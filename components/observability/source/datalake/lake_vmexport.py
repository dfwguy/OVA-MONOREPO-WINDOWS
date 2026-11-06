#!/usr/bin/env python3
"""
nvis-lake-vmexport — VictoriaMetrics -> Parquet mirror (the metrics lane).

CONTRACT THIS SERVICE IMPLEMENTS
    "Whatever goes into VictoriaMetrics and Prometheus also goes into Parquet."

It makes that TRUE BY CONSTRUCTION rather than by enumeration: it reads the
system of record itself (VM's /api/v1/export), so every producer is covered —
the 4 Prometheus shards, central Alloy's vm_fallback + platform_self, vmalert's
recording rules and ALERTS, and VM's own promscrape of the firehose targets.
93% of series and 66% of ingest never touch a Prometheus shard, so a
remote_write tee (option (a)) would silently miss the majority of the fleet;
future producers are covered here with zero wiring change.

WHY NOT A remote_write TEE
    - a tee must enumerate every producer, forever; vmalert cannot be teed at
      all (single --remoteWrite.url), and VM's promscrape lane cannot tee.
    - a dropped remote_write batch is PERMANENTLY lost — Prometheus will not
      re-send it. Here a lake outage self-heals: the bookmark is not advanced,
      so the next cycle re-reads the same window straight out of VM.

SAFETY PROPERTIES
    - READ-ONLY against the system of record. It cannot stall a scrape loop,
      cannot consume shard queue memory, cannot wedge in front of VM. Worst
      case it dies and VM is untouched.
    - Half-open windows [start, end). Sample timestamps are filtered
      client-side so the window boundary is exact regardless of whether VM's
      export endpoint treats `end` as inclusive. No dupes, no gaps.
    - The bookmark advances ONLY after the rows are durable Parquet
      (flush_stale(force=True) has returned). A crash mid-window replays it.
    - Disk guard: below MIN_FREE_BYTES the cycle is skipped WITHOUT advancing
      the bookmark, so backpressure defers data instead of destroying it.

Env: VM_EXPORT_URL, VM_LABEL_API, LAKE_ROOT, CLUSTER_NAME, EXPORT_INTERVAL_S,
EXPORT_LAG_S, EXPORT_MAX_WINDOW_S, EXPORT_BACKFILL_S, EXPORT_CHUNK_BY_JOB,
EXPORT_BATCH_ROWS, MIN_FREE_BYTES, METRICS_PORT(9412).
"""
from __future__ import annotations
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pyarrow as pa

from lake_common import LakeSink, IDENTITY, CLUSTER, LAKE_ROOT, LANDING
from schema import METRICS_SCHEMA

VM_EXPORT_URL = os.environ.get("VM_EXPORT_URL", "http://127.0.0.1:8429/api/v1/export")
VM_LABEL_API = os.environ.get(
    "VM_LABEL_API", "http://127.0.0.1:8429/api/v1/label/job/values")
INTERVAL_S = int(os.environ.get("EXPORT_INTERVAL_S", "300"))
# Trail real-time so late remote_write batches have landed in VM first.
LAG_S = int(os.environ.get("EXPORT_LAG_S", "120"))
# Cap a single catch-up window so a long outage backfills in bounded chunks.
MAX_WINDOW_S = int(os.environ.get("EXPORT_MAX_WINDOW_S", "900"))
# On first start with no bookmark, how far back to reach.
BACKFILL_S = int(os.environ.get("EXPORT_BACKFILL_S", "600"))
CHUNK_BY_JOB = os.environ.get("EXPORT_CHUNK_BY_JOB", "1") not in ("0", "false", "")
BATCH_ROWS = int(os.environ.get("EXPORT_BATCH_ROWS", "200000"))
MIN_FREE = int(os.environ.get("MIN_FREE_BYTES", str(200 * 1024 ** 3)))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9412"))
HTTP_TIMEOUT = int(os.environ.get("EXPORT_HTTP_TIMEOUT", "300"))

STATE_DIR = LAKE_ROOT / "_state"
BOOKMARK = STATE_DIR / "vmexport.json"

