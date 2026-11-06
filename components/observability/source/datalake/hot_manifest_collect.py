#!/usr/bin/env python3
"""Fast manifest lane for settled exact-rack validation stdout.

The archival log collector intentionally walks every validation artifact, but
that tree contains millions of files and one pass can take hours.  Exact-rack
acceptance must not wait behind that archive backlog.  This bounded collector
discovers only authoritative top-level NCCL, NeMo, and MNUberGEMM stdout,
requires a workload terminal marker and five minutes of quiescence, then writes
the same byte-exact blob and ``run_log_files`` manifest used by the full lane.

It deliberately does not parse or duplicate line rows; the archival collector
continues to own complete ``run_logs`` ingestion and Loki forwarding.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import runlog_ingest as ri
from runlog_parse import INGEST_TOOL, INGEST_VERSION, identify


ROOT = Path(os.environ.get("HOT_MANIFEST_ROOT", "/cluster/OVA/logs"))
SETTLE_SECONDS = int(os.environ.get("HOT_MANIFEST_SETTLE_SECONDS", "300"))
STATE_PATH = ri.STATE_DIR / "hot-exact-rack-manifests.json"

SU = r"(?:[1-9]|1[0-4])"
RACK = r"(?:0[1-8]|1[7-9]|2[0-4])"
JOB = r"\d{4,7}"
PATH_RE = re.compile(
    rf"^(?:SU{SU}/rack{RACK}/(?:"
    rf"(?:singleRackNCCL|multiNodeNCCL)/"
    rf"nvftp-nccl-five-collective-{JOB}\.out|"
    rf"(?:singleRackNeMo|multiNodeNeMo)/nemo-26\.04\.01-{JOB}\.out|"
    rf"multiNodeMNU/mnubergemm-.+-{JOB}\.out"
    rf")|iren_mkz-16k-validation/(?:"
    rf"nemo-26\.04\.01-{JOB}\.out|"
    rf"nvftp-nccl-five-collective-{JOB}\.out))$"
)
GLOBS = (
    "SU*/rack*/singleRackNCCL/nvftp-nccl-five-collective-*.out",
    "SU*/rack*/multiNodeNCCL/nvftp-nccl-five-collective-*.out",
    "SU*/rack*/singleRackNeMo/nemo-26.04.01-*.out",
    "SU*/rack*/multiNodeNeMo/nemo-26.04.01-*.out",
    "SU*/rack*/multiNodeMNU/mnubergemm-*.out",
    "iren_mkz-16k-validation/nemo-26.04.01-*.out",
    "iren_mkz-16k-validation/nvftp-nccl-five-collective-*.out",
)
TERMINAL = {
    "nccl_five_collective": re.compile(r"^FIVE_COLLECTIVE_SWEEP_END\b", re.M),
    "nemo_single": re.compile(r"^NEMO_VALIDATION_(?:PASS|FAIL)\b", re.M),
    "mnubergemm": re.compile(r"normal mpi teardown\s*$", re.M),
}
SHARED_NEMO_RE = re.compile(r"^nemo-26\.04\.01-(?P<job>\d{4,7})\.out$")
SHARED_NCCL_RE = re.compile(
    r"^nvftp-nccl-five-collective-(?P<job>\d{4,7})\.out$")
SHARED_NEMO_NODELIST_RE = re.compile(
    r"^NODELIST:\s*example50-(?P<dh>dh\d+)-(?P<letter>[a-z])"
    r"(?P<rack>\d{2})-\[(?P<trays>[\d,-]+)\]\s*$",
    re.MULTILINE,
)
SHARED_NCCL_NODE_RE = re.compile(
    r"^NCCL_IB_PREFLIGHT_READY node=(?P<host>example50-(?P<dh>dh\d+)-"
    r"(?P<letter>[a-z])(?P<rack>\d{2})-(?P<tray>\d{2})) rails=\d+\s*$",
    re.MULTILINE,
)
SHARED_NCCL_START_RE = re.compile(
    r"^FIVE_COLLECTIVE_SWEEP_START\b[^\n]*\bnodes=18\b"
    r"[^\n]*\blayout=exact-request\b",
    re.MULTILINE,
)
TRAYS = {f"{tray:02d}" for tray in (*range(11, 19), *range(28, 38))}
SU_MAP = {("dh02", chr(ord("a") + index)): index + 1 for index in range(11)}
SU_MAP.update({("dh01", chr(ord("a") + index)): index + 12 for index in range(3)})


def discover(root: Path = ROOT) -> list[Path]:
    """Return the bounded authoritative exact-rack source set."""
    found: set[Path] = set()
    for pattern in GLOBS:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if PATH_RE.fullmatch(relative):
                found.add(path)
    return sorted(found)


def bounded_text(path: Path, tail_bytes: int = 512 * 1024) -> str:
    with path.open("rb") as handle:
        size = path.stat().st_size
        if size > tail_bytes:
            handle.seek(size - tail_bytes)
        return handle.read().decode("utf-8", "replace")


def shared_nemo_identity(path: Path, ident):
    """Attach a rack identity to a shared-root NeMo log only from exact geometry."""
    match = SHARED_NEMO_RE.fullmatch(path.name)
    if path.parent.name != "iren_mkz-16k-validation" or not match:
        return ident
    try:
        with path.open("rb") as handle:
            head = handle.read(64 * 1024).decode("utf-8", "replace")
    except OSError:
        return ident
    nodelist = SHARED_NEMO_NODELIST_RE.search(head)
    if not nodelist or (nodelist.group("dh"), nodelist.group("letter")) not in SU_MAP:
        return ident
    trays: set[str] = set()
    for token in nodelist.group("trays").split(","):
        if "-" in token:
            start_raw, end_raw = token.split("-", 1)
            if not (start_raw.isdigit() and end_raw.isdigit()):
                return ident
            start, end = int(start_raw), int(end_raw)
            if end < start:
                return ident
            trays.update(f"{tray:02d}" for tray in range(start, end + 1))
        elif token.isdigit():
            trays.add(f"{int(token):02d}")
        else:
            return ident
    if trays != TRAYS:
        return ident
    dh, letter = nodelist.group("dh"), nodelist.group("letter")
    rack = nodelist.group("rack")
    if not re.fullmatch(RACK, rack):
        return ident
    su = SU_MAP[(dh, letter)]
    rack_host = f"example50-{dh}-{letter}{rack}"
    job = match.group("job")
    ident.job_id = job
    ident.su = f"SU{su}"
    ident.harness = "rackstatus"
    ident.workload = "nemo_single"
    ident.unit_kind = "rack"
    ident.unit_id = rack_host
    ident.stream = "sbatch_stdout"
    ident.run_id = f"{ri.CLUSTER}-rackstatus-nemo_single-{rack_host}-j{job}"
    ident.unit_key = f"{ri.CLUSTER}-nemo_single-{rack_host}-r01"
    return ident


def shared_nccl_identity(path: Path, ident):
    """Attach a rack identity to shared-root NCCL only for exact geometry."""
    match = SHARED_NCCL_RE.fullmatch(path.name)
    if path.parent.name != "iren_mkz-16k-validation" or not match:
        return ident

    # ``identify`` recognises the filename before it knows the shared-root
    # geometry.  Fail closed here so cross-rack and partial-rack sweeps never
    # enter the exact-rack manifest under the shared directory name.
    ident.harness = "unknown"
    ident.workload = "unknown"
    try:
        with path.open("rb") as handle:
            head = handle.read(128 * 1024).decode("utf-8", "replace")
    except OSError:
        return ident
    if not SHARED_NCCL_START_RE.search(head):
        return ident

    nodes = {
        node.group("host"): (
            node.group("dh"), node.group("letter"),
            node.group("rack"), node.group("tray"),
        )
        for node in SHARED_NCCL_NODE_RE.finditer(head)
    }
    if len(nodes) != 18:
        return ident
    racks = {(dh, letter, rack) for dh, letter, rack, _ in nodes.values()}
    if len(racks) != 1:
        return ident
    dh, letter, rack = next(iter(racks))
    if (dh, letter) not in SU_MAP or not re.fullmatch(RACK, rack):
        return ident
    if {tray for _, _, _, tray in nodes.values()} != TRAYS:
        return ident

    su = SU_MAP[(dh, letter)]
    rack_host = f"example50-{dh}-{letter}{rack}"
    job = match.group("job")
    ident.job_id = job
    ident.su = f"SU{su}"
    ident.harness = "rackstatus"
    ident.workload = "nccl_five_collective"
    ident.unit_kind = "rack"
    ident.unit_id = rack_host
    ident.stream = "sbatch_stdout"
    ident.run_id = (
        f"{ri.CLUSTER}-rackstatus-nccl_five_collective-{rack_host}-j{job}")
    ident.unit_key = f"{ri.CLUSTER}-nccl_five_collective-{rack_host}-r01"
    return ident


def is_terminal(path: Path, workload: str) -> bool:
    marker = TERMINAL.get(workload)
    if marker is None:
        return False
    try:
        return bool(marker.search(bounded_text(path)))
    except OSError:
        return False


def manifest_row(path: Path, stat: os.stat_result, ident, sha: str,
                 blob_ref: str, blob_encoding: str,
                 blob_bytes: int) -> dict:
    now_us = int(time.time() * 1_000_000)
    return {
        "ts": now_us,
        "cluster": ri.CLUSTER,
        "su": ident.su or "UNKNOWN",
        "rack": ident.unit_id if ident.unit_kind == "rack" else "UNKNOWN",
        "node": ident.node or "",
        "run_id": ident.run_id,
        "unit_key": ident.unit_key,
        "job_id": ident.job_id,
        "activity_id": ident.activity_id,
        "harness": ident.harness,
        "workload": ident.workload,
        "stream": ident.stream,
        "rank": ident.rank,
        "path": str(path),
        "filename": path.name,
        "capture_host": ri.CAPTURE_HOST,
        "media_type": "text/plain",
        "size_bytes": stat.st_size,
        "sha256": sha,
        "mtime": int(stat.st_mtime * 1_000_000),
        "blob_ref": blob_ref,
        "blob_encoding": blob_encoding,
        "blob_bytes": blob_bytes,
        "lines_total": 0,
        "lines_ingested": 0,
        "byte_offset_start": stat.st_size,
        "byte_offset_end": stat.st_size,
        "loki_pushed": 0,
        "parse_errors": 0,
        "source": "live",
        "fixture": False,
        "ingest_tool": f"{INGEST_TOOL}-hot-manifest",
        "ingest_version": INGEST_VERSION,
    }


def run_once(root: Path = ROOT) -> dict:
    state = ri.CollectorState(STATE_PATH)
    writer = ri.PartitionedWriter("run_log_files")
    now = time.time()
    rows = []
    pending_state = []
    stats = {"discovered": 0, "unsettled": 0, "nonterminal": 0,
             "unchanged": 0, "captured": 0, "errors": 0}
    for path in discover(root):
        stats["discovered"] += 1
        try:
            st = path.stat()
            if now - st.st_mtime < SETTLE_SECONDS:
                stats["unsettled"] += 1
                continue
            ident = identify(str(path), cluster=ri.CLUSTER, fixture=False,
                             mtime=st.st_mtime)
            ident = shared_nemo_identity(path, ident)
            ident = shared_nccl_identity(path, ident)
            if (not ident.job_id or ident.harness != "rackstatus" or
                    ident.workload not in TERMINAL or
                    not is_terminal(path, ident.workload)):
                stats["nonterminal"] += 1
                continue
            previous = state.get(str(path))
            previous_blob = previous.get("blob_ref", "")
            if (previous.get("inode") == st.st_ino and
                    previous.get("size") == st.st_size and
                    previous.get("mtime_ns") == st.st_mtime_ns and
                    previous_blob and (ri.LAKE_ROOT / previous_blob).is_file()):
                stats["unchanged"] += 1
                continue
            sha, size = ri.sha256_file(str(path))
            if size != st.st_size:
                stats["unsettled"] += 1
                continue
            blob_ref, blob_encoding, blob_bytes = ri.store_blob(
                str(path), sha, size)
            rows.append(manifest_row(
                path, st, ident, sha, blob_ref, blob_encoding, blob_bytes))
            pending_state.append((str(path), {
                "inode": st.st_ino,
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
                "sha256": sha,
                "blob_ref": blob_ref,
                "blob_encoding": blob_encoding,
                "blob_bytes": blob_bytes,
                "run_id": ident.run_id,
                "job_id": ident.job_id,
                "workload": ident.workload,
            }))
        except Exception as exc:  # fail one file, never the complete lane
            stats["errors"] += 1
            print(f"hot manifest error {path}: {type(exc).__name__}: {exc}")
    if rows:
        writer.write(rows)
        for path, record in pending_state:
            state.put(path, record)
        state.save()
        stats["captured"] = len(rows)
    print(json.dumps(stats, sort_keys=True))
    return stats


if __name__ == "__main__":
    result = run_once()
    raise SystemExit(1 if result["errors"] else 0)
