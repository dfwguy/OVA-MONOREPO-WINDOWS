#!/usr/bin/env python3
"""
log_collector.py — nvis-lake-logs: NCCL / validation LOG ingestion for the
IREN_MKZ Parquet data lake.

WHAT IT DOES
  Walks a set of local roots, and for every log file it finds:
    1. copies the WHOLE file byte-exact into the content-addressed raw-blob zone
       ($LAKE_ROOT/blobs/sha256=<hex>/<name>[.gz]) — the durable archive,
    2. parses it line-by-line into the `run_logs` Parquet table (one row per
       line, typed: run_id / node / rank / stream / ts / line / cluster + 20
       more columns), landing at
       $LAKE_ROOT/landing/run_logs/cluster=/date=/run_id=/stream=/,
    3. records one row per file in `run_log_files` (the blob manifest),
    4. tees the OPERATOR-RELEVANT subset of lines to Loki,
    5. bookmarks (path -> sha256/offset) so a re-scan is a no-op and a growing
       Slurm stdout is tailed incrementally.

WHERE THE LOGS COME FROM (from the suite source, not guessed)
  A. rack-status direct-mpirun path — the one actually used on IREN_MKZ.
     `{RACK_REMOTE_BASE_PATH}/var/logs/` = /home/cmsupport/nvis-rack-status/var/logs/
       <user>-NCCL-1Rack-<rack>-<N>N-<jobid>.txt     (nccl_allreduce.sbatch stdout)
       <user>-NEMO-1Rack-<rack>-<N>N-<jobid>.txt
       nccl-mpi_<label>_<jobid>.out                  (cross-rack)
       llmb-nccl_<rack>_<jobid>.out
     stderr is MERGED into stdout everywhere in this stack (neither
     actions/launch_job.sh nor run_nccl_mpi.sh passes -e/--error), so there is
     no separate stderr artifact to collect — one file per job.
  B. Stage-1 acceptance rounds: $NCCL/rounds_<UTCSTAMP>/round_<r>.log + summary.tsv
  C. llmb-run: $LLMB_INSTALL/workloads/*/experiments/<exp>_<jobid>/LOG_*/
       .../job_step_stdout.txt              (the nccl-tests sweep table)
       .../iter1/rank<N>/nccl_debug_file.<host>.<pid>.txt   (per-rank NCCL_DEBUG)
     and $RESULTS_DIR/<node>/<workload>[-run<N>].txt (sbatch stdout IS the result file)
  D. orchestrator audit trail: $LOG_DIR/aat.log
  Those paths live on the HEAD NODE. This collector reads LOCAL paths only — it
  never SSHes anywhere. Point RUNLOG_ROOTS at wherever they are mounted/rsynced
  and it works the moment they exist; until then it reports 0 files and says so.

LOKI vs PARQUET — why BOTH, and what goes where
  LOKI = searchable RECENT. Grafana Explore, live tailing, `|= "ibv_modify_qp"`
  across a bring-up shift, alert rules. Measured constraints of THIS Loki
  (platform/loki/loki-config.yaml, verified live):
      retention_period: 744h (31d)
      reject_old_samples: true, reject_old_samples_max_age: 744h
      max_line_size: 512KB
  So Loki structurally CANNOT be the archive: it deletes at 31 days and it
  REJECTS any entry older than 31 days, which means a validation log can never
  be backfilled into it after the fact. A handover pack assembled 3 months after
  bring-up would find nothing.

  PARQUET = durable RAW archive + analytics. Every line, event-time indexed,
  arbitrary backfill (a partition directory is just a date), plus the byte-exact
  original file in the blob zone so a disputed result can be re-parsed from
  source years later. `validation_runs` is already exempt from lake retention
  for exactly this reason ("keep forever (handover provenance)").

  The split is therefore NOT redundancy, it is two different contracts:
    - to Loki we send WARN/ERROR + results/summaries/harness lines, and all
      non-rank-debug streams. At NCCL_DEBUG=INFO a single 72-rank rack run emits
      100s of MB across 72 files; shipping that verbatim would burn the 31-day
      retention budget in one campaign and bury the signal.
    - to Parquet we send EVERYTHING, always, plus the file itself.
  A line that goes to Loki ALSO goes to Parquet. Nothing is Loki-only.

IDEMPOTENCE
  Content-addressed blobs + a per-path bookmark. Re-running over the same tree
  writes nothing. A re-ingest of one run is `rm -rf` its landing run_id
  directory; the hourly compactor's row-count-verified merge collapses the rest.

Env:
  RUNLOG_ROOTS(:-separated)  RUNLOG_EXTRA_ROOTS  RUNLOG_GLOBS
  LAKE_ROOT  CLUSTER_NAME  METRICS_PORT(9413)  SCAN_INTERVAL_S(120)
  RUNLOG_CHECKPOINT_S(300)
  LOKI_URL  LOKI_ENABLE(1)  RUNLOG_SETTLE_S(300)  RUNLOG_MAX_FILE_BYTES
  RUNLOG_FIXTURE_ROOTS   MIN_FREE_BYTES
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import runlogs_schema as rls  # noqa: F401  (registers run_logs into schema.SCHEMAS)
import runlog_ingest as ri
from lake_common import IDENTITY
from runlog_parse import (ActivityResolver, INGEST_TOOL, INGEST_VERSION,
                          LineParser, identify, loki_worthy)

CLUSTER = os.environ.get("CLUSTER_NAME", "IREN_MKZ")
LAKE_ROOT = ri.LAKE_ROOT
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9413"))
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL_S", "120"))
CHECKPOINT_S = int(os.environ.get("RUNLOG_CHECKPOINT_S", "300"))
SETTLE_S = int(os.environ.get("RUNLOG_SETTLE_S", "300"))
MAX_FILE_BYTES = int(os.environ.get("RUNLOG_MAX_FILE_BYTES", str(4 * 1024 ** 3)))
MIN_FREE = int(os.environ.get("MIN_FREE_BYTES", str(50 * 1024 ** 3)))
ACTIVITY_STORE = os.environ.get("RUNLOG_ACTIVITY_STORE", "")
IDENTITY_SCHEMA_VERSION = 5
NCCL_ACTIVITY_IDENTITY_SCHEMA_VERSION = 3
LOKI_URL = os.environ.get("LOKI_URL", "http://127.0.0.1:3100/loki/api/v1/push")
LOKI_ENABLE = os.environ.get("LOKI_ENABLE", "1") not in ("0", "false", "no")
LOKI_MAX_AGE_S = int(os.environ.get("LOKI_MAX_AGE_S", str(744 * 3600)))  # matches loki cfg
# Loki's creation_grace_period (default 10m) rejects entries dated ahead of now;
# stay well inside it so head-node clock skew never 400s a whole batch.
LOKI_FUTURE_GRACE_S = int(os.environ.get("LOKI_FUTURE_GRACE_S", "300"))
LOKI_MAX_LINE = int(os.environ.get("LOKI_MAX_LINE", str(480 * 1024)))    # < max_line_size 512KB
LOKI_BATCH = int(os.environ.get("LOKI_BATCH", "2000"))

DEFAULT_ROOTS = [
    # A. rack-status head-node log dir (the deployed path) and the repo-local one
    "/home/cmsupport/nvis-rack-status/var/logs",
    "/opt/observability/nvis-rack-status-v3/var/logs",
    # B/C. llmb-bringup orchestrator + node-health + results
    "/opt/llmb-bringup/log",
    "/opt/llmb-bringup/logs",
    "/opt/llmb-bringup/results",
    "/opt/llmb-bringup/state",
    # C. llmb-run install tree (experiments + per-rank NCCL debug)
    "/opt/llmb/workloads",
    # local mirror of the suite, if rsynced here
    "/opt/observability/.ftp/x/llmb/IREN_MKZ8k_llmbrun/results",
]
GLOBS = tuple((os.environ.get("RUNLOG_GLOBS") or
               ".txt,.out,.log,.tsv,.err,.raw").split(","))

_M = {
    "scans": 0, "files_seen": 0, "files_ingested": 0, "files_skipped": 0,
    "rows": 0, "blobs": 0, "blob_bytes": 0, "loki_pushed": 0,
    "loki_errors": 0, "errors": 0, "last_scan_ts": 0.0, "last_scan_s": 0.0,
    "roots_present": 0, "roots_missing": 0, "fixture_rows": 0,
    "bytes_read": 0, "loki_skipped_old": 0, "loki_skipped_new": 0,
    "loki_rejected": 0, "fixture_by_marker": 0,
}
_MLOCK = threading.Lock()


def _bump(k, n=1):
    with _MLOCK:
        _M[k] = _M.get(k, 0) + n


def roots() -> list[tuple[str, bool]]:
    """[(path, is_fixture)] — fixture roots are flagged so every row they
    produce is written with source='fixture', fixture=true and a run_id that
    starts with 'FIXTURE-'."""
    env = os.environ.get("RUNLOG_ROOTS")
    base = [r for r in (env.split(":") if env else DEFAULT_ROOTS) if r]
    extra = [r for r in (os.environ.get("RUNLOG_EXTRA_ROOTS") or "").split(":") if r]
    fx = [r for r in (os.environ.get("RUNLOG_FIXTURE_ROOTS") or "").split(":") if r]
    return [(r, False) for r in base + extra] + [(r, True) for r in fx]


def walk(root: str):
    # A scan can spend hours archiving historical multi-GB NCCL debug logs.
    # Discover the tree first, visit compact acceptance evidence before bulky
    # raw/debug artifacts, and order each class newest-first.  This keeps a
    # newly settled rack result from waiting behind a multi-GB active `.raw`
    # file while still preserving every raw artifact later in the same scan.
    def priority(path: str) -> int:
        name = os.path.basename(path)
        if (
            re.fullmatch(r"nvftp-nccl-five-collective-[0-9]+\.out", name)
            or re.fullmatch(r"nemo-.+-[0-9]+\.out", name)
            or re.fullmatch(r"mnubergemm-.+-[0-9]+\.out", name)
            or name.startswith("rack-status-")
        ):
            return 0
        if name == "summary.tsv":
            return 1
        if name.endswith((".out", ".txt", ".tsv")):
            return 2
        if name.endswith((".err", ".log")):
            return 3
        return 4

    files = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
        for fn in sorted(filenames):
            if fn.endswith(tuple(GLOBS)):
                path = os.path.join(dirpath, fn)
                try:
                    mtime_ns = os.stat(path, follow_symlinks=False).st_mtime_ns
                except OSError:
                    continue
                files.append((priority(path), mtime_ns, path))
    files.sort(key=lambda item: (item[0], -item[1], item[2]))
    for _, _, path in files:
        yield path


# ---------------------------------------------------------------------------
# Loki tee
# ---------------------------------------------------------------------------
def push_loki(entries: list[tuple[dict, int, str, dict]], _depth: int = 0) -> int:
    """entries: [(labels, ts_ns, line, structured_metadata)]. Returns count sent.

    run_id / rank / lineno go in STRUCTURED METADATA, not labels: this Loki is
    schema v13 with allow_structured_metadata: true (verified in
    platform/loki/loki-config.yaml), and run_id as a label would mint a new
    stream per run and blow up the index. Verified live: /loki/api/v1/labels
    lists only cluster/fixture/harness/rack/source/stream/su/workload — run_id
    and lineno never became index labels.

    Loki rejects a WHOLE push with HTTP 400 if a SINGLE entry is out of its
    accepted time window ("timestamp too new" / "too old"). One clock-skewed
    line on one head node would therefore silently cost an entire batch. Two
    defences: entries outside the window are dropped from the Loki lane BEFORE
    the push (they are already safe in Parquet), and any surviving 400 is
    bisected so one poison entry costs log2(n) requests instead of the batch.
    """
    if not LOKI_ENABLE or not entries:
        return 0
    streams: dict[str, dict] = {}
    for labels, ts_ns, line, meta in entries:
        key = json.dumps(labels, sort_keys=True)
        st = streams.setdefault(key, {"stream": labels, "values": []})
        v = [str(ts_ns), line[:LOKI_MAX_LINE]]
        if meta:
            v.append({k: str(x) for k, x in meta.items() if x is not None})
        st["values"].append(v)
    body = json.dumps({"streams": list(streams.values())}).encode()
    req = urllib.request.Request(
        LOKI_URL, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        _bump("loki_pushed", len(entries))
        return len(entries)
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode(errors="replace")
        # Loki rejects every entry in an old batch when its ordering window has
        # advanced past the batch timestamp.  Bisecting that response only
        # repeats the same deterministic rejection for each individual line and
        # can stall a run-log scan for hours.  The authoritative Parquet/raw
        # lanes are already written, so account for and drop the whole batch
        # from the ancillary Loki lane.
        if e.code == 400 and "entry too far behind" in detail.lower():
            print(f"loki push HTTP 400 ({len(entries)} entries too far behind; "
                  f"dropped from the Loki lane; still in Parquet): {detail}",
                  flush=True)
            _bump("loki_errors")
            _bump("loki_rejected", len(entries))
            return 0
        if e.code == 400 and len(entries) > 1 and _depth < 12:
            mid = len(entries) // 2
            return (push_loki(entries[:mid], _depth + 1) +
                    push_loki(entries[mid:], _depth + 1))
        print(f"loki push HTTP {e.code} ({len(entries)} entr{'y' if len(entries)==1 else 'ies'} "
              f"dropped from the Loki lane; still in Parquet): {detail}", flush=True)
        _bump("loki_errors")
        _bump("loki_rejected", len(entries))
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"loki push error: {e}", flush=True)
        _bump("loki_errors")
        _bump("loki_rejected", len(entries))
        return 0


# ---------------------------------------------------------------------------
# per-file ingest
# ---------------------------------------------------------------------------
LOG_W = None
FILE_W = None


FIXTURE_MARKERS = tuple(
    m for m in (os.environ.get("RUNLOG_FIXTURE_MARKERS")
                or "SYNTHETIC FIXTURE,NOT A REAL,FABRICATED").split(",") if m)
FIXTURE_MARKER_SCAN_BYTES = int(
    os.environ.get("RUNLOG_FIXTURE_MARKER_BYTES", "512"))


def _has_fixture_marker(path: str) -> bool:
    """True if the file's own header declares it synthetic."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(FIXTURE_MARKER_SCAN_BYTES).decode(
                "utf-8", errors="replace").upper()
    except OSError:
        return False
    return any(m.upper() in head for m in FIXTURE_MARKERS)


