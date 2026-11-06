#!/usr/bin/env python3
"""
runlogs_schema.py — Arrow schemas for the VALIDATION LOG lane of the IREN_MKZ
Parquet data lake: `run_logs` (one row per log LINE) and `run_log_files` (one row
per whole log FILE captured into the content-addressed raw-blob zone).

Kept in a separate module from schema.py on purpose: schema.py is edited
concurrently by the metrics/nccl_results lanes, and these two tables partition
DIFFERENTLY from schema.PARTITION_KEYS (cluster/su/rack/date/hour). Importing
this module registers both tables into schema.SCHEMAS so `schema` stays the
single lookup point at runtime without a textual merge conflict.

Column-name note: the canonical verbatim-line column is `line` (not `raw`, which
is what schema.LOGS_SCHEMA uses for the Loki/OTLP push lane). `run_logs` is the
FILE-ingest table; `logs` is the PUSH-ingest table. They are deliberately
distinct: a pushed Loki line has no source file, byte offset or blob to point at.

Provenance rule (matches nccl_results): `source` is 'live' | 'fixture' and
`fixture` is a non-nullable bool. Every synthetic row ALSO carries a run_id that
starts with 'FIXTURE-' so the partition PATH says so too and no dashboard can
mistake a demo for a cluster result.
"""
from __future__ import annotations
import pyarrow as pa

# ---------------------------------------------------------------------------
# run_logs — one row per LINE of every validation/NCCL log we capture.
# ---------------------------------------------------------------------------
RUN_LOGS_SCHEMA = pa.schema([
    ("ts", pa.timestamp("us")),      # parsed line time, else file mtime + lineno offset
    ("ts_exact", pa.bool_()),        # False == synthesized from mtime; never fake precision
    ("cluster", pa.string()),
    ("su", pa.string()),
    ("rack", pa.string()),
    ("node", pa.string()),           # node the LINE is attributed to (rank host when known)
    ("run_id", pa.string()),         # <cluster>-<harness>-<workload>-<unit>[-r<n>]-<jobkey>
    ("unit_key", pa.string()),       # stable across MAX_ATTEMPTS retries
    ("job_id", pa.string()),         # slurm jobid, or t<epoch> for the rounds script
    ("activity_id", pa.string()),    # durable Rack Status activity UUID, when available
    ("harness", pa.string()),        # llmb|rackstatus|sbatch|orchestrator|manual|unknown
    ("workload", pa.string()),       # nccl_allreduce|nccl_single|nccl_multi|nccl_rounds|dcgm|nemo…
    ("stream", pa.string()),         # sbatch_stdout|nccl_rank_debug|job_step_stdout|round_log|
                                     # summary_tsv|orchestrator|node_health|llmb_stdout|result_file
    ("rank", pa.int32()),            # global rank (path, or resolved via the "# Using devices" map)
    ("local_rank", pa.int16()),
    ("pid", pa.int32()),
    ("device", pa.int8()),
    ("host", pa.string()),           # the rank's own hostname as printed by NCCL
    ("round", pa.int16()),           # NVIS_NCCL_ROUNDS index when the line is inside a round
    ("severity", pa.string()),       # INFO|WARN|ERROR|DEBUG|TRACE|ABORT|null
    ("msg_class", pa.string()),      # see runlog_parse.MSG_CLASSES
    ("xid", pa.int16()),             # parsed GPU Xid (correctly, not the PCI BDF)
    ("src_file", pa.string()),       # absolute source path as seen by the collector
    ("src_sha256", pa.string()),     # sha256 of the whole source file -> joins run_log_files
    ("lineno", pa.int64()),          # 1-based line number inside src_file
    ("kv", pa.map_(pa.string(), pa.string())),   # transport=, nranks=, busbw=, harness k=v …
    ("line", pa.string()),           # THE VERBATIM LINE — nothing is ever dropped
    ("source", pa.string()),         # 'live' | 'fixture'  — NEVER null
    ("fixture", pa.bool_()),         # true == synthetic/demo   — NEVER null
    ("ingest_tool", pa.string()),
    ("ingest_version", pa.string()),
])

