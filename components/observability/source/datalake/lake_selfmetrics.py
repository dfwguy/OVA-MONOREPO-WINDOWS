#!/usr/bin/env python3
"""
lake_selfmetrics.py — self-observability for nvis-lakewriter.

WHY THIS FILE EXISTS
--------------------
On 2026-07-23..27 the lake wrote NOTHING for three days and every metric it
exposed said it was healthy. GET /metrics emitted exactly three series:

    nvis_lake_up 1
    nvis_lake_spool_bytes 0
    nvis_lake_nvme_free_bytes 19362443264

There was no way to tell that apart from a lake that was working perfectly and
happened to be idle, because the interesting series DID NOT EXIST. The original
render_metrics() only iterates dicts that are populated lazily:

    for t, v in _M["rows"].items():   # empty dict -> emits NOTHING

A counter that is absent cannot be alerted on. `increase(nvis_lake_rows_written_total[1h]) == 0`
matches no series, so the alert never fires and the dashboard panel is blank —
which is indistinguishable from "quiet". That is the exact "blank read as
healthy" failure the platform-self-health rules were written to outlaw.

This module fixes that by ZERO-INITIALISING every series the writer is capable
of producing, so "zero rows in the last hour" is an observable NUMBER rather
than an absent series, and by adding the signals that would have caught each of
the four faults in this outage:

  fault A (nobody ever POSTed)     -> nvis_lake_ingest_requests_total{endpoint,code}
                                      nvis_lake_last_ingest_timestamp_seconds
  fault B (admission 429 storm)    -> nvis_lake_admission_ok
                                      nvis_lake_ingest_errors_total{stage,reason}
  fault B (stale /data bind mount)  -> nvis_lake_fs_info{path,device,fstype,mountpoint}
                                      nvis_lake_fs_is_expected_device{path}
                                      nvis_lake_fs_size_bytes{path}
  fault B2 (spool bind missing)    -> nvis_lake_path_exists{path="spool"}
                                      per-path fs metrics (spool device != lake device)
  "wrote nothing"                  -> nvis_lake_files_written_total{table}
                                      nvis_lake_table_files{table,zone}
                                      nvis_lake_table_disk_bytes{table,zone}
                                      nvis_lake_last_write_timestamp_seconds{table}

DESIGN CONSTRAINT: minimal blast radius on lakewriter.py.
This module is installed by exactly TWO added lines in lakewriter.py:

    import lake_selfmetrics                  # with the other local imports
    lake_selfmetrics.install(sys.modules[__name__])   # first line of main()

install() MONKEYPATCHES rather than edits: it wraps the host module's existing
render_metrics(), wraps LakeSink's on_flush callback, and wraps Handler._send.
The host's own code is never modified, so this module cannot regress the
writer's exposition and stays applied across unrelated edits to lakewriter.py.

MERGE SEMANTICS: the base exposition always wins. render() parses the host's
output into series keys and only appends a series if that exact key is absent.
So a real value from the host is never shadowed by one of our zeroes, and any
metric a future edit adds to render_metrics() passes through untouched.

Stdlib only — no pyarrow, no third-party imports. A bug here must never be able
to take the writer down, so every public entry point is exception-guarded and
degrades to "emit what we have".
"""
from __future__ import annotations

import os
import re
import threading
import time

# ---- configuration ---------------------------------------------------------
# Tables this writer is CAPABLE of producing. Zero-initialised so "no rows" is a
# number, not an absent series. Deliberately NOT schema.SCHEMAS.keys(): tables
# with no producer in this process (fabric_phy is a separate halted container;
# switch_events/writer_meta have no producer at all) would emit a permanent
# zero and make "zero rows in 1h" fire forever on something that is not broken.
WRITER_TABLES = tuple(
    t.strip() for t in os.environ.get("LAKE_WRITER_TABLES", "metrics,logs").split(",")
    if t.strip()
)

# Endpoints zero-initialised in nvis_lake_ingest_requests_total. Anything not
# listed collapses to endpoint="other" to bound cardinality, so a new POST route
# added to lakewriter.py should be added here too or it becomes invisible.
INGEST_ENDPOINTS = tuple(
    e.strip() for e in os.environ.get(
        "LAKE_INGEST_ENDPOINTS",
        "/api/v1/write,/loki/api/v1/push,/v1/logs,/v1/artifacts").split(",")
    if e.strip()
)