def _source_location(ident) -> tuple[str, str]:
    """Resolve Parquet SU/rack, preserving identity encoded in a log path."""
    su, rack = IDENTITY.lookup(ident.node or "")
    if rack == "UNKNOWN" and ident.unit_kind == "rack" and ident.unit_id:
        rack = ident.unit_id
    if su == "UNKNOWN" and ident.su:
        su = ident.su
    return su, rack


def _blob_only(path, st, ident, prev, state, fixture) -> dict:
    """Archive a file that has gone quiet but whose lines are already ingested.
    Emits a run_log_files row (lines_ingested=0) so the manifest stays an
    append-only log of CAPTURE events, not just of parse events."""
    global FILE_W
    su, rack = _source_location(ident)
    sha, size = ri.sha256_file(path)
    blob_ref, blob_enc, blob_bytes = ri.store_blob(path, sha, size)
    _bump("blobs")
    _bump("blob_bytes", blob_bytes)
    if FILE_W is None:
        FILE_W = ri.PartitionedWriter("run_log_files")
    FILE_W.write([{
        "ts": int(time.time() * 1e6), "cluster": CLUSTER, "su": su, "rack": rack,
        "node": ident.node or "", "run_id": ident.run_id,
        "unit_key": ident.unit_key, "job_id": ident.job_id,
        "activity_id": ident.activity_id,
        "harness": ident.harness, "workload": ident.workload,
        "stream": ident.stream, "rank": ident.rank,
        "path": os.path.abspath(path), "filename": os.path.basename(path),
        "capture_host": ri.CAPTURE_HOST, "media_type": "text/plain",
        "size_bytes": size, "sha256": sha, "mtime": int(st.st_mtime * 1e6),
        "blob_ref": blob_ref, "blob_encoding": blob_enc,
        "blob_bytes": blob_bytes, "lines_total": int(prev.get("lines", 0)),
        "lines_ingested": 0, "byte_offset_start": st.st_size,
        "byte_offset_end": st.st_size, "loki_pushed": 0, "parse_errors": 0,
        "source": "fixture" if fixture else "live", "fixture": fixture,
        "ingest_tool": INGEST_TOOL, "ingest_version": INGEST_VERSION,
    }])
    rec = dict(prev)
    rec.update({"blob_sha": sha, "blob_ref": blob_ref, "blob_enc": blob_enc,
                "blob_bytes": blob_bytes})
    state.put(path, rec)
    return {"path": path, "run_id": ident.run_id, "stream": ident.stream,
            "rows": 0, "sha256": sha, "blob_ref": blob_ref, "loki": 0,
            "su": su, "rack": rack, "harness": ident.harness,
            "workload": ident.workload, "parse_errors": 0}


