#!/usr/bin/env python3
"""
lake_artifacts.py — run-artifact capture for the IREN_MKZ Parquet data lake.

WHY THIS EXISTS
    Goal 3 of the lake is provenance: a validation result must always be
    traceable back to EXACTLY what was run. Metrics and logs cannot do that — a
    busbw number is meaningless six months later if the profile that set
    NCCL_FLOOR_ALL_REDUCE=820, the sbatch that set the mpirun flags, and the
    workloads.conf that gated the run have all moved on. This module lands those
    inputs as BYTES, keyed by run_id and addressed by sha256.

WHAT IT CAPTURES
    Any file that defines a run: conf/cluster.conf, conf/workloads.conf,
    conf/profiles/*.conf, conf/inventory/racks.txt, jobs/*.sbatch, jobs/hpl/*.dat,
    rack-config.env, validation_test_env.sh, the vetted-image manifest, the llmb
    recipe YAML — plus SYNTHESIZED artifacts that never exist as a file on disk
    (the resolved llmb-run / sbatch argv, the full NCCL_*/UCX_*/OMPI_* env
    snapshot). Those are pushed with an artifact_path of the form
    `synthesized:<name>` and a NULL mtime.

STORAGE MODEL
    landing/run_artifacts/cluster=<c>/date=<YYYY-MM-DD>/run_id=<id>/part-<uuid>.parquet

    run_id is a DIRECTORY, not a column-only dimension, because every read of
    this table is "give me everything that produced run X" — a directory listing,
    never a scan. It also makes each capture atomic and idempotent: one run is
    one directory, re-ingest is `rm -rf` that directory, never a
    read-modify-write. This table is deliberately NOT in lake_compact.TABLES.

    `content` is a string column, never binary:
      encoding='utf8'   -> content holds the decoded text, verbatim
      encoding='base64' -> content holds base64(raw) because raw is not valid,
                           round-trippable UTF-8
      encoding='ref'    -> content is NULL and the bytes live at
                           LAKE_ROOT/blobs/sha256=<hex>/<filename> (content_ref),
                           used when size > ARTIFACT_INLINE_MAX
    In all three cases sha256 is the digest of the RAW bytes, so the round-trip
    check is uniform (see `verify_run`).

INTEGRITY
    The sha256 a client sends is never trusted: the server recomputes it over the
    decoded bytes and REJECTS the whole push on mismatch. A silently-corrupted
    provenance record is worse than no provenance record.

Env: LAKE_ROOT, CLUSTER_NAME (via lake_common), ARTIFACT_INLINE_MAX (1 MiB).

CLI:
  python lake_artifacts.py runs [--cluster C]            list captured run_ids
  python lake_artifacts.py verify --run-id R [--cluster C]
                                                        sha256 round-trip check
  python lake_artifacts.py show --run-id R --type sbatch dump a captured blob
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from lake_common import CLUSTER, LAKE_ROOT, LANDING, ZSTD_LEVEL
from schema import RUN_ARTIFACTS_SCHEMA

TABLE = "run_artifacts"
BLOBS = LAKE_ROOT / "blobs"
INGEST_VERSION = "lake_artifacts/1.0.0"

# Landing partition spec for THIS table. Deliberately different from
# schema.PARTITION_KEYS (cluster/su/rack/date/hour) — see module docstring.
ARTIFACT_LANDING_PARTITION = ["cluster", "date", "run_id"]

# Blobs bigger than this spill to a content-addressed sidecar instead of going
# inline into the parquet `content` column. A client may ask for a SMALLER
# threshold (X-Lake-Inline-Max header) but never a larger one.
INLINE_MAX = int(os.environ.get("ARTIFACT_INLINE_MAX", str(1024 * 1024)))

# Path-safe run_id. Everything here becomes a directory name, so it is validated
# rather than sanitised: silently rewriting a run_id would break the join to
# validation_runs / nccl_results, which is the entire point of the table.
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,190}$")


class ArtifactError(ValueError):
    """Client-side error: bad run_id, bad encoding, sha256 mismatch."""


# ---- classification --------------------------------------------------------
# Ordered most-specific-first; the first match wins.
_TYPE_RULES = [
    (re.compile(r"/conf/profiles/[^/]+\.conf$"),        "platform_profile"),
    (re.compile(r"/conf/inventory/racks\.txt"),         "rack_inventory"),
    (re.compile(r"/conf/cluster\.conf(\.example)?$"),   "cluster_conf"),
    (re.compile(r"/conf/interview-answers\.conf$"),     "interview_answers"),
    (re.compile(r"/conf/workloads\.conf$"),             "workloads_conf"),
    (re.compile(r"/jobs/hpl/[^/]+\.dat$"),              "hpl_dat"),
    (re.compile(r"\.sbatch$"),                          "sbatch"),
    (re.compile(r"/rack-config\.env$"),                 "rack_config_env"),
    (re.compile(r"/validation_test_env\.sh$"),          "validation_test_env"),
    (re.compile(r"manifest\.json$"),                    "image_manifest"),
    (re.compile(r"system_config\.ya?ml$"),              "llmb_system_config"),
    (re.compile(r"_MOP\.md$|/mops?/.*\.md$"),           "mop"),
    (re.compile(r"\.ya?ml$"),                           "llmb_recipe_yaml"),
    (re.compile(r"/lib/[^/]+\.(sh|inc\.sh)$"),          "lib_sh"),
    (re.compile(r"^synthesized:launch"),                "launch_cmdline"),
    (re.compile(r"^synthesized:env"),                   "env_snapshot"),
]

_MEDIA_BY_SUFFIX = {
    ".sbatch": "text/x-shellscript",
    ".sh": "text/x-shellscript",
    ".conf": "text/plain",
    ".env": "text/plain",
    ".dat": "text/plain",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}

# artifact_types whose bodies are shell-style KEY=VALUE and worth lifting into
# the `parsed` map so a query can answer "what floor was in force" without
# re-parsing the blob.
_KV_TYPES = {"platform_profile", "cluster_conf", "interview_answers",
             "rack_config_env", "validation_test_env", "env_snapshot"}

_KV_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def classify(path: str) -> str:
    for rx, kind in _TYPE_RULES:
        if rx.search(path):
            return kind
    return "other"


def media_type_for(path: str) -> str:
    return _MEDIA_BY_SUFFIX.get(Path(path).suffix, "text/plain")


def _unquote(v: str) -> str:
    v = v.strip()
    # strip a trailing inline comment only when it is outside quotes
    if v[:1] in ("'", '"'):
        q = v[0]
        end = v.find(q, 1)
        if end > 0:
            return v[1:end]
    v = v.split(" #", 1)[0].strip()
    return v.strip("'\"")


def parse_kv(text: str) -> dict:
    """Lift shell-style KEY=VALUE lines. Never executes anything."""
    out = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _KV_RE.match(s)
        if m:
            out[m.group(1)] = _unquote(m.group(2))
    return out


def parse_workloads(text: str) -> dict:
    """Flatten workloads.conf's `workload <name> k=v \\` DSL to workload.<n>.<k>."""
    out = {}
    logical, buf = [], ""
    for line in text.splitlines():
        s = line.rstrip()
        if s.endswith("\\"):
            buf += s[:-1] + " "
            continue
        logical.append(buf + s)
        buf = ""
    if buf:
        logical.append(buf)
    order = 0
    for rec in logical:
        rec = rec.strip()
        if not rec.startswith("workload "):
            continue
        toks = rec.split()
        name = toks[1]
        order += 1
        out[f"workload.{name}.order"] = str(order)
        for t in toks[2:]:
            if "=" in t:
                k, v = t.split("=", 1)
                out[f"workload.{name}.{k}"] = v
    return out