# Error slots zero-initialised so "errors rising" has a floor to rise from.
ERROR_SLOTS = (("admission", "backpressure"), ("decode", "exception"),
               ("replay", "exception"))

# Drop reasons the writer can emit without any traffic at all.
DROP_REASONS = ("admission_429",)

# Filesystem the lake is SUPPOSED to be on. The 2026-07-23 bind bug pinned
# /data/lake to the 98G root LV because the bind was created before the NVMe was
# mounted at /data. Matching the resolved device against this regex turns that
# into a boolean alert instead of a number a human has to recognise as wrong.
EXPECTED_DEVICE_RE = os.environ.get("LAKE_EXPECTED_DEVICE_RE", "nvme")

DISK_SCAN_SECONDS = int(os.environ.get("LAKE_DISK_SCAN_SECONDS", "60"))
DISK_SCAN_MAX_FILES = int(os.environ.get("LAKE_DISK_SCAN_MAX_FILES", "400000"))
DISK_SCAN_BUDGET_S = float(os.environ.get("LAKE_DISK_SCAN_BUDGET_SECONDS", "10"))

_START = time.time()
_LOCK = threading.Lock()

# ---- mutable state ---------------------------------------------------------
_host = None                      # the lakewriter module
_base_render = None               # the original render_metrics()
_files: dict[str, int] = {}       # table -> parquet files written this process
_last_write: dict[str, float] = {}  # table -> epoch of last successful flush
_req: dict[tuple[str, str], int] = {}      # (endpoint, code) -> count
_req_bytes: dict[str, int] = {}            # endpoint -> body bytes accepted
_errors: dict[tuple[str, str], int] = {}   # (stage, reason) -> count
_last_ingest = 0.0
_scan = {"ts": 0.0, "dur": 0.0, "truncated": 0, "zones": {}, "tables": {}}


# ---- helpers ---------------------------------------------------------------
def _esc(v) -> str:
    """Escape a Prometheus label VALUE (backslash, quote, newline)."""
    return (str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " "))


def _line(name: str, labels: dict | None, value) -> str:
    if labels:
        inner = ",".join(f'{k}="{_esc(v)}"' for k, v in sorted(labels.items()))
        return f"{name}{{{inner}}} {value}"
    return f"{name} {value}"


def _key(line: str) -> str:
    """Series identity of an exposition line: everything left of the value.

    Label ORDER differs between the host's hand-built lines and ours, so the
    key normalises by sorting the label pairs. Without this, the host emitting
    nvis_lake_rows_written_total{table="metrics"} and us emitting the same
    series with different label order would both survive into the exposition
    and VictoriaMetrics would ingest a duplicate.
    """
    s = line.split("#", 1)[0].strip()
    if not s:
        return ""
    name = s.split("{", 1)[0].split(" ", 1)[0]
    if "{" not in s:
        return name
    inner = s[s.index("{") + 1: s.rindex("}")]
    parts = sorted(p.strip() for p in inner.split(",") if p.strip())
    return name + "{" + ",".join(parts) + "}"


# ---- filesystem introspection ---------------------------------------------
def _mounts() -> list[tuple[str, str, str]]:
    """[(device, mountpoint, fstype)] from /proc/mounts, longest mountpoint first."""
    out = []
    try:
        with open("/proc/mounts") as fh:
            for ln in fh:
                f = ln.split()
                if len(f) >= 3:
                    # octal-escaped spaces etc. in mountpoints
                    mp = f[1].replace("\\040", " ")
                    out.append((f[0], mp, f[2]))
    except Exception:
        pass
    out.sort(key=lambda t: len(t[1]), reverse=True)
    return out


def _fs_for(path) -> tuple[str, str, str]:
    """(device, fstype, mountpoint) actually backing `path`."""
    try:
        rp = os.path.realpath(str(path))
    except Exception:
        return ("unknown", "unknown", "unknown")
    for dev, mp, fstype in _mounts():
        if rp == mp or rp.startswith(mp.rstrip("/") + "/") or mp == "/":
            return (dev, fstype, mp)
    return ("unknown", "unknown", "unknown")


def _statvfs(path):
    """(size, free, avail) bytes, or None when the path cannot be measured."""
    try:
        st = os.statvfs(str(path))
        return (st.f_blocks * st.f_frsize, st.f_bfree * st.f_frsize,
                st.f_bavail * st.f_frsize)
    except Exception:
        return None