def _identity_link_only(path, st, ident, prev, state, fixture) -> None:
    """Append a manifest-only activity link without replaying line rows."""
    global FILE_W
    su, rack = _source_location(ident)
    if FILE_W is None:
        FILE_W = ri.PartitionedWriter("run_log_files")
    FILE_W.write([{
        "ts": int(time.time() * 1e6), "cluster": CLUSTER, "su": su,
        "rack": rack, "node": ident.node or "", "run_id": ident.run_id,
        "unit_key": ident.unit_key, "job_id": ident.job_id,
        "activity_id": ident.activity_id, "harness": ident.harness,
        "workload": ident.workload, "stream": ident.stream,
        "rank": ident.rank, "path": os.path.abspath(path),
        "filename": os.path.basename(path), "capture_host": ri.CAPTURE_HOST,
        "media_type": "text/plain", "size_bytes": st.st_size,
        "sha256": prev.get("sha256"), "mtime": int(st.st_mtime * 1e6),
        "blob_ref": prev.get("blob_ref"), "blob_encoding": prev.get("blob_enc"),
        "blob_bytes": int(prev.get("blob_bytes", 0)),
        "lines_total": int(prev.get("lines", 0)), "lines_ingested": 0,
        "byte_offset_start": int(prev.get("offset", 0)),
        "byte_offset_end": int(prev.get("offset", 0)), "loki_pushed": 0,
        "parse_errors": 0, "source": "fixture" if fixture else "live",
        "fixture": fixture, "ingest_tool": INGEST_TOOL,
        "ingest_version": INGEST_VERSION,
    }])
    rec = dict(prev)
    rec.update({
        "activity_id": ident.activity_id,
        "run_id": ident.run_id,
        "identity_schema_version": IDENTITY_SCHEMA_VERSION,
    })
    state.put(path, rec)