def resolve_vars(parsed: dict, context: dict) -> dict:
    """Expand ${VAR} / ${VAR:-default} textually against `context`.

    Purely textual — no shell is spawned. This is what makes an old FAIL
    reproducible: workloads.conf stores `thresholds=all_reduce:${NCCL_FLOOR_ALL_REDUCE:-}`,
    which is unresolvable once the profile has been retuned.
    """
    env = dict(context)
    out = {}
    for k, v in parsed.items():
        def sub(m, _env=env):
            name, dflt = m.group(1), m.group(2)
            got = _env.get(name)
            return got if got not in (None, "") else (dflt or "")
        new = _VAR_RE.sub(sub, v)
        if new != v:
            out[k] = new
    return out


# ---- storage ---------------------------------------------------------------
def part_dir(cluster: str, captured_at_us: int, run_id: str) -> Path:
    dt = datetime.fromtimestamp(captured_at_us / 1_000_000, tz=timezone.utc)
    return (LANDING / TABLE / f"cluster={cluster}" /
            f"date={dt:%Y-%m-%d}" / f"run_id={run_id}")


def blob_rel(sha256: str, filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename or "blob") or "blob"
    return f"blobs/sha256={sha256}/{safe}"


def write_blob(sha256: str, filename: str, data: bytes) -> str:
    """Content-addressed sidecar. Idempotent: identical bytes are stored once."""
    rel = blob_rel(sha256, filename)
    dst = LAKE_ROOT / rel
    if dst.exists() and dst.stat().st_size == len(data):
        return rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + f".{uuid.uuid4().hex}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, dst)
    return rel