# ---- disk scan -------------------------------------------------------------
def _scan_zone(root, zone, tables, budget_end):
    """Walk landing/curated -> per-table (files, bytes, newest mtime).

    Layout is <zone>/<table>/cluster=../su=../rack=../date=../hour=../part-*.parquet
    so the first level under the zone is the table name. Uses os.scandir (not
    os.walk) because DirEntry caches the stat we need for size/mtime, halving
    the syscalls on a tree that will hold millions of files at full fleet.
    """
    truncated = False
    try:
        tdirs = [e for e in os.scandir(str(root)) if e.is_dir(follow_symlinks=False)]
    except Exception:
        return False
    for tdir in tdirs:
        table = tdir.name
        agg = tables.setdefault((table, zone), [0, 0, 0.0])
        stack = [tdir.path]
        while stack:
            if time.time() > budget_end or agg[0] > DISK_SCAN_MAX_FILES:
                truncated = True
                break
            cur = stack.pop()
            try:
                entries = list(os.scandir(cur))
            except Exception:
                continue
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    elif e.name.endswith(".parquet"):
                        st = e.stat(follow_symlinks=False)
                        agg[0] += 1
                        agg[1] += st.st_size
                        if st.st_mtime > agg[2]:
                            agg[2] = st.st_mtime
                except Exception:
                    continue
    return truncated


def _do_scan():
    """Refresh the cached on-disk view. Bounded by time and file count."""
    t0 = time.time()
    budget_end = t0 + DISK_SCAN_BUDGET_S
    tables: dict[tuple[str, str], list] = {}
    truncated = False
    root = getattr(_host, "LAKE_ROOT", None)
    if root is not None:
        for zone in ("landing", "curated"):
            try:
                truncated |= bool(_scan_zone(os.path.join(str(root), zone), zone,
                                             tables, budget_end))
            except Exception:
                pass
    # Zero-fill so an empty lake reports 0 files rather than no series at all —
    # this is the whole point of the module.
    for t in WRITER_TABLES:
        for zone in ("landing", "curated"):
            tables.setdefault((t, zone), [0, 0, 0.0])
    zones: dict[str, list] = {}
    for (t, zone), v in tables.items():
        z = zones.setdefault(zone, [0, 0])
        z[0] += v[0]
        z[1] += v[1]
    for zone in ("landing", "curated"):
        zones.setdefault(zone, [0, 0])
    with _LOCK:
        _scan.update({"ts": time.time(), "dur": time.time() - t0,
                      "truncated": 1 if truncated else 0,
                      "zones": zones, "tables": tables})


def _scan_loop():
    while True:
        try:
            _do_scan()
        except Exception:
            pass
        time.sleep(max(5, DISK_SCAN_SECONDS))


# ---- instrumentation hooks -------------------------------------------------
def _patch_sink_class(lake_common_mod):
    """Count parquet FILES by patching LakeSink._flush_one at the CLASS level.

    Why the class and not SINK's on_flush callback: the lake has grown MORE THAN
    ONE sink. lakewriter builds the module-level SINK, but the artifact/NCCL
    lanes construct their own LakeSink instances, and any sink built before or
    after install() captured its own on_flush reference. Wrapping one instance's
    callback therefore undercounts silently — measured live:
    nvis_lake_rows_written_total{table="run_artifacts"} climbed to 23 while
    files_written_total stayed at 0, because those rows were flushed by a sink
    this module had never touched.

    _flush_one is the single place every Parquet file in the lake is produced,
    so patching it on the class covers every instance, past and future, whoever
    built it. Guarded on pb.batches because _flush_one returns early (writing
    nothing) when the buffer is empty.
    """
    cls = getattr(lake_common_mod, "LakeSink", None)
    if cls is None or getattr(cls, "_nvis_selfmetrics_patched", False):
        return
    orig = cls._flush_one

    def _flush_one(self, table, pb):
        had = bool(getattr(pb, "batches", None))
        result = orig(self, table, pb)
        if had:
            try:
                with _LOCK:
                    _files[table] = _files.get(table, 0) + 1
                    _last_write[table] = time.time()
            except Exception:
                pass
        return result

    cls._flush_one = _flush_one
    cls._nvis_selfmetrics_patched = True