def ingest_file(path: str, state: ri.CollectorState, fixture: bool,
                dry_run: bool = False,
                activity_resolver: ActivityResolver | None = None) -> dict | None:
    """Ingest one log file. Returns a summary dict, or None when skipped."""
    global LOG_W, FILE_W
    try:
        st = os.stat(path)
    except OSError:
        return None
    if st.st_size == 0:
        return None
    if st.st_size > MAX_FILE_BYTES:
        _bump("files_skipped")
        print(f"skip (too large {st.st_size}B > {MAX_FILE_BYTES}): {path}", flush=True)
        return None

    prev = state.get(path)
    offset = int(prev.get("offset", 0))
    # Rotation check: re-hash EXACTLY the prefix length we hashed last time.
    # Comparing a fixed-size window would flag every append on a file shorter
    # than the window as a replacement and re-ingest it whole (duplicate rows).
    prev_fp, prev_fp_len = prev.get("fp"), int(prev.get("fp_len", 0))
    rotated = False
    if prev_fp and prev_fp_len:
        if st.st_size < prev_fp_len:
            rotated = True                                   # truncated
        else:
            now_fp, _ = ri.fingerprint(path, prev_fp_len)
            rotated = now_fp != prev_fp                      # replaced
    if st.st_size < offset:
        rotated = True
    if prev.get("inode") and prev["inode"] != st.st_ino:
        rotated = True
    if rotated:
        offset = 0
        prev = dict(prev)
        prev["lines"] = 0            # line numbers restart with the new file
    # Defence in depth against "no fabricated data": a file whose own header
    # declares it synthetic is ALWAYS ingested as a fixture, even when it is
    # sitting in a production root. Root membership is a deployment detail and
    # can be got wrong; the file's own banner cannot. Without this, dropping a
    # demo log into {RACK_REMOTE_BASE_PATH}/var/logs would mint rows labelled
    # source='live' that a dashboard would present as a cluster result.
    if not fixture and _has_fixture_marker(path):
        fixture = True
        _bump("fixture_by_marker")

    ident = identify(path, cluster=CLUSTER, fixture=fixture, mtime=st.st_mtime)
    if activity_resolver is not None:
        ident.activity_id = activity_resolver.resolve(ident, path, st.st_mtime)
    if (ident.workload == "nccl_five_collective" and ident.activity_id and
            int(prev.get("identity_schema_version", 0)) <
            NCCL_ACTIVITY_IDENTITY_SCHEMA_VERSION):
        # One-time migration for files first landed before job/activity identity
        # was part of the schema.  The operator quarantines the two affected
        # derived partitions before deployment; raw sources/blobs stay intact.
        offset = 0
        prev = dict(prev)
        prev["lines"] = 0
    if st.st_size == offset and prev.get("mtime_ns") == st.st_mtime_ns:
        # No new LINES. But a file whose lines were ingested while it was still
        # being written has not been blobbed yet (blobbing waits for quiescence
        # so a 450 MB rank log is copied once, not on every scan). Without this
        # branch it would NEVER be blobbed and the raw archive would silently
        # hold only the files that happened to arrive already-quiet.
        settled_now = (time.time() - st.st_mtime) >= SETTLE_S
        # blob_sha != the sha recorded by the last parse pass => the archive
        # copy is missing or stale for the file's current content.
        needs_blob = prev.get("blob_sha") != prev.get("sha256")
        activity_changed = bool(
            ident.activity_id and ident.activity_id != prev.get("activity_id"))
        identity_changed = bool(
            int(prev.get("identity_schema_version", 0)) <
            IDENTITY_SCHEMA_VERSION and
            ident.run_id != prev.get("run_id"))
        if (activity_changed or identity_changed) and not dry_run:
            # The scheduler reference can appear in Rack Status only after its
            # wrapper exits, and a parser update can discover a more specific
            # identity for an already-settled source. Persist either late link
            # in the file manifest without replaying already-landed lines and
            # creating duplicate log rows.
            _identity_link_only(path, st, ident, prev, state, fixture)
            prev = state.get(path)
        if not (settled_now and needs_blob) or dry_run:
            return None
        return _blob_only(path, st, ident, prev, state, fixture)
    su, rack = _source_location(ident)
    settled = (time.time() - st.st_mtime) >= SETTLE_S

    # ---- read the new tail ------------------------------------------------
    parser = LineParser(identity=ident)
    fallback_ts_us = int(st.st_mtime * 1_000_000)
    parsed: list[tuple[int, str, dict]] = []
    lineno = int(prev.get("lines", 0))
    parse_errors = 0
    with open(path, "rb") as fh:
        fh.seek(offset)
        raw = fh.read()
        end_offset = offset + len(raw)
    text = raw.decode("utf-8", errors="replace")
    # A trailing partial line (job still writing) is left for the next pass.
    lines = text.split("\n")
    tail_partial = ""
    if lines and not text.endswith("\n"):
        tail_partial = lines.pop()
    if lines and lines[-1] == "":
        lines.pop()
    for ln in lines:
        lineno += 1
        try:
            parsed.append((lineno, ln, parser.parse(ln, lineno)))
        except Exception as e:  # noqa: BLE001 — never let one bad line stop a file
            parse_errors += 1
            parsed.append((lineno, ln, {
                "ts_us": None, "ts_exact": False, "severity": "ERROR",
                "msg_class": None, "rank": None, "local_rank": None,
                "pid": None, "device": None, "host": None, "round": None,
                "xid": None, "kv": {"parse_error": type(e).__name__}}))
    end_offset -= len(tail_partial.encode("utf-8", errors="replace"))

    # ---- blob the whole file once it has settled --------------------------
    blob_ref = blob_enc = None
    blob_bytes = 0
    sha, size = ri.sha256_file(path)
    if settled and prev.get("blob_sha") != sha and not dry_run:
        blob_ref, blob_enc, blob_bytes = ri.store_blob(path, sha, size)
        _bump("blobs")
        _bump("blob_bytes", blob_bytes)
    elif prev.get("blob_sha") == sha:
        blob_ref, blob_enc = prev.get("blob_ref"), prev.get("blob_enc")
        blob_bytes = int(prev.get("blob_bytes", 0))

    rows = ri.build_log_rows(parsed, ident, su, rack, os.path.abspath(path),
                             sha, fallback_ts_us, fixture)

    # ---- Loki tee (recent + searchable subset) ----------------------------
    now_ns = time.time_ns()
    cutoff_ns = now_ns - LOKI_MAX_AGE_S * 1_000_000_000
    future_ns = now_ns + LOKI_FUTURE_GRACE_S * 1_000_000_000
    sent = 0
    if LOKI_ENABLE and not dry_run:
        batch = []
        for r, (_, _, p) in zip(rows, parsed):
            if not loki_worthy(ident.stream, p):
                continue
            ts_ns = int(r["ts"]) * 1000
            if ts_ns < cutoff_ns:
                _bump("loki_skipped_old")
                continue          # Loki rejects >31d old; Parquet still has it
            if ts_ns > future_ns:
                # Clock skew on a head node, or a log timestamped ahead of the
                # collector. Loki 400s the WHOLE push for one such entry.
                _bump("loki_skipped_new")
                continue
            labels = {"cluster": CLUSTER, "source": "validation",
                      "stream": ident.stream, "harness": ident.harness,
                      "workload": ident.workload, "rack": rack,
                      "su": su, "fixture": "true" if fixture else "false"}
            meta = {"run_id": r["run_id"], "job_id": r["job_id"] or "",
                    "node": r["node"] or "", "lineno": r["lineno"],
                    "src_sha256": sha[:16]}
            if r["rank"] is not None:
                meta["rank"] = r["rank"]
            if r["msg_class"]:
                meta["msg_class"] = r["msg_class"]
            batch.append((labels, ts_ns, r["line"], meta))
            if len(batch) >= LOKI_BATCH:
                sent += push_loki(batch)
                batch = []
        sent += push_loki(batch)

    # ---- Parquet -----------------------------------------------------------
    if not dry_run:
        if LOG_W is None:
            LOG_W = ri.PartitionedWriter("run_logs")
            FILE_W = ri.PartitionedWriter("run_log_files")
        LOG_W.write(rows)
        FILE_W.write([{
            "ts": int(time.time() * 1e6), "cluster": CLUSTER, "su": su,
            "rack": rack, "node": ident.node or "", "run_id": ident.run_id,
            "unit_key": ident.unit_key, "job_id": ident.job_id,
            "activity_id": ident.activity_id,
            "harness": ident.harness, "workload": ident.workload,
            "stream": ident.stream, "rank": ident.rank,
            "path": os.path.abspath(path), "filename": os.path.basename(path),
            "capture_host": ri.CAPTURE_HOST,
            "media_type": "text/plain", "size_bytes": size, "sha256": sha,
            "mtime": int(st.st_mtime * 1e6), "blob_ref": blob_ref,
            "blob_encoding": blob_enc, "blob_bytes": blob_bytes,
            "lines_total": lineno, "lines_ingested": len(rows),
            "byte_offset_start": offset, "byte_offset_end": end_offset,
            "loki_pushed": sent, "parse_errors": parse_errors,
            "source": "fixture" if fixture else "live", "fixture": fixture,
            "ingest_tool": INGEST_TOOL, "ingest_version": INGEST_VERSION,
        }])
        new_fp, new_fp_len = ri.fingerprint(path)
        state.put(path, {
            "inode": st.st_ino, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
            "fp": new_fp, "fp_len": new_fp_len,
            "offset": end_offset, "lines": lineno, "sha256": sha,
            "blob_sha": sha if blob_ref else prev.get("blob_sha"),
            "blob_ref": blob_ref, "blob_enc": blob_enc,
            "blob_bytes": blob_bytes, "run_id": ident.run_id,
            "activity_id": ident.activity_id,
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
        })

    _bump("files_ingested")
    _bump("rows", len(rows))
    _bump("bytes_read", len(raw))
    if fixture:
        _bump("fixture_rows", len(rows))
    return {"path": path, "run_id": ident.run_id, "stream": ident.stream,
            "rows": len(rows), "sha256": sha, "blob_ref": blob_ref,
            "loki": sent, "su": su, "rack": rack, "harness": ident.harness,
            "workload": ident.workload, "parse_errors": parse_errors}