def _encode_for_storage(data: bytes, filename: str, inline_max: int):
    """-> (encoding, content, content_ref). sha256 always covers RAW bytes."""
    sha = hashlib.sha256(data).hexdigest()
    if len(data) > inline_max:
        return "ref", None, write_blob(sha, filename, data)
    try:
        text = data.decode("utf-8")
        if text.encode("utf-8") == data:
            return "utf8", text, None
    except UnicodeDecodeError:
        pass
    return "base64", base64.b64encode(data).decode("ascii"), None


def _us(v) -> int | None:
    """epoch seconds (int/float/str) -> microseconds; None passes through."""
    if v in (None, ""):
        return None
    return int(float(v) * 1_000_000)


def rows_from_payload(payload: dict, inline_max: int | None = None) -> list[dict]:
    """Decode an artifact push into RUN_ARTIFACTS_SCHEMA rows.

    Wire format (JSON):
      { "run_id": "...", "cluster": "...", "job_id": "...", "harness": "...",
        "capture_kind": "run|suite_snapshot", "source_host": "...",
        "captured_by": "...", "fixture": false, "captured_at": <epoch_s>,
        "resolve_context": {"NCCL_FLOOR_ALL_REDUCE": "820", ...},
        "artifacts": [
          { "artifact_path": "/abs/path" | "synthesized:<name>",
            "artifact_type": "...",        # optional, auto-classified
            "encoding": "utf8"|"base64",   # of the WIRE payload
            "content": "...",
            "sha256": "...",               # optional, VERIFIED not trusted
            "size_bytes": 123,             # optional, VERIFIED not trusted
            "mtime": <epoch_s>,            # optional
            "node": "...", "su": "...", "rack": "..." } , ... ] }
    """
    run_id = str(payload.get("run_id") or "").strip()
    if not RUN_ID_RE.match(run_id):
        raise ArtifactError(f"invalid run_id {run_id!r}: must match {RUN_ID_RE.pattern}")
    cluster = str(payload.get("cluster") or CLUSTER)
    if not RUN_ID_RE.match(cluster):
        raise ArtifactError(f"invalid cluster {cluster!r}")

    inline_max = INLINE_MAX if inline_max is None else max(0, min(inline_max, INLINE_MAX))
    now_us = _us(payload.get("captured_at")) or int(time.time() * 1_000_000)
    fixture = bool(payload.get("fixture", False))
    ctx = dict(payload.get("resolve_context") or {})

    arts = payload.get("artifacts") or []
    if not isinstance(arts, list):
        raise ArtifactError("artifacts must be a list")

    rows = []
    for a in arts:
        path = str(a.get("artifact_path") or "")
        if not path:
            raise ArtifactError("artifact_path is required")
        wire_enc = (a.get("encoding") or "utf8").lower()
        raw = a.get("content")
        if raw is None:
            raise ArtifactError(f"{path}: content is required")
        if wire_enc == "base64":
            try:
                data = base64.b64decode(raw, validate=True)
            except Exception as e:
                raise ArtifactError(f"{path}: bad base64: {e}") from e
        elif wire_enc == "utf8":
            data = str(raw).encode("utf-8")
        else:
            raise ArtifactError(f"{path}: unsupported wire encoding {wire_enc!r}")

        sha = hashlib.sha256(data).hexdigest()
        claimed = a.get("sha256")
        if claimed and claimed.lower() != sha:
            # Never land a provenance record we cannot vouch for.
            raise ArtifactError(
                f"{path}: sha256 mismatch client={claimed} server={sha}")
        claimed_size = a.get("size_bytes")
        if claimed_size is not None and int(claimed_size) != len(data):
            raise ArtifactError(
                f"{path}: size mismatch client={claimed_size} server={len(data)}")

        filename = Path(path.split(":", 1)[-1] if path.startswith("synthesized:")
                        else path).name
        atype = a.get("artifact_type") or classify(path)
        enc, content, ref = _encode_for_storage(data, filename, inline_max)

        parsed = dict(a.get("parsed") or {})
        if not parsed and enc == "utf8":
            if atype in _KV_TYPES:
                parsed = parse_kv(content)
            elif atype == "workloads_conf":
                parsed = parse_workloads(content)
        resolved = dict(a.get("resolved") or {})
        if not resolved and parsed:
            merged = {**ctx, **{k: v for k, v in parsed.items() if "." not in k}}
            resolved = resolve_vars(parsed, merged)

        rows.append({
            "captured_at": now_us,
            "cluster": cluster,
            "run_id": run_id,
            "artifact_type": atype,
            "artifact_path": path,
            "filename": filename,
            "sha256": sha,
            "size_bytes": len(data),
            "mtime": _us(a.get("mtime")),
            "media_type": a.get("media_type") or media_type_for(path),
            "encoding": enc,
            "content": content,
            "content_ref": ref,
            "su": a.get("su") or payload.get("su"),
            "rack": a.get("rack") or payload.get("rack"),
            "node": a.get("node") or payload.get("node"),
            "job_id": a.get("job_id") or payload.get("job_id"),
            "harness": payload.get("harness"),
            "capture_kind": payload.get("capture_kind") or "run",
            "source_host": payload.get("source_host"),
            "parsed": parsed or None,
            "resolved": resolved or None,
            "captured_by": payload.get("captured_by"),
            "ingest_version": INGEST_VERSION,
            "fixture": fixture,
        })
    return rows