# ---------------------------------------------------------------------------
# run_log_files — manifest of the raw-blob zone. One row per captured FILE.
# The blob itself lives at LAKE_ROOT/blobs/sha256=<hex>/<filename>[.gz]; sha256
# is ALWAYS of the uncompressed bytes so the address stays content-exact and is
# verifiable after gunzip.
# ---------------------------------------------------------------------------
RUN_LOG_FILES_SCHEMA = pa.schema([
    ("ts", pa.timestamp("us")),      # capture time
    ("cluster", pa.string()),
    ("su", pa.string()),
    ("rack", pa.string()),
    ("node", pa.string()),
    ("run_id", pa.string()),
    ("unit_key", pa.string()),
    ("job_id", pa.string()),
    ("activity_id", pa.string()),
    ("harness", pa.string()),
    ("workload", pa.string()),
    ("stream", pa.string()),
    ("rank", pa.int32()),
    ("path", pa.string()),           # absolute source path on the capture host
    ("filename", pa.string()),
    ("capture_host", pa.string()),   # which machine the collector ran on
    ("media_type", pa.string()),
    ("size_bytes", pa.int64()),      # uncompressed source size
    ("sha256", pa.string()),         # content address (uncompressed)
    ("mtime", pa.timestamp("us")),
    ("blob_ref", pa.string()),       # blobs/sha256=<hex>/<filename>[.gz], null if not blobbed
    ("blob_encoding", pa.string()),  # identity|gzip
    ("blob_bytes", pa.int64()),      # bytes actually stored on the NVMe
    ("lines_total", pa.int64()),
    ("lines_ingested", pa.int64()),  # rows landed in run_logs from this pass
    ("byte_offset_start", pa.int64()),  # incremental tail start (0 == whole file)
    ("byte_offset_end", pa.int64()),
    ("loki_pushed", pa.int64()),     # entries teed to Loki from this pass
    ("parse_errors", pa.int64()),
    ("source", pa.string()),         # 'live' | 'fixture'  — NEVER null
    ("fixture", pa.bool_()),
    ("ingest_tool", pa.string()),
    ("ingest_version", pa.string()),
])

# ---------------------------------------------------------------------------
# Partition specs — per table, because these two do NOT use cluster/su/rack/
# date/hour. Landing on run_id makes a run's write atomic and idempotent (one
# run = one directory; re-ingest = rm -rf that directory, never a
# read-modify-write). `stream` is a 4th level on run_logs ONLY because
# nccl_rank_debug is ~1000x the bytes of every other stream combined, so
# "show me the sbatch stdout for this run" must be a partition prune and not a
# 1000:1 scan-and-discard. It also lets retention differ per stream with a
# plain directory delete.
# ---------------------------------------------------------------------------
LANDING_PARTITION = {
    "run_logs":      ["cluster", "date", "run_id", "stream"],
    "run_log_files": ["cluster", "date", "run_id"],
}

# Curated zone (produced by compaction, not by the collector). `hour` returns on
# run_logs because log volume is genuinely time-dense.
CURATED_PARTITION = {
    "run_logs":      ["cluster", "date", "su", "rack", "hour"],
    "run_log_files": ["cluster", "date"],
}

SORT_KEY = {
    "run_logs":      ["run_id", "stream", "src_file", "lineno"],
    "run_log_files": ["run_id", "path"],
}

SCHEMAS = {
    "run_logs": RUN_LOGS_SCHEMA,
    "run_log_files": RUN_LOG_FILES_SCHEMA,
}


def register() -> None:
    """Additively publish these tables into schema.SCHEMAS / schema.SORT_KEY.

    Runtime registration rather than a textual edit: schema.py is owned by the
    metrics + nccl_results lanes and this keeps the lanes merge-free. Never
    overwrites an existing key.
    """
    try:
        import schema as _s
    except Exception:
        return
    for name, sch in SCHEMAS.items():
        _s.SCHEMAS.setdefault(name, sch)
        _s.SORT_KEY.setdefault(name, SORT_KEY[name][0])
    if not hasattr(_s, "LANDING_PARTITION"):
        _s.LANDING_PARTITION = {}
    if not hasattr(_s, "CURATED_PARTITION"):
        _s.CURATED_PARTITION = {}
    for name in SCHEMAS:
        _s.LANDING_PARTITION.setdefault(name, LANDING_PARTITION[name])
        _s.CURATED_PARTITION.setdefault(name, CURATED_PARTITION[name])


register()