def scan_once(dry_run: bool = False) -> list[dict]:
    t0 = time.time()
    state = ri.CollectorState()
    results = []
    activity_resolver = ActivityResolver.from_file(ACTIVITY_STORE)
    next_checkpoint = time.monotonic() + CHECKPOINT_S
    present = missing = 0
    free = shutil.disk_usage(LAKE_ROOT).free if LAKE_ROOT.exists() else 0
    if free < MIN_FREE:
        # SKIP, never drop: the file stays on disk and is picked up next scan.
        print(f"WARN lake free {free} < MIN_FREE {MIN_FREE}; skipping scan "
              f"(no data lost — sources are still on disk)", flush=True)
        _bump("errors")
        return results
    for root, fixture in roots():
        if not os.path.isdir(root):
            missing += 1
            continue
        present += 1
        for p in walk(root):
            _bump("files_seen")
            try:
                r = ingest_file(p, state, fixture, dry_run=dry_run,
                                activity_resolver=activity_resolver)
            except Exception as e:  # noqa: BLE001
                _bump("errors")
                print(f"ingest error {p}: {type(e).__name__}: {e}", flush=True)
                continue
            if r:
                results.append(r)
            if (not dry_run and CHECKPOINT_S > 0 and
                    time.monotonic() >= next_checkpoint):
                state.save()
                next_checkpoint = time.monotonic() + CHECKPOINT_S
    if not dry_run:
        state.save()
    with _MLOCK:
        _M["scans"] += 1
        _M["last_scan_ts"] = time.time()
        _M["last_scan_s"] = time.time() - t0
        _M["roots_present"] = present
        _M["roots_missing"] = missing
    return results