# ---- self metrics ----------------------------------------------------------
_M = {
    "cycles": 0, "errors": 0, "samples": 0, "series": 0, "rows": 0,
    "bytes_downloaded": 0, "skipped_no_space": 0, "null_samples": 0,
    "last_window_end_ms": 0, "last_cycle_s": 0.0, "last_ok": 0.0,
    "written_rows": {}, "written_bytes": {},
}
_MLOCK = threading.Lock()


def _on_flush(table, rows, nbytes, lag):
    with _MLOCK:
        _M["written_rows"][table] = _M["written_rows"].get(table, 0) + rows
        _M["written_bytes"][table] = _M["written_bytes"].get(table, 0) + nbytes


SINK = LakeSink(on_flush=_on_flush)


def _free_bytes() -> int:
    """Tightest free space across the paths that actually receive lake writes."""
    vals = []
    for p in (LANDING, LAKE_ROOT):
        try:
            vals.append(shutil.disk_usage(p).free)
        except Exception:
            pass
    return min(vals) if vals else 0


# ---- bookmark --------------------------------------------------------------
def read_bookmark() -> int | None:
    try:
        return int(json.loads(BOOKMARK.read_text())["last_end_ms"])
    except Exception:
        return None


def write_bookmark(end_ms: int):
    """Atomic bookmark commit — a torn bookmark would silently skip a window."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BOOKMARK.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({
        "last_end_ms": int(end_ms),
        "last_end_iso": _iso(end_ms),
        "updated": _iso(int(time.time() * 1000)),
    }))
    os.replace(tmp, BOOKMARK)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.") + f"{int(ms) % 1000:03d}Z"


# ---- VM access -------------------------------------------------------------
def _get(url: str, params: list[tuple[str, str]]):
    q = urllib.parse.urlencode(params, doseq=True)
    return urllib.request.urlopen(f"{url}?{q}", timeout=HTTP_TIMEOUT)


def job_selectors(start_ms: int, end_ms: int) -> list[str]:
    """Complete, non-overlapping cover of every series present in the window.

    One selector per job label value, plus `job=""` which VM matches against
    series that carry no job label at all. Union == {__name__!=""} with no
    double counting, while bounding VM-side and local memory per request.
    Falls back to the single catch-all selector if the label API fails.
    """
    if not CHUNK_BY_JOB:
        return ['{__name__!=""}']
    try:
        with _get(VM_LABEL_API, [("start", _iso(start_ms)), ("end", _iso(end_ms))]) as r:
            jobs = json.loads(r.read()).get("data", [])
    except Exception as e:
        print(f"WARN label API failed ({e}); falling back to catch-all", flush=True)
        return ['{__name__!=""}']
    sels = ['{__name__!="",job=""}']
    for j in jobs:
        if j:
            sels.append('{job="%s"}' % j.replace("\\", "\\\\").replace('"', '\\"'))
    return sels


def _rows_to_table(rows):
    cols = {f.name: [r.get(f.name) for r in rows] for f in METRICS_SCHEMA}
    return pa.Table.from_pydict(cols, schema=METRICS_SCHEMA)


def _row(lbls: dict, ts_ms: int, value):
    """Field derivation kept byte-identical to lakewriter.decode_remote_write.

    Both lanes must produce the same rows, otherwise the same metric would look
    different depending on which path happened to carry it.
    """
    name = lbls.pop("__name__", "unknown")
    node = lbls.get("node") or lbls.get("Hostname") or lbls.get("instance", "")
    su, rack = IDENTITY.lookup(node, lbls)
    gpu = lbls.get("gpu") or lbls.get("GPU_I_ID")
    return {
        "ts": int(ts_ms) * 1000,          # ms -> us
        "metric": name, "value": value, "cluster": CLUSTER,
        "su": su, "rack": rack, "node": node,
        "gpu": int(gpu) if gpu and str(gpu).isdigit() else None,
        "job": lbls.get("job"), "instance": lbls.get("instance"),
        "labels": {k: v for k, v in lbls.items() if k not in ("job", "instance")},
    }


def _split_selector(sel: str, start_ms: int, end_ms: int) -> list[str]:
    """Break one oversized job selector into per-metric-name selectors.

    VictoriaMetrics refuses a query whose match set exceeds
    -search.maxUniqueTimeseries (10,000,000 here) with HTTP 400. On this fleet
    {job="node-exporter"} is over that on its own. Splitting by __name__ bounds
    the series per request without dropping anything.
    """
    job = re.search(r'job="([^"]*)"', sel)
    if not job:
        return []
    try:
        # NOTE: this VM build rejects match[] on the label-values API with 422,
        # so ask for all metric names in the window and pair each with the job.
        # A name that does not occur for this job simply exports zero rows.
        with _get(VM_LABEL_NAME_API,
                  [("start", _iso(start_ms)), ("end", _iso(end_ms))]) as r:
            names = json.loads(r.read()).get("data", [])
    except Exception as e:
        print(f"WARN split: metric-name API failed for {sel}: {e}", flush=True)
        return []
    esc = job.group(1).replace("\\", "\\\\").replace('"', '\\"')
    return ['{job="%s",__name__="%s"}' % (esc, n.replace('"', '\\"'))
            for n in names if n]


def export_window(start_ms: int, end_ms: int) -> tuple[int, int]:
    """Mirror [start_ms, end_ms) from VM into the lake. Returns (series, rows).

    FAILURE ISOLATION. This used to let one selector's exception propagate out
    of the function, which aborted cycle() BEFORE write_bookmark(). The bookmark
    then never advanced and the identical window was re-exported every 5 minutes
    forever: on 2026-08-13 the lake held 133,009 duplicate files of one 15-minute
    window from 2026-08-06 08:22-08:37, ~9.7 GB/day of replay, and the metrics
    lane had ingested nothing new for SEVEN DAYS while looking busy. A single
    over-large job must degrade to "that job is missing from this window",
    never to "time stops".
    """
    failed: list[str] = []
    total_series = total_rows = 0
    selectors = list(job_selectors(start_ms, end_ms))
    idx = 0
    while idx < len(selectors):
        sel = selectors[idx]
        idx += 1
        try:
            params = [("match[]", sel), ("start", _iso(start_ms)), ("end", _iso(end_ms)),
                      ("reduce_mem_usage", "1")]
            batch: list[dict] = []
            with _get(VM_EXPORT_URL, params) as resp:
                for raw_line in resp:                    # stream: bounded memory
                    with _MLOCK:
                        _M["bytes_downloaded"] += len(raw_line)
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        obj = json.loads(raw_line)
                    except Exception:
                        with _MLOCK:
                            _M["errors"] += 1
                        continue
                    lbls = dict(obj.get("metric", {}))
                    values = obj.get("values") or []
                    stamps = obj.get("timestamps") or []
                    total_series += 1
                    for v, tms in zip(values, stamps):
                        # Half-open [start, end): exact boundary regardless of how
                        # VM treats `end`. This is what makes windows dupe-free.
                        if not (start_ms <= tms < end_ms):
                            continue
                        if v is None:        # VM renders NaN staleness markers null
                            v = float("nan")
                            with _MLOCK:
                                _M["null_samples"] += 1
                        batch.append(_row(dict(lbls), tms, float(v)))
                    if len(batch) >= BATCH_ROWS:
                        SINK.add_table("metrics", _rows_to_table(batch))
                        total_rows += len(batch)
                        batch = []
            if batch:
                SINK.add_table("metrics", _rows_to_table(batch))
                total_rows += len(batch)
        except Exception as e:
            msg = str(e)
            subs = (_split_selector(sel, start_ms, end_ms)
                    if ("exceeds" in msg or "400" in msg) else [])
            if subs:
                print(f"SPLIT {sel}: {msg[:80]} -> {len(subs)} sub-selectors",
                      flush=True)
                selectors.extend(subs)
                continue
            # Record and move on. Losing one job for one window is recoverable;
            # stalling the bookmark is not.
            failed.append(sel)
            with _MLOCK:
                _M["selector_failures"] = _M.get("selector_failures", 0) + 1
            print(f"SELECTOR FAILED {sel}: {msg[:160]}", flush=True)
    if failed:
        print(f"WINDOW {_iso(start_ms)}..{_iso(end_ms)} INCOMPLETE: "
              f"{len(failed)} selector(s) failed: {failed[:5]}", flush=True)
        try:
            gaps = Path(os.environ.get("LAKE_GAPS_FILE",
                                       "/data/lake/_state/export_gaps.jsonl"))
            gaps.parent.mkdir(parents=True, exist_ok=True)
            with open(gaps, "a") as fh:
                fh.write(json.dumps({"start_ms": start_ms, "end_ms": end_ms,
                                     "failed": failed}) + "\n")
        except Exception:
            pass
    return total_series, total_rows


def cycle() -> bool:
    now_ms = int(time.time() * 1000)
    end_ms = now_ms - LAG_S * 1000
    start_ms = read_bookmark()
    if start_ms is None:
        start_ms = end_ms - BACKFILL_S * 1000
    if end_ms <= start_ms:
        return True
    # Bound catch-up so a long outage is drained in digestible windows.
    end_ms = min(end_ms, start_ms + MAX_WINDOW_S * 1000)

    free = _free_bytes()
    if free < MIN_FREE:
        # Do NOT advance the bookmark: defer, do not destroy. When space is
        # reclaimed the same window is re-read straight out of VM.
        with _MLOCK:
            _M["skipped_no_space"] += 1
        print(f"SKIP window {_iso(start_ms)}..{_iso(end_ms)}: free={free} "
              f"< MIN_FREE={MIN_FREE}", flush=True)
        return False

    t0 = time.time()
    series, rows = export_window(start_ms, end_ms)
    SINK.flush_stale(force=True)          # durable Parquet BEFORE the bookmark
    write_bookmark(end_ms)
    dt = time.time() - t0
    with _MLOCK:
        _M["cycles"] += 1
        _M["series"] += series
        _M["rows"] += rows
        _M["samples"] += rows
        _M["last_window_end_ms"] = end_ms
        _M["last_cycle_s"] = dt
        _M["last_ok"] = time.time()
    print(f"window {_iso(start_ms)}..{_iso(end_ms)} series={series} rows={rows} "
          f"in {dt:.2f}s", flush=True)
    return True


# ---- self-observability ----------------------------------------------------
def render_metrics() -> str:
    with _MLOCK:
        m = dict(_M)
        wrows = dict(_M["written_rows"])
        wbytes = dict(_M["written_bytes"])
    end_s = m["last_window_end_ms"] / 1000.0
    lag = (time.time() - end_s) if end_s else -1
    out = [
        "# nvis-lake-vmexport self metrics",
        "nvis_lake_export_up 1",
        f"nvis_lake_export_cycles_total {m['cycles']}",
        f"nvis_lake_export_errors_total {m['errors']}",
        f"nvis_lake_export_rows_total {m['rows']}",
        f"nvis_lake_export_series_total {m['series']}",
        f"nvis_lake_export_null_samples_total {m['null_samples']}",
        f"nvis_lake_export_bytes_downloaded_total {m['bytes_downloaded']}",
        f"nvis_lake_export_skipped_no_space_total {m['skipped_no_space']}",
        f"nvis_lake_export_last_window_end_timestamp {end_s:.0f}",
        f"nvis_lake_export_lag_seconds {lag:.1f}",
        f"nvis_lake_export_cycle_duration_seconds {m['last_cycle_s']:.3f}",
        f"nvis_lake_export_nvme_free_bytes {_free_bytes()}",
    ]
    for t, v in wrows.items():
        out.append(f'nvis_lake_export_written_rows_total{{table="{t}"}} {v}')
    for t, v in wbytes.items():
        out.append(f'nvis_lake_export_written_bytes_total{{table="{t}"}} {v}')
    return "\n".join(out) + "\n"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body=b""):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, b"ok")
        if self.path == "/metrics":
            return self._send(200, render_metrics().encode())
        self._send(404)


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("0.0.0.0", METRICS_PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"nvis-lake-vmexport up: src={VM_EXPORT_URL} root={LAKE_ROOT} "
          f"interval={INTERVAL_S}s lag={LAG_S}s metrics=:{METRICS_PORT}", flush=True)
    while True:
        try:
            # Drain backlog quickly: keep cycling while more than one full
            # window is outstanding, otherwise sleep until the next interval.
            caught_up = cycle()
            bm = read_bookmark() or 0
            behind = time.time() * 1000 - LAG_S * 1000 - bm
            if caught_up and behind > MAX_WINDOW_S * 1000:
                continue
        except Exception as e:
            with _MLOCK:
                _M["errors"] += 1
            print(f"cycle error: {type(e).__name__}: {e}", flush=True)
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