def _norm_endpoint(path: str) -> str:
    """Bound label cardinality: unknown paths collapse to a single 'other'."""
    p = (path or "").split("?", 1)[0]
    for e in INGEST_ENDPOINTS:
        if p == e or p.startswith(e):
            return e
    return "other"


def _patch_handler(handler):
    """Wrap Handler._send to count POST outcomes by endpoint and status code.

    _send is the single funnel every response passes through (200/204/404/429),
    so wrapping it captures admission rejections too — which is precisely the
    signal that was missing: nvis_lake_dropped_total only appears AFTER a first
    drop, and requests that were never made leave no trace whatsoever.
    """
    orig = handler._send

    def _send(self, code, body=b""):
        try:
            if getattr(self, "command", "") == "POST":
                ep = _norm_endpoint(getattr(self, "path", ""))
                global _last_ingest
                with _LOCK:
                    _req[(ep, str(code))] = _req.get((ep, str(code)), 0) + 1
                    if code in (200, 204):
                        n = len(getattr(self, "_body", b"") or b"")
                        _req_bytes[ep] = _req_bytes.get(ep, 0) + n
                        _last_ingest = time.time()
                    elif code == 429:
                        _errors[("admission", "backpressure")] = \
                            _errors.get(("admission", "backpressure"), 0) + 1
        except Exception:
            pass
        return orig(self, code, body)

    handler._send = _send


def _sync_errors_from_host():
    """Mirror the host's _M['dropped'] into (stage, reason) error slots.

    The host records drops as free-form strings ('admission_429',
    'decode_err:TypeError', 'replay_err:OSError'). Splitting them into a stage
    and a reason gives a stable low-cardinality alerting surface while the raw
    nvis_lake_dropped_total is still emitted verbatim by the host.
    """
    try:
        m = getattr(_host, "_M", None)
        if not m:
            return
        lock = getattr(_host, "_MLOCK", None)
        snap = {}
        if lock:
            with lock:
                snap = dict(m.get("dropped", {}))
        else:
            snap = dict(m.get("dropped", {}))
        agg: dict[tuple[str, str], int] = {}
        for reason, n in snap.items():
            if reason.startswith("decode_err"):
                slot = ("decode", reason.split(":", 1)[-1] if ":" in reason else "exception")
            elif reason.startswith("replay_err"):
                slot = ("replay", reason.split(":", 1)[-1] if ":" in reason else "exception")
            elif reason.startswith("admission"):
                slot = ("admission", "backpressure")
            else:
                slot = ("other", reason)
            agg[slot] = agg.get(slot, 0) + n
        with _LOCK:
            for k, v in agg.items():
                # admission is counted live in _patch_handler; take the max so a
                # restart-replayed host counter cannot double-count.
                _errors[k] = max(_errors.get(k, 0), v)
    except Exception:
        pass


