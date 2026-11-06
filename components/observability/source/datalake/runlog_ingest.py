#!/usr/bin/env python3
"""
runlog_ingest.py — the two write targets of the validation LOG lane:

  1. RAW-BLOB ZONE (whole files, byte-exact, content-addressed)
        $LAKE_ROOT/blobs/sha256=<hex>/<filename>[.gz]
     Same layout the run_artifacts lane uses for conf/sbatch blobs, so one
     `blobs/` tree serves both and identical files across 112 racks store once.
     sha256 is ALWAYS of the UNCOMPRESSED bytes: the address stays content-exact
     and is verifiable after gunzip.

  2. run_logs / run_log_files PARQUET (typed, partitioned, queryable)
        $LAKE_ROOT/landing/run_logs/cluster=/date=/run_id=/stream=/part-*.parquet
        $LAKE_ROOT/landing/run_log_files/cluster=/date=/run_id=/part-*.parquet

Why a direct writer instead of POSTing to nvis-lakewriter:9410
  * lakewriter is a PUSH server for Prometheus remote_write and Loki push. A
    whole 450 MB per-rank NCCL debug file is not a metric sample and not a Loki
    line; there is no endpoint that could carry it and no schema it would land in.
  * lakewriter's admission gate (`_free_bytes() < MIN_FREE_BYTES`) 429s every
    POST while the /data bind is stale. File ingest must not inherit that
    coupling: a log that failed to land is evidence permanently lost, whereas a
    metric sample is re-derivable from VictoriaMetrics.
  * File ingest is inherently batch and idempotent (content-addressed + a
    bookmark), so it does not need — and must not pay for — the streaming WAL.

Writes are atomic: `part-<uuid>.parquet.tmp` -> fsync -> os.replace().
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import socket
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import runlogs_schema as rls
from runlog_parse import INGEST_TOOL, INGEST_VERSION

CLUSTER = os.environ.get("CLUSTER_NAME", "IREN_MKZ")
LAKE_ROOT = Path(os.environ.get("LAKE_ROOT", "/data/lake"))
LANDING = LAKE_ROOT / "landing"
BLOBS = LAKE_ROOT / "blobs"
STATE_DIR = LAKE_ROOT / "_state"
ZSTD_LEVEL = int(os.environ.get("RUNLOG_ZSTD_LEVEL", "3"))
BLOB_GZIP = os.environ.get("RUNLOG_BLOB_GZIP", "1") not in ("0", "false", "no")
BLOB_MIN_GZIP = int(os.environ.get("RUNLOG_BLOB_MIN_GZIP", "4096"))
CAPTURE_HOST = os.environ.get("CAPTURE_HOST") or socket.gethostname()

_SAFE_KEEP = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")


def part_value(v) -> str:
    """Hive partition values must be path-safe. Never silently drop a value."""
    s = "" if v is None else str(v)
    out = "".join(c if c in _SAFE_KEEP else "_" for c in s)
    return out or "UNKNOWN"


FINGERPRINT_BYTES = int(os.environ.get("RUNLOG_FINGERPRINT_BYTES", "4096"))


def fingerprint(path: str, nbytes: int = 0) -> tuple[str, int]:
    """sha256 of the file's first `nbytes` bytes (default: FINGERPRINT_BYTES).

    Returns (hex, bytes_actually_hashed) — the LENGTH must be carried in the
    bookmark alongside the hash.

    Size alone cannot distinguish "the job appended more output" from "the file
    was REPLACED by a new run at the same path" (Slurm reuses --output paths,
    rounds/summary.tsv is rewritten in place, a redeployed harness rewrites
    aat.log). A shorter-prefix rewrite whose new length happens to exceed the
    old bookmark would otherwise be parsed from the middle of a line and every
    subsequent row would be garbage.

    But a fixed-window fingerprint is ALSO wrong while the file is still shorter
    than the window: hashing "first 4096 bytes" of a 3027-byte file hashes all
    3027, and one appended line changes it, so an ordinary append would look
    like a replacement and re-ingest the whole file (duplicate rows). Hence the
    caller re-hashes exactly the PREVIOUSLY RECORDED length and compares; only
    a mismatch over that same prefix means rotation.
    """
    n = nbytes or FINGERPRINT_BYTES
    h = hashlib.sha256()
    got = 0
    try:
        with open(path, "rb") as fh:
            b = fh.read(n)
            h.update(b)
            got = len(b)
    except OSError:
        return "", 0
    return h.hexdigest(), got


def sha256_file(path: str, bufsize: int = 1 << 20) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        while True:
            b = fh.read(bufsize)
            if not b:
                break
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


# ---------------------------------------------------------------------------
# raw-blob zone
# ---------------------------------------------------------------------------
def blob_ref_for(sha: str, filename: str, gz: bool) -> str:
    return f"blobs/sha256={sha}/{filename}{'.gz' if gz else ''}"


def store_blob(src: str, sha: str, size: int) -> tuple[str, str, int]:
    """Copy `src` into the content-addressed blob zone. Idempotent no-op when the
    address already exists. Returns (blob_ref, encoding, stored_bytes)."""
    filename = os.path.basename(src)
    gz = BLOB_GZIP and size >= BLOB_MIN_GZIP
    d = BLOBS / f"sha256={sha}"
    dst = d / (filename + (".gz" if gz else ""))
    ref = blob_ref_for(sha, filename, gz)
    if dst.exists():
        return ref, ("gzip" if gz else "identity"), dst.stat().st_size
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(d), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out:
            if gz:
                # mtime=0 so the same content always produces the same bytes.
                with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=6,
                                   mtime=0) as gzf, open(src, "rb") as fin:
                    while True:
                        b = fin.read(1 << 20)
                        if not b:
                            break
                        gzf.write(b)
            else:
                with open(src, "rb") as fin:
                    while True:
                        b = fin.read(1 << 20)
                        if not b:
                            break
                        out.write(b)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return ref, ("gzip" if gz else "identity"), dst.stat().st_size


def verify_blob(ref: str) -> bool:
    """Re-hash a stored blob (gunzipping if needed) and check it against its own
    address. This is the archive's self-audit: an unverifiable blob is a lie."""
    p = LAKE_ROOT / ref
    try:
        want = ref.split("sha256=")[1].split("/")[0]
    except IndexError:
        return False
    h = hashlib.sha256()
    opener = gzip.open if str(p).endswith(".gz") else open
    try:
        with opener(p, "rb") as fh:
            while True:
                b = fh.read(1 << 20)
                if not b:
                    break
                h.update(b)
    except OSError:
        return False
    return h.hexdigest() == want


