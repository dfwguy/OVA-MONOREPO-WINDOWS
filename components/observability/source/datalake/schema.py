#!/usr/bin/env python3
"""
schema.py — single source of truth for the IREN_MKZ Parquet data-lake tables.

All tables are Hive-partitioned on the path by `cluster / su / rack / date / hour`
(the brief's `cluster/SU/rack/node/date` spec; `node` is folded into a SORTED
column in the curated zone — see design/datalake_parquet.md §3 — and `hour`
bounds scan/retention ranges). Every table also carries the partition keys as
columns so schema-on-read tools recover them whether they read the landing files
directly or via hive partition discovery.

Conventions:
  - times are UTC `timestamp[us]` (event-time),
  - string columns are dictionary-encoded at write time,
  - anything not promoted to a typed column is preserved in a `labels`/`kv`
    map<string,string> so NOTHING is ever dropped ("blank never means healthy"),
  - schema evolution is ADDITIVE + nullable only; never rename/retype in place.

Importing this module keeps lakewriter.py / lake_fabric_poller.py / lake_compact.py
from drifting apart.
"""
from __future__ import annotations
import pyarrow as pa

# Partition keys, in path order. `node`/`switch` are sorted columns, not dirs.
PARTITION_KEYS = ["cluster", "su", "rack", "date", "hour"]

# 2.1 metrics — long/narrow: DCGM, node, cgroup, low-card fabric summaries.
METRICS_SCHEMA = pa.schema([
    ("ts", pa.timestamp("us")),
    ("metric", pa.string()),
    ("value", pa.float64()),
    ("cluster", pa.string()),
    ("su", pa.string()),
    ("rack", pa.string()),
    ("node", pa.string()),            # sorted column in curated zone
    ("gpu", pa.int16()),              # nullable GPU/instance index
    ("job", pa.string()),
    ("instance", pa.string()),
    ("labels", pa.map_(pa.string(), pa.string())),
])

# 2.2 logs — dmesg/kernel/journald/NCCL/Slurm/LLMB (+ OTLP logs).
LOGS_SCHEMA = pa.schema([
    ("ts", pa.timestamp("us")),
    ("cluster", pa.string()),
    ("su", pa.string()),
    ("rack", pa.string()),
    ("node", pa.string()),
    ("source", pa.string()),          # dmesg|kernel|journal|nccl|slurm|llmb|varlog|otel
    ("unit", pa.string()),
    ("severity", pa.string()),
    ("xid", pa.int16()),              # parsed GPU Xid
    ("job", pa.string()),
    ("msg_class", pa.string()),       # PCIE_AER|GPU_XID|THERMAL|NCCL_RESULT|MNNVL|…
    ("kv", pa.map_(pa.string(), pa.string())),
    ("raw", pa.string()),
])

# 2.3 fabric_phy — wide numeric per-port PHY (ufm-telemetry CSV + optics dumps).
FABRIC_SCHEMA = pa.schema([
    ("ts", pa.timestamp("us")),
    ("cluster", pa.string()),
    ("plane", pa.string()),           # ib|eth|nvlink
    ("switch", pa.string()),          # sorted column in curated zone
    ("switch_guid", pa.string()),
    ("port", pa.int16()),
    ("su", pa.string()),
    ("rack", pa.string()),
    ("peer_node", pa.string()),
    ("peer_port", pa.string()),
    ("link_speed", pa.string()),
    ("link_width", pa.string()),
    ("ber_raw", pa.float64()),
    ("ber_eff", pa.float64()),
    ("fec_corrected", pa.float64()),
    ("fec_uncorrected", pa.float64()),
    ("symbol_errors", pa.float64()),
    ("rx_power_dbm", pa.float64()),
    ("tx_power_dbm", pa.float64()),
    ("module_temp_c", pa.float64()),
    ("pfc_pause", pa.float64()),
    ("ecn_marked", pa.float64()),
    ("discards", pa.float64()),
    ("oper_state", pa.int8()),
])

# 2.4 switch_events — LLDPq/IB flap & SM/pkey change log (append-only).
SWITCH_EVENTS_SCHEMA = pa.schema([
    ("ts", pa.timestamp("us")),
    ("cluster", pa.string()),
    ("su", pa.string()),
    ("rack", pa.string()),
    ("plane", pa.string()),
    ("switch", pa.string()),
    ("port", pa.int16()),
    ("event", pa.string()),           # link_down|link_up|flap|sm_change|pkey_change
    ("detail", pa.map_(pa.string(), pa.string())),
    ("raw", pa.string()),
])

