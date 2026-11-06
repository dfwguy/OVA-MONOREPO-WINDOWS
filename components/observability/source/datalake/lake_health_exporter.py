#!/usr/bin/env python3
"""lake_health_exporter — the metrics the datalake alerts need, on :9414.

Written because the alerts in vmalert/rules/40-datalake-pipeline.yml would
otherwise reference series that do not exist, and a rule that can never fire is
worse than no rule: it looks like coverage.

Everything here answers "is the lake making PROGRESS", not "is the process
alive". Every failure this stack has had was a live, busy process delivering
nothing:
  * vmexport re-exported one 15-minute window 589 times for 7 days
  * lake-compact OOM-looped 2,762 times with docker RestartCount stuck at 0
  * run capture died and coverage decayed silently for 6 days

Reads are cheap and bounded: state files, a du-style walk capped by depth, and
one Parquet footer read. No log parsing, no sacct call on the scrape path
(sacct truth is refreshed by the census itself and cached here).
"""
from __future__ import annotations
import json
import os
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LAKE = os.environ.get("LAKE_ROOT", "/data/lake")
STATE = os.path.join(LAKE, "_state")
LANDING = os.path.join(LAKE, "landing")
SCRATCH = os.path.join(LAKE, "tmp")
CENSUS = os.path.join(LAKE, "curated", "slurm_jobs", "part-000.parquet")
PORT = int(os.environ.get("METRICS_PORT", "9414"))
CACHE_S = int(os.environ.get("LAKE_HEALTH_CACHE_S", "60"))

_cache: dict = {"at": 0.0, "text": ""}


def _read_ts(name: str) -> float:
    try:
        with open(os.path.join(STATE, name)) as fh:
            return float(fh.read().strip())
    except Exception:
        return 0.0


def _dir_bytes(path: str, max_depth: int = 6) -> int:
    total = 0
    base_depth = path.rstrip("/").count("/")
    for root, dirs, files in os.walk(path):
        if root.count("/") - base_depth >= max_depth:
            dirs[:] = []
        for f in files:
            try:
                total += os.stat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def _largest_landing_partition() -> tuple[str, int]:
    """Biggest single hour-partition. One hour of one rack is ~0.5 GB; anything
    near 20 GB means a producer is looping, which is what killed the compactor."""
    worst, worst_b = "", 0
    metrics_root = os.path.join(LANDING, "metrics")
    if not os.path.isdir(metrics_root):
        return worst, worst_b
    for root, dirs, files in os.walk(metrics_root):
        if not os.path.basename(root).startswith("hour="):
            continue
        dirs[:] = []
        b = 0
        try:
            for f in os.scandir(root):
                if f.is_file():
                    b += f.stat().st_size
        except OSError:
            continue
        if b > worst_b:
            worst, worst_b = root.replace(LANDING + "/", ""), b
    return worst, worst_b


def collect() -> str:
    out = []

    def m(name, val, typ="gauge", help_=""):
        if help_:
            out.append(f"# HELP {name} {help_}")
        out.append(f"# TYPE {name} {typ}")
        out.append(f"{name} {val}")

    census_ok = _read_ts("census_last_ok")
    backfill_ok = _read_ts("backfill_last_ok")
    m("nvis_lake_census_last_ok_timestamp", int(census_ok), "gauge",
      "Unix time the job census last completed successfully")
    m("nvis_lake_backfill_last_ok_timestamp", int(backfill_ok), "gauge",
      "Unix time the run backfill last completed successfully")

    # Census size + the sacct truth it reconciled against.
    rows = truth = 0
    try:
        import duckdb
        rows = duckdb.connect().execute(
            f"SELECT count(*) FROM read_parquet('{CENSUS}')").fetchone()[0]
    except Exception:
        rows = 0
    try:
        truth = int(json.load(open(os.path.join(STATE, "census_truth.json")))["sacct_rows"])
    except Exception:
        truth = rows
    m("nvis_lake_census_rows", rows, "gauge", "Rows in the Slurm job census")
    m("nvis_lake_census_sacct_truth", truth, "gauge", "sacct row count at last census")

    # Run coverage: benchmark jobs with a parsed result / benchmark jobs finished.
    ratio = 1.0
    try:
        import duckdb
        con = duckdb.connect()
        tot = con.execute(
            f"SELECT count(*) FROM read_parquet('{CENSUS}') WHERE workload_class "
            f"IN ('nccl','llama','nemo','mnubergemm') AND state='COMPLETED'").fetchone()[0]
        got = con.execute(
            f"SELECT count(*) FROM read_parquet('{CENSUS}') WHERE workload_class "
            f"IN ('nccl','llama','nemo','mnubergemm') AND state='COMPLETED' "
            f"AND result_status='log_present'").fetchone()[0]
        ratio = (got / tot) if tot else 1.0
        m("nvis_lake_run_jobs_total", tot)
        m("nvis_lake_run_jobs_with_result", got)
    except Exception:
        pass
    m("nvis_lake_run_coverage_ratio", round(ratio, 4), "gauge",
      "Finished benchmark jobs that have a parsed result in the lake")

    # Capacity / pathology.
    scratch = _dir_bytes(SCRATCH, max_depth=2) if os.path.isdir(SCRATCH) else 0
    m("nvis_lake_scratch_bytes", scratch, "gauge",
      "DuckDB spill bytes; a bounded-RAM sort once spilled 1.2 TB here")
    try:
        m("nvis_lake_free_bytes", shutil.disk_usage(LAKE).free, "gauge",
          "Free bytes on the lake device (shared with VictoriaMetrics and Loki)")
    except Exception:
        pass
    part, pb = _largest_landing_partition()
    if part:
        out.append("# TYPE nvis_lake_landing_partition_bytes gauge")
        out.append(f'nvis_lake_landing_partition_bytes{{partition="{part}"}} {pb}')

    # UNKNOWN-partition share: the identity bug sent 93.8% of the fleet here.
    unk = 0
    try:
        unk = _dir_bytes(os.path.join(LANDING, "metrics", "cluster=IREN_MKZ",
                                      "su=UNKNOWN"), max_depth=4)
    except Exception:
        pass
    m("nvis_lake_unknown_partition_bytes", unk, "gauge",
      "Bytes landed with unresolved su/rack identity")
    m("nvis_lake_health_scrape_timestamp", int(time.time()))
    return "\n".join(out) + "\n"


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/healthz"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        now = time.time()
        if now - _cache["at"] > CACHE_S:
            try:
                _cache["text"] = collect()
            except Exception as e:
                _cache["text"] = f"# collect error: {type(e).__name__}\n"
            _cache["at"] = now
        body = _cache["text"].encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"lake_health_exporter on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