# ---------------------------------------------------------------------------
# partitioned parquet writer
# ---------------------------------------------------------------------------
class PartitionedWriter:
    """One parquet part per (table, partition key) per call. Batch-oriented:
    a log file is ingested as a unit, so buffering across files buys nothing and
    would only widen the crash-loss window."""

    def __init__(self, table: str, root: Path | None = None):
        self.table = table
        self.schema = rls.SCHEMAS[table]
        self.fields = rls.LANDING_PARTITION[table]
        self.root = (root or LANDING) / table
        self.sort_key = rls.SORT_KEY[table]

    def _dir(self, key: dict) -> Path:
        d = self.root
        for f in self.fields:
            d = d / f"{f}={part_value(key.get(f))}"
        return d

    @staticmethod
    def _date_of(ts_us: int) -> str:
        return f"{datetime.fromtimestamp(ts_us / 1e6, tz=timezone.utc):%Y-%m-%d}"

    def write(self, rows: list[dict]) -> list[Path]:
        if not rows:
            return []
        buckets: dict[tuple, list[dict]] = {}
        for r in rows:
            key = {}
            for f in self.fields:
                key[f] = (self._date_of(r["ts"]) if f == "date"
                          else r.get(f, CLUSTER if f == "cluster" else None))
            buckets.setdefault(tuple(key[f] for f in self.fields), []).append(r)
        out: list[Path] = []
        for kt, sub in buckets.items():
            key = dict(zip(self.fields, kt))
            out.append(self._write_one(key, sub))
        return out

    def _write_one(self, key: dict, rows: list[dict]) -> Path:
        cols: dict[str, list] = {f.name: [] for f in self.schema}
        for r in rows:
            for name in cols:
                cols[name].append(r.get(name))
        arrays = []
        for f in self.schema:
            v = cols[f.name]
            if pa.types.is_timestamp(f.type):
                v = [None if x is None else
                     (x if isinstance(x, datetime)
                      else datetime.fromtimestamp(int(x) / 1e6, tz=timezone.utc)
                      .replace(tzinfo=None))
                     for x in v]
            elif pa.types.is_map(f.type):
                v = [None if x is None else list(dict(x).items()) for x in v]
            arrays.append(pa.array(v, type=f.type))
        tbl = pa.Table.from_arrays(arrays, schema=self.schema)
        sort_cols = [c for c in self.sort_key if c in tbl.column_names]
        if sort_cols:
            tbl = tbl.sort_by([(c, "ascending") for c in sort_cols])
        d = self._dir(key)
        d.mkdir(parents=True, exist_ok=True)
        name = f"part-{uuid.uuid4().hex}.parquet"
        tmp = d / (name + ".tmp")
        pq.write_table(tbl, tmp, compression="zstd",
                       compression_level=ZSTD_LEVEL, use_dictionary=True,
                       write_statistics=True)
        # fsync the file AND its directory so the rename survives a power cut.
        with open(tmp, "rb") as fh:
            os.fsync(fh.fileno())
        final = d / name
        os.replace(tmp, final)
        dfd = os.open(str(d), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
        return final


# ---------------------------------------------------------------------------
# bookmark state — makes the collector incremental, idempotent and restartable
# ---------------------------------------------------------------------------
class CollectorState:
    """`$LAKE_ROOT/_state/logcollect.json`, keyed by absolute source path.

    Per file: {inode, size, mtime_ns, offset, lines, sha256, blob_sha, run_id}.
      * sha256 unchanged  -> nothing to do (idempotent re-scan).
      * size grew         -> parse ONLY [offset, size) (Slurm stdout is appended
                             to for the life of the job).
      * size shrank       -> rotation/truncation; restart from 0.
    Written tmp -> fsync -> replace so a crash mid-write cannot corrupt it.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (STATE_DIR / "logcollect.json")
        self.data = {"version": 1, "files": {}}
        self.load()

    def load(self):
        try:
            with open(self.path) as fh:
                d = json.load(fh)
            if isinstance(d, dict) and "files" in d:
                self.data = d
        except (OSError, ValueError):
            pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w") as fh:
            json.dump(self.data, fh, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def get(self, path: str) -> dict:
        return self.data["files"].get(os.path.abspath(path), {})

    def put(self, path: str, rec: dict):
        rec["updated"] = time.time()
        self.data["files"][os.path.abspath(path)] = rec


# ---------------------------------------------------------------------------
# row assembly
# ---------------------------------------------------------------------------
def build_log_rows(parsed_lines, ident, su, rack, src_file, src_sha,
                   fallback_ts_us: int, fixture: bool) -> list[dict]:
    """parsed_lines: iterable of (lineno, raw_line, parsed_dict)."""
    src = "fixture" if fixture else "live"
    rows = []
    for lineno, raw, p in parsed_lines:
        ts = p["ts_us"]
        exact = bool(p["ts_exact"])
        if ts is None:
            # No timestamp in the line (the NCCL norm). Anchor on the file's
            # mtime and add a per-line microsecond so ORDER is preserved and no
            # two rows collide; ts_exact=False says precision is synthetic.
            ts = fallback_ts_us + lineno
            exact = False
        rows.append({
            "ts": ts, "ts_exact": exact,
            "cluster": CLUSTER, "su": su, "rack": rack,
            "node": p.get("host") or ident.node or "",
            "run_id": ident.run_id, "unit_key": ident.unit_key,
            "job_id": ident.job_id, "activity_id": ident.activity_id,
            "harness": ident.harness,
            "workload": ident.workload, "stream": ident.stream,
            "rank": p.get("rank"), "local_rank": p.get("local_rank"),
            "pid": p.get("pid"), "device": p.get("device"),
            "host": p.get("host"), "round": p.get("round"),
            "severity": p.get("severity"), "msg_class": p.get("msg_class"),
            "xid": p.get("xid"),
            "src_file": src_file, "src_sha256": src_sha, "lineno": lineno,
            "kv": p.get("kv") or {}, "line": raw,
            "source": src, "fixture": fixture,
            "ingest_tool": INGEST_TOOL, "ingest_version": INGEST_VERSION,
        })
    return rows