# ---- rendering -------------------------------------------------------------
def _extra_lines() -> list[str]:
    out: list[str] = []
    host = _host
    now = time.time()

    out.append("# --- nvis-lakewriter extended self-observability (lake_selfmetrics) ---")
    out.append(_line("nvis_lake_build_info",
                     {"component": "lakewriter", "selfmetrics": "1"}, 1))
    out.append(_line("nvis_lake_start_time_seconds", None, f"{_START:.0f}"))

    # -- zero-init of the host's lazily-created per-table series --------------
    # Emitted only when absent from the base exposition (see render()), so a
    # real value is never shadowed. This is what makes the "zero rows in 1h"
    # alert able to fire at all.
    with _LOCK:
        files = dict(_files)
        last_write = dict(_last_write)
        req = dict(_req)
        req_bytes = dict(_req_bytes)
        errors = dict(_errors)
        scan = {"ts": _scan["ts"], "dur": _scan["dur"],
                "truncated": _scan["truncated"],
                "zones": dict(_scan["zones"]), "tables": dict(_scan["tables"])}
        last_ingest = _last_ingest

    tables = sorted(set(WRITER_TABLES) | set(files) | {t for (t, _) in scan["tables"]})
    for t in tables:
        lb = {"table": t}
        out.append(_line("nvis_lake_rows_written_total", lb, 0))
        out.append(_line("nvis_lake_bytes_written_total", lb, 0))
        out.append(_line("nvis_lake_flush_lag_seconds", lb, 0))
        out.append(_line("nvis_lake_partition_last_write_timestamp", lb, 0))
        # NEW: files actually produced, and a canonical *_seconds last-write.
        out.append(_line("nvis_lake_files_written_total", lb, files.get(t, 0)))
        out.append(_line("nvis_lake_last_write_timestamp_seconds", lb,
                         f"{last_write.get(t, 0.0):.0f}"))

    # -- on-disk truth: files and bytes that actually exist -------------------
    # bytes_written_total counts in-memory Arrow bytes handed to the writer;
    # it says nothing about whether a byte reached the NVMe. These do.
    for (t, zone), v in sorted(scan["tables"].items()):
        lb = {"table": t, "zone": zone}
        out.append(_line("nvis_lake_table_files", lb, v[0]))
        out.append(_line("nvis_lake_table_disk_bytes", lb, v[1]))
        out.append(_line("nvis_lake_table_last_file_timestamp_seconds", lb,
                         f"{v[2]:.0f}"))
    for zone, v in sorted(scan["zones"].items()):
        out.append(_line("nvis_lake_disk_files", {"zone": zone}, v[0]))
        out.append(_line("nvis_lake_disk_bytes", {"zone": zone}, v[1]))
    out.append(_line("nvis_lake_disk_scan_timestamp_seconds", None,
                     f"{scan['ts']:.0f}"))
    out.append(_line("nvis_lake_disk_scan_duration_seconds", None,
                     f"{scan['dur']:.4f}"))
    out.append(_line("nvis_lake_disk_scan_truncated", None, scan["truncated"]))

    # -- ingest: proves whether anybody is actually POSTing -------------------
    for ep in INGEST_ENDPOINTS:
        for code in ("200", "204", "429", "404"):
            k = (ep, code)
            if k in req or code in ("200", "204", "429"):
                out.append(_line("nvis_lake_ingest_requests_total",
                                 {"endpoint": ep, "code": code}, req.get(k, 0)))
        out.append(_line("nvis_lake_ingest_bytes_total", {"endpoint": ep},
                         req_bytes.get(ep, 0)))
    for (ep, code), v in sorted(req.items()):
        if ep not in INGEST_ENDPOINTS:
            out.append(_line("nvis_lake_ingest_requests_total",
                             {"endpoint": ep, "code": code}, v))
    out.append(_line("nvis_lake_last_ingest_timestamp_seconds", None,
                     f"{last_ingest:.0f}"))

    # -- ingest errors, zero-floored so a rise is detectable -----------------
    for slot in ERROR_SLOTS:
        errors.setdefault(slot, 0)
    for (stage, reason), v in sorted(errors.items()):
        out.append(_line("nvis_lake_ingest_errors_total",
                         {"stage": stage, "reason": reason}, v))
    # Zero-init the host's own drop counter so alerts have a series pre-outage.
    for r in DROP_REASONS:
        out.append(_line("nvis_lake_dropped_total", {"reason": r}, 0))

    # -- filesystem: size/used/avail + DEVICE IDENTITY per write target -------
    # The host emits free bytes and a numeric st_dev. st_dev alone cannot tell
    # an operator WHICH disk it landed on; nvis_lake_fs_info carries the device
    # name and nvis_lake_fs_is_expected_device turns "is this the NVMe?" into a
    # boolean an alert can evaluate.
    root = getattr(host, "LAKE_ROOT", None)
    paths = {}
    if root is not None:
        paths = {
            "lake_root": str(root),
            "landing": str(getattr(host, "LANDING", os.path.join(str(root), "landing"))),
            "curated": os.path.join(str(root), "curated"),
            "spool": str(getattr(host, "SPOOL", os.path.join(str(root), "raw_spool"))),
        }
    try:
        rx = re.compile(EXPECTED_DEVICE_RE)
    except Exception:
        rx = re.compile("nvme")
    for label, p in sorted(paths.items()):
        exists = 1 if os.path.exists(p) else 0
        out.append(_line("nvis_lake_path_exists", {"path": label}, exists))
        dev, fstype, mp = _fs_for(p)
        out.append(_line("nvis_lake_fs_info",
                         {"path": label, "device": dev, "fstype": fstype,
                          "mountpoint": mp}, 1))
        out.append(_line("nvis_lake_fs_is_expected_device", {"path": label},
                         1 if rx.search(dev or "") else 0))
        sv = _statvfs(p)
        if sv:
            size, free, avail = sv
            out.append(_line("nvis_lake_fs_size_bytes", {"path": label}, size))
            out.append(_line("nvis_lake_fs_avail_bytes", {"path": label}, avail))
            out.append(_line("nvis_lake_fs_used_bytes", {"path": label}, size - free))
            # NOTE: ratio and the fs_free_bytes parity line below both use AVAIL,
            # not free. The host's nvis_lake_fs_free_bytes comes from
            # shutil.disk_usage().free, which is f_bavail (excludes the
            # root-reserved blocks). f_bfree is ~385 GB larger on this ext4
            # volume, so mixing the two under one metric name would make the
            # "free space low" alert read differently depending on which code
            # path happened to emit the series for that path.
            out.append(_line("nvis_lake_fs_free_ratio", {"path": label},
                             f"{(avail / size):.6f}" if size else "0"))
            # Emitted for parity with the host's own name; render() drops it if
            # the host already published this exact series.
            out.append(_line("nvis_lake_fs_free_bytes", {"path": label}, avail))

    # -- admission control state: the gate that silently 429'd for 3 days ----
    min_free = int(getattr(host, "MIN_FREE", 0) or 0)
    spool_max = int(getattr(host, "SPOOL_MAX", 0) or 0)
    out.append(_line("nvis_lake_min_free_bytes", None, min_free))
    out.append(_line("nvis_lake_spool_max_bytes", None, spool_max))
    admission = 0
    try:
        free_now = int(host._free_bytes())
        spool_now = int(host._spool_bytes())
        admission = 1 if (spool_now <= spool_max and free_now >= min_free) else 0
        out.append(_line("nvis_lake_admission_free_bytes", None, free_now))
    except Exception:
        pass
    out.append(_line("nvis_lake_admission_ok", None, admission))
    try:
        spool_files = len([f for f in os.listdir(str(getattr(host, "SPOOL", "")))
                           if f.endswith(".seg")])
        out.append(_line("nvis_lake_spool_files", None, spool_files))
    except Exception:
        out.append(_line("nvis_lake_spool_files", None, 0))

    out.append(_line("nvis_lake_exporter_scrape_duration_seconds", None,
                     f"{time.time() - now:.6f}"))
    return out