# 2.5 validation_runs — one row per NCCL/HPL/MNUberGEMM/DCGM-diag run.
VALIDATION_RUNS_SCHEMA = pa.schema([
    ("ts", pa.timestamp("us")),
    ("cluster", pa.string()),
    ("su", pa.string()),
    ("rack", pa.string()),
    ("node", pa.string()),
    ("run_id", pa.string()),
    ("kind", pa.string()),            # nccl|hpl|mnubergemm|dcgm_diag|nvbandwidth|nvsm
    ("scope", pa.string()),           # single-node|rack|su|across-su|all
    ("verdict", pa.string()),         # pass|fail|quarantine
    ("measured", pa.map_(pa.string(), pa.float64())),  # busbw, tflops, step_time…
    ("job", pa.string()),
    ("raw", pa.string()),
])

# 2.6 nccl_results — one row per (collective x round x message size x placement)
# parsed out of nccl-tests `all_reduce_perf` / `*_perf_mpi` sweep output.
#
# ADDITIVE ONLY: this table is new; nothing above changed. Partitioning for this
# table is NOT the cluster/su/rack/date/hour of PARTITION_KEYS — see
# nccl_ingest.NCCL_LANDING_PARTITION (cluster/date/run_id): a run is written as
# one atomic directory so re-ingest is `rm -rf <run_id dir>` and never a
# read-modify-write. `hour` is deliberately absent (runs are 30-180 min apart).
#
# `placement` is a ROW dimension, not a pair of column families: the MOP §7.3
# primary metric is out-of-place busbw, so `WHERE placement='out_of_place'`
# becomes a partition/statistics pushdown instead of a column choice.
#
# `source`/`fixture` are NON-NULLABLE provenance. Any row that did not come from
# a real cluster run carries source='fixture' AND fixture=true, and its run_id is
# forced to start with 'FIXTURE-' so the partition path says so too.
NCCL_RESULTS_SCHEMA = pa.schema([
    ("ts", pa.timestamp("us")),          # collective/round completion (else file mtime)
    ("cluster", pa.string()),
    ("su", pa.string()),
    ("rack", pa.string()),               # the NVLink domain under test
    ("run_id", pa.string()),             # <cluster>-<harness>-<workload>-<unit>[-r<n>]-<jobkey>
    ("unit_key", pa.string()),           # stable across MAX_ATTEMPTS retries
    ("job_id", pa.string()),             # slurm jobid, or t<epoch> for the rounds script
    ("harness", pa.string()),            # llmb|rackstatus|sbatch|manual
    ("workload", pa.string()),           # nccl_single|nccl_multi|nccl_allreduce|nccl_rounds
    ("scope", pa.string()),              # loopback|single_node|rack|group|multi_rack
    ("collective", pa.string()),         # all_reduce|all_gather|reduce_scatter|alltoall|sendrecv
    ("round", pa.int16()),               # 1-based NVIS_NCCL_ROUNDS sweep index
    ("iter_label", pa.string()),         # llmb `iter1` tag
    ("placement", pa.string()),          # out_of_place|in_place
    ("size_bytes", pa.int64()),          # nccl-tests col `size` (B)
    ("count_elems", pa.int64()),         # col `count` (elements)
    ("dtype", pa.string()),              # col `type`  (float|half|bfloat16|fp8_e4m3|…)
    ("redop", pa.string()),              # col `redop` — NULL on the 11-column dialect
    ("root", pa.int32()),                # col `root`  — NULL on 11-col; -1 = non-rooted
    ("time_us", pa.float64()),
    ("algbw_gbps", pa.float64()),
    ("busbw_gbps", pa.float64()),        # THE metric (MOP §7.3 primary)
    ("wrong", pa.int64()),               # `#wrong`; -1 encodes N/A (validation: 0)
    ("nranks", pa.int32()),
    ("nnodes", pa.int16()),
    ("gpus_per_node", pa.int8()),
    ("nodelist", pa.string()),           # folded hostlist actually allocated
    ("nccl_version", pa.string()),       # result-changing
    ("nccl_lib_path", pa.string()),
    ("nccl_tests_bin", pa.string()),
    ("transport", pa.string()),          # NVLink/intra|NET/IB|NET/Socket|NET/SPCX
    ("floor_gbps", pa.float64()),        # threshold in force at scoring time
    ("floor_source", pa.string()),       # profile:gb300-nvl72|mop:7.3C|…
    ("verdict", pa.string()),            # pass|fail — NULL on non-scored rows
    ("is_peak", pa.bool_()),             # the row the scorer used (largest size, oop)
    ("avg_busbw_gbps", pa.float64()),    # `# Avg bus bandwidth` footer
    ("oob_ok", pa.bool_()),              # `# Out of bounds values : n OK`
    ("src_file", pa.string()),
    ("src_lineno", pa.int32()),
    ("kv", pa.map_(pa.string(), pa.string())),   # NCCL_IB_HCA, mpirun mca flags, …
    ("source", pa.string()),             # 'live' | 'fixture'  — NEVER null
    ("fixture", pa.bool_()),             # true == synthetic/demo  — NEVER null
])