# ---------------------------------------------------------------------------
# self-observability — "blank never means healthy"
# ---------------------------------------------------------------------------
def render_metrics() -> str:
    with _MLOCK:
        m = dict(_M)
    free = shutil.disk_usage(LAKE_ROOT).free if LAKE_ROOT.exists() else -1
    out = [
        "# nvis-lake-logs (validation log -> run_logs Parquet + raw-blob zone)",
        "# HELP nvis_runlog_up collector liveness",
        "# TYPE nvis_runlog_up gauge",
        "nvis_runlog_up 1",
        f'nvis_runlog_build_info{{tool="{INGEST_TOOL}",version="{INGEST_VERSION}"}} 1',
        "# TYPE nvis_runlog_scans_total counter",
        f"nvis_runlog_scans_total {m['scans']}",
        "# TYPE nvis_runlog_files_seen_total counter",
        f"nvis_runlog_files_seen_total {m['files_seen']}",
        "# TYPE nvis_runlog_files_ingested_total counter",
        f"nvis_runlog_files_ingested_total {m['files_ingested']}",
        "# TYPE nvis_runlog_files_skipped_total counter",
        f"nvis_runlog_files_skipped_total {m['files_skipped']}",
        "# TYPE nvis_runlog_rows_total counter",
        f"nvis_runlog_rows_total {m['rows']}",
        "# TYPE nvis_runlog_fixture_rows_total counter",
        f"nvis_runlog_fixture_rows_total {m['fixture_rows']}",
        "# HELP nvis_runlog_fixture_by_marker_total files forced to fixture=true "
        "by their own SYNTHETIC-FIXTURE banner despite sitting in a production "
        "root. Non-zero means a demo log is in a live log directory.",
        "# TYPE nvis_runlog_fixture_by_marker_total counter",
        f"nvis_runlog_fixture_by_marker_total {m['fixture_by_marker']}",
        "# TYPE nvis_runlog_blobs_total counter",
        f"nvis_runlog_blobs_total {m['blobs']}",
        "# TYPE nvis_runlog_blob_bytes_total counter",
        f"nvis_runlog_blob_bytes_total {m['blob_bytes']}",
        "# TYPE nvis_runlog_bytes_read_total counter",
        f"nvis_runlog_bytes_read_total {m['bytes_read']}",
        "# TYPE nvis_runlog_loki_pushed_total counter",
        f"nvis_runlog_loki_pushed_total {m['loki_pushed']}",
        "# TYPE nvis_runlog_loki_errors_total counter",
        f"nvis_runlog_loki_errors_total {m['loki_errors']}",
        "# HELP nvis_runlog_loki_skipped_total lines withheld from the Loki lane "
        "because Loki would reject them (>31d old, or dated ahead of now). They "
        "ARE in Parquet — this is a Loki-window gap, never data loss.",
        "# TYPE nvis_runlog_loki_skipped_total counter",
        f'nvis_runlog_loki_skipped_total{{reason="too_old"}} {m["loki_skipped_old"]}',
        f'nvis_runlog_loki_skipped_total{{reason="too_new"}} {m["loki_skipped_new"]}',
        f'nvis_runlog_loki_skipped_total{{reason="rejected"}} {m["loki_rejected"]}',
        "# TYPE nvis_runlog_errors_total counter",
        f"nvis_runlog_errors_total {m['errors']}",
        "# HELP nvis_runlog_roots roots configured vs actually present. "
        "roots_present==0 means the head-node log dirs are NOT mounted here — "
        "an empty run_logs table is EXPECTED, not healthy.",
        "# TYPE nvis_runlog_roots gauge",
        f'nvis_runlog_roots{{state="present"}} {m["roots_present"]}',
        f'nvis_runlog_roots{{state="missing"}} {m["roots_missing"]}',
        "# TYPE nvis_runlog_last_scan_timestamp_seconds gauge",
        f"nvis_runlog_last_scan_timestamp_seconds {m['last_scan_ts']:.0f}",
        "# TYPE nvis_runlog_last_scan_duration_seconds gauge",
        f"nvis_runlog_last_scan_duration_seconds {m['last_scan_s']:.3f}",
        "# TYPE nvis_runlog_lake_free_bytes gauge",
        f"nvis_runlog_lake_free_bytes {free}",
        "# HELP nvis_runlog_fs_device st_dev of the landing dir; equal to the "
        "rootfs device means the /data NVMe bind is stale.",
        "# TYPE nvis_runlog_fs_device gauge",
        f'nvis_runlog_fs_device{{path="landing"}} '
        f'{os.stat(ri.LANDING).st_dev if ri.LANDING.exists() else 0}',
        f'nvis_runlog_fs_device{{path="blobs"}} '
        f'{os.stat(ri.BLOBS).st_dev if ri.BLOBS.exists() else 0}',
        f'nvis_runlog_fs_device{{path="rootfs"}} {os.stat("/").st_dev}',
        "",
    ]
    return "\n".join(out)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/plain; version=0.0.4"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, b"ok")
        if self.path == "/metrics":
            return self._send(200, render_metrics().encode())
        return self._send(404, b"not found")


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("scan", "once", "dry-run"):
        for d in (ri.LANDING, ri.BLOBS, ri.STATE_DIR):
            d.mkdir(parents=True, exist_ok=True)
        res = scan_once(dry_run=(argv[0] == "dry-run"))
        print(json.dumps({"files": res, "metrics": _M}, indent=2, default=str))
        return
    for d in (ri.LANDING, ri.BLOBS, ri.STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    print(f"nvis-lake-logs {INGEST_VERSION} lake={LAKE_ROOT} "
          f"landing_dev={os.stat(ri.LANDING).st_dev} rootfs_dev={os.stat('/').st_dev} "
          f"metrics=:{METRICS_PORT} loki={'on' if LOKI_ENABLE else 'off'}", flush=True)
    if os.stat(ri.LANDING).st_dev == os.stat("/").st_dev:
        print("WARN landing is on the ROOT filesystem — the /data bind mount is "
              "stale or missing; recreate this container", flush=True)
    srv = ThreadingHTTPServer(("0.0.0.0", METRICS_PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    while True:
        try:
            res = scan_once()
            if res:
                print(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} "
                      f"ingested {len(res)} file(s), "
                      f"{sum(r['rows'] for r in res)} rows", flush=True)
        except Exception as e:  # noqa: BLE001
            _bump("errors")
            print(f"scan error: {type(e).__name__}: {e}", flush=True)
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