def _make_render(base):
    def render_metrics() -> str:
        try:
            text = base()
        except Exception as e:                      # host renderer broke
            text = ("# nvis-lakewriter self metrics\nnvis_lake_up 1\n"
                    + _line("nvis_lake_exporter_base_render_errors_total",
                            {"kind": type(e).__name__}, 1) + "\n")
        try:
            _sync_errors_from_host()
            seen = set()
            lines = text.splitlines()
            for ln in lines:
                k = _key(ln)
                if k:
                    seen.add(k)
            for ln in _extra_lines():
                if ln.startswith("#"):
                    lines.append(ln)
                    continue
                k = _key(ln)
                if k and k not in seen:
                    seen.add(k)
                    lines.append(ln)
            text = "\n".join(lines) + "\n"
        except Exception as e:
            text = text.rstrip("\n") + "\n" + _line(
                "nvis_lake_exporter_errors_total", {"kind": type(e).__name__}, 1) + "\n"
        return text
    return render_metrics


# ---- install ---------------------------------------------------------------
def install(host_module):
    """Attach to the running lakewriter module. Idempotent; never raises."""
    global _host, _base_render
    try:
        if _host is not None:
            return
        _host = host_module
        _base_render = host_module.render_metrics
        host_module.render_metrics = _make_render(_base_render)
        try:
            import lake_common
            _patch_sink_class(lake_common)
        except Exception as e:
            print(f"WARN lake_selfmetrics: sink patch failed: {type(e).__name__}: {e}",
                  flush=True)
        handler = getattr(host_module, "Handler", None)
        if handler is not None:
            _patch_handler(handler)
        try:
            _do_scan()
        except Exception:
            pass
        threading.Thread(target=_scan_loop, daemon=True).start()
        print("lake_selfmetrics installed: zero-init tables=%s expected_device=%r"
              % (",".join(WRITER_TABLES), EXPECTED_DEVICE_RE), flush=True)
    except Exception as e:
        print(f"WARN lake_selfmetrics install failed: {type(e).__name__}: {e}",
              flush=True)