def rows_to_table(rows: list[dict]) -> pa.Table | None:
    if not rows:
        return None
    cols = {f.name: [r.get(f.name) for r in rows] for f in RUN_ARTIFACTS_SCHEMA}
    return pa.Table.from_pydict(cols, schema=RUN_ARTIFACTS_SCHEMA)


def _already_landed(d: Path) -> set[tuple[str, str]]:
    """{(artifact_path, sha256)} already present in a run's landing dir."""
    have = set()
    for f in d.glob("*.parquet"):
        try:
            t = pq.ParquetFile(str(f)).read(columns=["artifact_path", "sha256"])
        except Exception:
            continue  # a half-written/foreign file must never block a write
        have.update(zip(t.column("artifact_path").to_pylist(),
                        t.column("sha256").to_pylist()))
    return have


def write_rows(rows: list[dict]) -> list[Path]:
    """Land rows as atomic Parquet under cluster=/date=/run_id=. Returns paths.

    Bypasses LakeSink on purpose: LakeSink buckets by (su, rack, hour), which is
    the wrong grain here, and artifacts are a low-rate, bursty, must-not-be-lost
    stream — buffering them for FLUSH_SECONDS would add a crash-loss window to
    the one table whose whole job is durability.

    IDEMPOTENT: a row whose (artifact_path, sha256) is already landed under this
    run_id is skipped. Retries and re-pushes (a Slurm prolog that fires twice, a
    collect step re-run after a transient failure) are therefore no-ops, while a
    file that genuinely CHANGED between pushes still lands as a new row — which
    is the honest answer, since the run really did see two different inputs.
    """
    tbl = rows_to_table(rows)
    if tbl is None:
        return []
    written = []
    # group by (cluster, date, run_id) — one push is normally a single group
    groups: dict[tuple, list[int]] = {}
    for i, r in enumerate(rows):
        dt = datetime.fromtimestamp(r["captured_at"] / 1_000_000, tz=timezone.utc)
        groups.setdefault((r["cluster"], f"{dt:%Y-%m-%d}", r["run_id"]), []).append(i)
    landed = []
    for (cluster, _date, run_id), idx in groups.items():
        d = part_dir(cluster, rows[idx[0]]["captured_at"], run_id)
        if d.exists():
            have = _already_landed(d)
            idx = [i for i in idx
                   if (rows[i]["artifact_path"], rows[i]["sha256"]) not in have]
            if not idx:
                continue
        sub = tbl.take(pa.array(idx))
        sub = sub.sort_by([("artifact_type", "ascending"),
                           ("artifact_path", "ascending")])
        d.mkdir(parents=True, exist_ok=True)
        name = f"part-{uuid.uuid4().hex}.parquet"
        tmp = d / (name + ".tmp")
        pq.write_table(sub, tmp, compression="zstd",
                       compression_level=ZSTD_LEVEL, use_dictionary=True,
                       write_statistics=True)
        os.replace(tmp, d / name)          # atomic
        written.append(d / name)
        landed += idx
    return written, landed


def ingest_payload(payload: dict, inline_max: int | None = None):
    """Decode + land one artifact push.

    -> (rows_landed, bytes_landed, paths, rows_skipped)
    rows_skipped counts artifacts already present under this run_id with the
    identical sha256 — a duplicate push, not a loss.
    """
    rows = rows_from_payload(payload, inline_max)
    paths, landed = write_rows(rows)
    return (len(landed), sum(rows[i]["size_bytes"] for i in landed), paths,
            len(rows) - len(landed))