# 2.8 run_artifacts — the VERBATIM inputs that defined a run, content-addressed.
#
# Purpose: a result must always be traceable back to EXACTLY what was run. That
# means the conf/profile files, the validation-test definitions, the sbatch job
# scripts, the HPL input decks and the synthesized launch argv are captured as
# BYTES, not as a summary — `sha256` is the content address and `content` is the
# blob itself, so a two-year-old FAIL is still reproducible after the source tree
# has moved on.
#
# ADDITIVE ONLY: nothing above changed. Like nccl_results this table does NOT use
# PARTITION_KEYS; see lake_artifacts.ARTIFACT_LANDING_PARTITION
# (cluster/date/run_id). Artifacts are only ever read as "give me everything that
# produced run X" — a directory listing, never a scan — so run_id stays a
# directory in BOTH zones and the table is deliberately absent from
# lake_compact.TABLES (compaction would destroy the one access pattern it has).
#
# `content` is a string column, never binary: text is stored decoded and verbatim
# (encoding='utf8'); anything that is not valid round-trippable UTF-8 is stored
# base64 (encoding='base64'). Blobs larger than ARTIFACT_INLINE_MAX spill to
# LAKE_ROOT/blobs/sha256=<hex>/<filename> and carry encoding='ref' with the path
# in `content_ref`, so the sha256 round-trip holds for every row either way.
RUN_ARTIFACTS_SCHEMA = pa.schema([
    ("captured_at", pa.timestamp("us")),  # when the lake took the copy
    ("cluster", pa.string()),
    ("run_id", pa.string()),              # join key to validation_runs / nccl_results
    ("artifact_type", pa.string()),       # cluster_conf|workloads_conf|platform_profile|
                                          # rack_inventory|sbatch|hpl_dat|llmb_recipe_yaml|
                                          # rack_config_env|validation_test_env|
                                          # image_manifest|launch_cmdline|env_snapshot|
                                          # mop|lib_sh|other
    ("artifact_path", pa.string()),       # absolute path on the source host
    ("filename", pa.string()),
    ("sha256", pa.string()),              # of the RAW bytes — the content address
    ("size_bytes", pa.int64()),           # of the RAW bytes
    ("mtime", pa.timestamp("us")),        # source file mtime (NULL for synthesized)
    ("media_type", pa.string()),
    ("encoding", pa.string()),            # utf8|base64|ref
    ("content", pa.string()),             # THE BLOB (NULL only when encoding='ref')
    ("content_ref", pa.string()),         # blobs/sha256=<hex>/<filename> when spilled
    ("su", pa.string()),
    ("rack", pa.string()),
    ("node", pa.string()),
    ("job_id", pa.string()),
    ("harness", pa.string()),             # llmb|rackstatus|sbatch|manual
    ("capture_kind", pa.string()),        # run|suite_snapshot
    ("source_host", pa.string()),         # host the bytes were read from
    ("parsed", pa.map_(pa.string(), pa.string())),    # KEY=VALUE lifted verbatim
    ("resolved", pa.map_(pa.string(), pa.string())),  # after ${VAR} expansion
    ("captured_by", pa.string()),
    ("ingest_version", pa.string()),
    ("fixture", pa.bool_()),              # NEVER null; true == synthetic/demo
])

# 2.7 writer_meta — internal per-flush accounting (also exported to Prometheus).
WRITER_META_SCHEMA = pa.schema([
    ("ts", pa.timestamp("us")),
    ("cluster", pa.string()),
    ("su", pa.string()),
    ("rack", pa.string()),
    ("table", pa.string()),
    ("rows", pa.int64()),
    ("bytes", pa.int64()),
    ("flush_lag_s", pa.float64()),
    ("dropped", pa.int64()),
])

SCHEMAS = {
    "metrics": METRICS_SCHEMA,
    "logs": LOGS_SCHEMA,
    "fabric_phy": FABRIC_SCHEMA,
    "switch_events": SWITCH_EVENTS_SCHEMA,
    "validation_runs": VALIDATION_RUNS_SCHEMA,
    "nccl_results": NCCL_RESULTS_SCHEMA,
    "run_artifacts": RUN_ARTIFACTS_SCHEMA,
    "writer_meta": WRITER_META_SCHEMA,
}

# Curated-zone sort key per table (folds high-card dim into a sorted column so
# row-group min/max stats give predicate pushdown without a directory explosion).
SORT_KEY = {
    "metrics": "node",
    "logs": "node",
    "fabric_phy": "switch",
    "switch_events": "switch",
    "validation_runs": "node",
    # nccl_results curates to cluster/date/su/rack, so `rack` is already a dir;
    # inside a curated file the useful sort is run/collective/size.
    "nccl_results": "run_id",
    # run_artifacts is NOT compacted (see lake_compact.TABLES); the sort key is
    # declared so a manual rewrite keeps the "all inputs of run X, in path order"
    # ordering that makes provenance diffs readable.
    "run_artifacts": "artifact_path",
}