# ---- read-back / verification ---------------------------------------------
def run_dirs(cluster: str | None = None):
    base = LANDING / TABLE
    pat = f"cluster={cluster}/date=*/run_id=*" if cluster else "cluster=*/date=*/run_id=*"
    return sorted(p for p in base.glob(pat) if p.is_dir()) if base.exists() else []


def run_files(run_id: str | None = None, cluster: str | None = None) -> list[str]:
    out = []
    for d in run_dirs(cluster):
        if run_id is None or d.name == f"run_id={run_id}":
            out += [str(p) for p in sorted(d.glob("*.parquet"))]
    return out


def read_files(files: list[str]) -> pa.Table:
    """Read an explicit file list with hive discovery OFF.

    IMPORTANT for any consumer of this table: `cluster` and `run_id` are BOTH
    path keys and columns (schema.py's stated convention — a reader must recover
    them either way). pyarrow's hive discovery infers the path copies as
    dictionary<string> and then refuses to merge them with the file's own string
    column: `ArrowTypeError: Field cluster has incompatible types`. Passing an
    explicit file list disables discovery, which is also what lake_compact.py
    does. The equivalent for a directory read is
    `ds.dataset(dir, format="parquet", partitioning=None)`.
    """
    if not files:
        raise FileNotFoundError("no parquet files")
    return pa.concat_tables([pq.ParquetFile(f).read() for f in files])


def read_run(run_id: str, cluster: str | None = None) -> pa.Table:
    files = run_files(run_id, cluster)
    if not files:
        raise FileNotFoundError(f"no landed artifacts for run_id={run_id}")
    return read_files(files)


def row_bytes(row: dict) -> bytes:
    """Reconstruct the RAW bytes of one artifact row, whatever the encoding."""
    enc = row["encoding"]
    if enc == "utf8":
        return row["content"].encode("utf-8")
    if enc == "base64":
        return base64.b64decode(row["content"])
    if enc == "ref":
        return (LAKE_ROOT / row["content_ref"]).read_bytes()
    raise ArtifactError(f"unknown encoding {enc!r}")


def verify_run(run_id: str, cluster: str | None = None) -> dict:
    """sha256 round-trip every row of a run. -> summary dict."""
    tbl = read_run(run_id, cluster)
    ok, bad = 0, []
    for row in tbl.to_pylist():
        try:
            got = hashlib.sha256(row_bytes(row)).hexdigest()
        except Exception as e:
            bad.append((row["artifact_path"], f"read error: {e}"))
            continue
        if got == row["sha256"] and len(row_bytes(row)) == row["size_bytes"]:
            ok += 1
        else:
            bad.append((row["artifact_path"], f"stored={row['sha256']} recomputed={got}"))
    return {"run_id": run_id, "rows": tbl.num_rows, "ok": ok, "bad": bad,
            "bytes": sum(tbl.column("size_bytes").to_pylist())}


def _cli(argv):
    mode = argv[1] if len(argv) > 1 else "runs"
    args = {}
    for i in range(2, len(argv) - 1, 2):
        if argv[i].startswith("--"):
            args[argv[i][2:]] = argv[i + 1]
    cluster = args.get("cluster")
    if mode == "runs":
        for d in run_dirs(cluster):
            n = sum(pq.ParquetFile(f).metadata.num_rows for f in d.glob("*.parquet"))
            print(f"{d.parent.parent.name.split('=')[1]}  {d.parent.name.split('=')[1]}"
                  f"  {d.name.split('=')[1]}  rows={n}")
        return 0
    if mode == "verify":
        res = verify_run(args["run-id"], cluster)
        print(json.dumps({k: v for k, v in res.items() if k != "bad"}, indent=2))
        for p, why in res["bad"]:
            print(f"MISMATCH {p}: {why}", file=sys.stderr)
        return 0 if not res["bad"] else 1
    if mode == "show":
        tbl = read_run(args["run-id"], cluster)
        for row in tbl.to_pylist():
            if args.get("type") and row["artifact_type"] != args["type"]:
                continue
            if args.get("path") and args["path"] not in row["artifact_path"]:
                continue
            print(f"===== {row['artifact_path']} "
                  f"({row['artifact_type']}, {row['size_bytes']}B, "
                  f"sha256={row['sha256'][:16]}…) =====")
            sys.stdout.write(row_bytes(row).decode("utf-8", "replace"))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
