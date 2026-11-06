#!/usr/bin/env python3
"""
runlog_parse.py — pure-python (stdlib only) parsers for the IREN_MKZ validation
log lane. No pyarrow import here on purpose: the parser is unit-testable and
runnable on the host, where pyarrow is absent.

Two jobs:

  1. `identify(path)`  -> RunIdentity: derive run_id / harness / workload /
     unit / job_id / stream / rank from the FILE PATH, because nothing in the
     validation suite writes a run identifier into the file (see recon §4d).

  2. `LineParser.parse(line, lineno)` -> dict of typed fields for one row of
     `run_logs`: severity, msg_class, rank/pid/device/host, kv, xid.

Deliberate correctness choices (each fixes a defect found in the existing code):

  * NCCL sweep tables are parsed by locating `busbw` in the `#...busbw...`
    HEADER line, never by a fixed column index. Both dialects occur on this
    cluster: 13 columns for reduction/rooted collectives and 11 for
    all_gather/alltoall/sendrecv. `nccl_parse.inc.sh` hardcodes `$8`, which
    silently reports 0 for the 11-column variants — that looks exactly like a
    fabric failure. `lib/llmb.sh::nccl_peak_busbw` already does it by header;
    this module matches llmb.sh, not nccl_parse.inc.sh.

  * Xid is parsed with `Xid\\s*(?:\\([^)]*\\))?\\s*:\\s*(\\d+)`. The existing
    `lakewriter._log_row` takes the first all-digit token after a colon split,
    so `NVRM: Xid (PCI:0000:01:00): 79` records xid=0 (from the BDF) instead of
    79.

  * Suite timestamps are `%Y-%m-%dT%H:%M:%S%z` with NO colon in the offset
    (`2026-07-26T23:58:49+0000`). Parsed with an explicit strptime format.

  * When a line carries no timestamp (the overwhelming majority of NCCL output),
    ts is synthesized from the file mtime plus a per-line microsecond offset and
    `ts_exact` is set False. Ordering is preserved; precision is never faked.
"""
from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

INGEST_TOOL = "nvis-lake-logs"
INGEST_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# msg_class taxonomy
# ---------------------------------------------------------------------------
MSG_CLASSES = (
    "NCCL_RESULT", "NCCL_SUMMARY", "NCCL_HEADER", "NCCL_WARN", "NCCL_TOPO",
    "TRANSPORT", "NCCL_INFO", "IB_QP_FAIL", "CONN_TIMEOUT", "TEST_TIMEOUT",
    "GPU_XID", "SLURM_ERROR", "MPI", "HARNESS", "NEMO_STEP", "DCGM",
    "RESULT_VERDICT", "SUMMARY_TSV",
)

STREAMS = (
    "sbatch_stdout", "nccl_rank_debug", "job_step_stdout", "round_log",
    "summary_tsv", "orchestrator", "node_health", "llmb_stdout", "result_file",
    "unknown",
)

# ---------------------------------------------------------------------------
# run identity from path
# ---------------------------------------------------------------------------

# rack-status dashboard-discoverable NCCL/NEMO stdout:
#   <user>-NCCL-1Rack-<rack>-<N>N-<job>.txt
_RE_DASH = re.compile(
    r"^(?P<user>[^-]+)-(?P<kind>NCCL|NEMO)-(?P<scope>\d*Rack|\w+)-"
    r"(?P<unit>.+?)-(?P<nnodes>\d+)N-(?P<job>\d+)\.(txt|out|log)$")
# cross-rack mpirun stdout:   nccl-mpi_<label>_<job>.out
_RE_MPI = re.compile(r"^nccl-mpi_(?P<unit>.+)_(?P<job>\d+)\.(out|txt|log)$")
# llmb-run NCCL launched from rack-status: llmb-nccl_<label>_<job>.out
_RE_LLMBNCCL = re.compile(r"^llmb-nccl_(?P<unit>.+)_(?P<job>\d+)\.(out|txt|log)$")
# NVFTP five-collective Rack Status stdout:
#   .../SU12/rack02/singleRackNCCL/nvftp-nccl-five-collective-6979.out
_RE_NVFTP_NCCL = re.compile(
    r"^nvftp-nccl-five-collective-(?P<job>\d+)\.(out|txt|log)$")
# Standard Rack Status NeMo stdout:
#   .../SU12/rack21/singleRackNeMo/nemo-26.04.01-8768.out
_RE_NVFTP_NEMO = re.compile(
    r"^nemo-26\.04\.01-(?P<job>\d+)\.(out|txt|log)$")
# Exact-rack MNUberGEMM stdout:
#   .../SU9/rack04/multiNodeMNU/mnubergemm-26.03-v1.17-g001-24646.out
_RE_NVFTP_MNU = re.compile(
    r"^mnubergemm-.+-(?P<job>\d+)\.(out|txt|log)$")
# Stage-1 acceptance rounds: rounds_<UTCSTAMP>/round_<r>.log  (+ summary.tsv)
_RE_ROUND = re.compile(r"^round_(?P<round>\d+)\.log$")
_RE_ROUNDSDIR = re.compile(r"^rounds_(?P<stamp>\d{8}T\d{6}Z)$")
# llmb per-rank NCCL debug: .../rank<N>/nccl_debug_file.<host>.<pid>.txt
_RE_RANKDIR = re.compile(r"^rank(?P<rank>\d+)$")
_RE_RANKFILE = re.compile(
    r"^nccl_debug_file\.(?P<host>[^.]+)\.(?P<pid>\d+)\.txt$")
# llmb experiment dir: experiments/<exp>_<jobid>/
_RE_EXPDIR = re.compile(r"^(?P<exp>.+)_(?P<job>\d+)$")
_RE_JOBDIR = re.compile(r"^job-(?P<job>\d+)$")
# llmb per-node result file: <RESULTS_DIR>/<node>/<workload>[-run<N>].txt
_RE_RESULT = re.compile(r"^(?P<wl>[a-z0-9_]+?)(?:-run(?P<seq>\d+))?\.txt$")

# A 10-digit "jobid" that is really an epoch (nccl_fullrack_rounds.sh substitutes
# an epoch for the jobid). Anything at/after 2020-09-13 is an epoch, not a jobid.
_EPOCH_FLOOR = 1_600_000_000


def _job_key(job: str | int | None) -> str:
    if job in (None, ""):
        return ""
    try:
        n = int(job)
    except (TypeError, ValueError):
        return f"j{job}"
    return f"t{n}" if n >= _EPOCH_FLOOR else f"j{n}"


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(s: str) -> str:
    return _SAFE.sub("_", (s or "")).strip("_") or "unknown"


def _nvis_rack_from_path(parts: list[str]) -> str:
    """Return the canonical 16K rack hostname encoded by SU/rack path parts."""
    su = rack = None
    for segment in parts:
        match = re.fullmatch(r"SU(\d{1,2})", segment, re.IGNORECASE)
        if match:
            su = int(match.group(1))
        match = re.fullmatch(r"rack(\d{1,2})", segment, re.IGNORECASE)
        if match:
            rack = int(match.group(1))
    if su is None or rack is None or not (1 <= su <= 14):
        return ""
    if su <= 11:
        dh, letter = "dh02", chr(ord("a") + su - 1)
    else:
        dh, letter = "dh01", chr(ord("a") + su - 12)
    return f"example50-{dh}-{letter}{rack:02d}"


def _nvis_su_from_path(parts: list[str]) -> str:
    """Return the canonical SU label encoded by an ``SU<n>`` path segment."""
    for segment in parts:
        match = re.fullmatch(r"SU(\d{1,2})", segment, re.IGNORECASE)
        if match and 1 <= int(match.group(1)) <= 14:
            return f"SU{int(match.group(1))}"
    return ""


@dataclass
class RunIdentity:
    run_id: str = ""
    unit_key: str = ""
    job_id: str = ""
    activity_id: str = ""       # Rack Status durable activity UUID, when resolvable
    su: str = ""                # Canonical SU label when encoded by the source path
    harness: str = "unknown"     # llmb|rackstatus|sbatch|orchestrator|manual|unknown
    workload: str = "unknown"
    unit_kind: str = "unknown"   # node|rack|group|cluster
    unit_id: str = "unknown"
    run_seq: int = 1
    stream: str = "unknown"
    rank: int | None = None
    host: str = ""
    pid: int | None = None
    round: int | None = None
    node: str = ""
    fixture: bool = False

    def as_row(self) -> dict:
        return {
            "run_id": self.run_id, "unit_key": self.unit_key,
            "job_id": self.job_id, "activity_id": self.activity_id,
            "su": self.su,
            "harness": self.harness,
            "workload": self.workload, "stream": self.stream,
            "rank": self.rank, "host": self.host, "pid": self.pid,
            "round": self.round, "node": self.node,
        }


def identify(path: str, cluster: str = "IREN_MKZ", fixture: bool = False,
             mtime: float | None = None) -> RunIdentity:
    """Derive run identity + stream from an absolute log path.

    Falls back to a deterministic, non-colliding identity rather than dropping
    the file: an unrecognised log is still evidence ("blank never means
    healthy"). The fallback job_key is the file mtime epoch so re-ingesting the
    same unchanged file yields the same run_id.
    """
    p = os.path.abspath(path)
    base = os.path.basename(p)
    parts = p.split(os.sep)
    parent = parts[-2] if len(parts) >= 2 else ""
    gparent = parts[-3] if len(parts) >= 3 else ""

    ri = RunIdentity(fixture=fixture)

    # -- per-rank NCCL debug file -------------------------------------------
    m = _RE_RANKFILE.match(base)
    if m:
        ri.stream = "nccl_rank_debug"
        ri.host = m.group("host")
        ri.pid = int(m.group("pid"))
        ri.node = ri.host
        mr = _RE_RANKDIR.match(parent)
        if mr:
            ri.rank = int(mr.group("rank"))
        ri.harness = "llmb"
        ri.workload = "nccl_single"

    # -- Stage-1 acceptance rounds ------------------------------------------
    elif _RE_ROUND.match(base) or base == "summary.tsv":
        mr = _RE_ROUND.match(base)
        ri.stream = "round_log" if mr else "summary_tsv"
        ri.round = int(mr.group("round")) if mr else None
        ri.harness = "rackstatus"
        if "singleRackNCCL" in parts:
            ri.workload = "nccl_five_collective"
            ri.unit_kind = "rack"
            ri.unit_id = _nvis_rack_from_path(parts) or "unknown"
        else:
            ri.workload = "nccl_rounds"

    # -- llmb job step stdout -----------------------------------------------
    elif base == "job_step_stdout.txt":
        ri.stream = "job_step_stdout"
        ri.harness = "llmb"
        ri.workload = "nccl_single"

    # -- orchestrator / harness audit trail ---------------------------------
    elif base in ("aat.log", "orchestrator.log"):
        ri.stream = "orchestrator"
        ri.harness = "orchestrator"
        ri.workload = "orchestrator"
        ri.unit_kind = "cluster"
        ri.unit_id = cluster

    # -- rack-status dashboard stdout ---------------------------------------
    elif _RE_DASH.match(base):
        m = _RE_DASH.match(base)
        ri.stream = "sbatch_stdout"
        ri.harness = "rackstatus"
        ri.workload = ("nccl_allreduce" if m.group("kind") == "NCCL"
                       else "nemo_single")
        ri.unit_kind = "rack"
        ri.unit_id = m.group("unit")
        ri.job_id = m.group("job")

    elif _RE_MPI.match(base):
        m = _RE_MPI.match(base)
        ri.stream = "sbatch_stdout"
        ri.harness = "rackstatus"
        ri.workload = "nccl_multi"
        ri.unit_kind = "group"
        ri.unit_id = m.group("unit")
        ri.job_id = m.group("job")

    elif _RE_LLMBNCCL.match(base):
        m = _RE_LLMBNCCL.match(base)
        ri.stream = "llmb_stdout"
        ri.harness = "llmb"
        ri.workload = "nccl_single"
        ri.unit_kind = "rack"
        ri.unit_id = m.group("unit")
        ri.job_id = m.group("job")

    elif _RE_NVFTP_NCCL.match(base):
        m = _RE_NVFTP_NCCL.match(base)
        ri.stream = "sbatch_stdout"
        ri.harness = "rackstatus"
        ri.workload = "nccl_five_collective"
        ri.unit_kind = "rack"
        ri.unit_id = _nvis_rack_from_path(parts) or "unknown"
        ri.job_id = m.group("job")

    elif any(kind in parts for kind in ("singleRackNeMo", "multiNodeNeMo")) \
            and _RE_NVFTP_NEMO.match(base):
        m = _RE_NVFTP_NEMO.match(base)
        ri.stream = "sbatch_stdout"
        ri.harness = "rackstatus"
        ri.workload = "nemo_single"
        ri.unit_kind = "rack"
        ri.unit_id = _nvis_rack_from_path(parts) or "unknown"
        ri.job_id = m.group("job")

    elif "multiNodeMNU" in parts and _RE_NVFTP_MNU.match(base):
        m = _RE_NVFTP_MNU.match(base)
        ri.stream = "sbatch_stdout"
        ri.harness = "rackstatus"
        ri.workload = "mnubergemm"
        ri.unit_kind = "rack"
        ri.unit_id = _nvis_rack_from_path(parts) or "unknown"
        ri.job_id = m.group("job")

    # -- NVFTP five-collective per-test live/raw logs -----------------------
    # These live below singleRackNCCL/job-<id>/ and must join the same rack/job
    # identity as the sbatch stdout and summary.  Leaving them to the generic
    # fallback creates a second unknown-unknown run for the same Slurm job.
    elif "singleRackNCCL" in parts and any(_RE_JOBDIR.match(seg) for seg in parts):
        ri.harness = "rackstatus"
        ri.workload = "nccl_five_collective"
        ri.unit_kind = "rack"
        ri.unit_id = _nvis_rack_from_path(parts) or "unknown"
        if base.endswith("-nccl-info.live.log"):
            ri.stream = "nccl_rank_debug"
        elif base.endswith(".live.log") or base.endswith(".raw"):
            ri.stream = "job_step_stdout"
        else:
            ri.stream = "unknown"

    # -- llmb per-node result file: <RESULTS_DIR>/<node>/<workload>.txt ------
    elif _RE_RESULT.match(base) and parent and gparent.endswith("results"):
        m = _RE_RESULT.match(base)
        ri.stream = "result_file"
        ri.harness = "llmb"
        ri.workload = m.group("wl")
        ri.unit_kind = "node"
        ri.unit_id = parent
        ri.node = parent
        ri.run_seq = int(m.group("seq") or 1)

    else:
        ri.stream = "unknown"

    # -- climb the path for a jobid / rounds stamp / rack when still missing --
    if not ri.job_id:
        for seg in reversed(parts[:-1]):
            mj = _RE_JOBDIR.match(seg)
            if mj:
                ri.job_id = mj.group("job")
                break
            mr = _RE_ROUNDSDIR.match(seg)
            if mr:
                try:
                    ri.job_id = str(int(datetime.strptime(
                        mr.group("stamp"), "%Y%m%dT%H%M%SZ"
                    ).replace(tzinfo=timezone.utc).timestamp()))
                except ValueError:
                    pass
                break
            me = _RE_EXPDIR.match(seg)
            if me and me.group("job").isdigit() and len(me.group("job")) >= 3:
                ri.job_id = me.group("job")
                if ri.unit_id == "unknown":
                    ri.unit_id = _safe(me.group("exp"))
                break

    if ri.unit_id == "unknown" and ri.node:
        ri.unit_id = ri.node
        ri.unit_kind = "node"
    if ri.unit_id == "unknown":
        ri.unit_id = _safe(parent or "root")
    if ri.unit_kind == "rack":
        ri.su = _nvis_su_from_path(parts)

    jk = _job_key(ri.job_id) or f"t{int(mtime or os.path.getmtime(p) if os.path.exists(p) else 0)}"
    seq = f"-r{ri.run_seq:02d}" if ri.run_seq and ri.run_seq > 1 else ""
    prefix = "FIXTURE-" if fixture else ""
    ri.run_id = (f"{prefix}{cluster}-{ri.harness}-{_safe(ri.workload)}-"
                 f"{_safe(ri.unit_id)}{seq}-{jk}")
    # unit_key is stable across MAX_ATTEMPTS retries (no jobid in it).
    ri.unit_key = (f"{prefix}{cluster}-{_safe(ri.workload)}-"
                   f"{_safe(ri.unit_id)}-r{ri.run_seq:02d}")
    return ri


class ActivityResolver:
    """Resolve Slurm/file identities to the durable Rack Status activity UUID.

    Scheduler task references are authoritative.  A running activity may not
    have its scheduler reference until the launcher exits and its stdout is
    reconciled, so a second, deliberately narrow fallback matches a source
    file below the activity's exact ``log_dir`` while that activity is live.
    """

    def __init__(self, records: dict | None = None):
        self.by_job: dict[str, str] = {}
        self.live_by_log_dir: list[tuple[float, str, str]] = []
        for key, raw in (records or {}).items():
            if not isinstance(raw, dict):
                continue
            activity_id = str(raw.get("activity_id") or key or "").strip()
            if not activity_id:
                continue
            refs: list[str] = []
            for value in (raw.get("scheduler_ref"), raw.get("scheduler_job_id")):
                if value not in (None, ""):
                    refs.append(str(value).strip())
            scheduler_job_ids = raw.get("scheduler_job_ids")
            if isinstance(scheduler_job_ids, str):
                refs.extend(item.strip() for item in scheduler_job_ids.split(","))
            for task in raw.get("tasks") or []:
                if isinstance(task, dict):
                    value = task.get("scheduler_ref") or task.get("scheduler_job_id")
                    if value not in (None, ""):
                        refs.append(str(value).strip())
            for ref in refs:
                # Array/step suffixes still belong to the parent allocation.
                match = re.match(r"^(\d+)", ref)
                if match:
                    self.by_job[match.group(1)] = activity_id

            phase = str(raw.get("phase") or "").strip().lower()
            log_dir = str(raw.get("log_dir") or "").rstrip("/")
            if phase not in {"starting", "pending", "running"} or not log_dir:
                continue
            created = self._timestamp(raw.get("created_at"))
            self.live_by_log_dir.append((created, log_dir, activity_id))
        self.live_by_log_dir.sort(reverse=True)

    @staticmethod
    def _timestamp(value) -> float:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def from_file(cls, path: str | None) -> "ActivityResolver":
        if not path:
            return cls()
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return cls()
        return cls(data if isinstance(data, dict) else {})

    @staticmethod
    def _host_path(path: str) -> str:
        prefix = "/logs/rackstatus"
        if path == prefix or path.startswith(prefix + "/"):
            return "/cluster/OVA/logs" + path[len(prefix):]
        return path

    def resolve(self, identity: RunIdentity, path: str, mtime: float) -> str:
        if identity.job_id and identity.job_id in self.by_job:
            return self.by_job[identity.job_id]
        host_path = self._host_path(os.path.abspath(path))
        for created, log_dir, activity_id in self.live_by_log_dir:
            if created <= mtime and (host_path == log_dir or host_path.startswith(log_dir + "/")):
                return activity_id
        return ""


# ---------------------------------------------------------------------------
# line parsing
# ---------------------------------------------------------------------------

# <host>:<pid>:<tid> [<dev>] <rest>
_RE_NCCL_PREFIX = re.compile(
    r"^(?P<host>[A-Za-z0-9_.\-]+):(?P<pid>\d+):(?P<tid>\d+)\s+"
    r"\[(?P<dev>\d+)\]\s+(?P<rest>.*)$")
_RE_NCCL_LEVEL = re.compile(
    r"^(?:(?P<src>[\w./+-]+:\d+)\s+)?NCCL\s+(?P<lvl>WARN|INFO|TRACE|ABORT|ERROR)\s+"
    r"(?P<msg>.*)$")
# "# Rank  0 Group  0 Pid 12345 on <host> device  0 [0x1b] NVIDIA GB300"
_RE_USING_DEV = re.compile(
    r"^#\s+Rank\s+(?P<rank>\d+)\s+Group\s+(?P<group>\d+)\s+Pid\s+(?P<pid>\d+)\s+"
    r"on\s+(?P<host>\S+)\s+device\s+(?P<dev>\d+)")
_RE_XID = re.compile(r"Xid\s*(?:\([^)]*\))?\s*:\s*(\d+)")
_RE_KV = re.compile(r"([A-Za-z_][A-Za-z0-9_./]*)=([^\s]+)")
_RE_ROUND_BANNER = re.compile(r"=====\s*\w+\s+round\s+(?P<r>\d+)/(?P<n>\d+)\s*=====")
_RE_ROUND_RESULT = re.compile(r":\s*round\s+(?P<r>\d+)/(?P<n>\d+)\s+(?P<st>OK|FAILED)")
_RE_TRANSPORT = re.compile(
    r"\b(?:via\s+)?(NET/(?:IB|Socket|SPCX|[A-Za-z0-9_]+)|NVLS|NVLink|P2P/\w+|"
    r"CollNet|SHARP)\b")
_RE_COMMINIT = re.compile(
    r"comm\s+(?P<comm>0x[0-9a-f]+)\s+rank\s+(?P<rank>\d+)\s+nranks\s+(?P<nranks>\d+)"
    r"(?:\s+cudaDev\s+(?P<dev>\d+))?")
_RE_NEMO_STEP = re.compile(
    r"(?:Step\s+Time\D+(?P<step>[\d.]+)).*?(?:MODEL_TFLOP/s/GPU\D+(?P<tf>[\d.]+))",
    re.IGNORECASE)
_RE_ITER = re.compile(r"\biteration\s+(?P<cur>\d+)\s*/\s*(?P<tot>\d+)")

# timestamps
_RE_TS_BRACKET_ISO = re.compile(
    r"^\[?(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?)\]?")
_RE_TS_SUITE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}")


def parse_ts(tok: str) -> int | None:
    """Parse a timestamp token to epoch microseconds (UTC). None if unparseable."""
    tok = tok.strip()
    if not tok:
        return None
    # Suite format: 2026-07-26T23:58:49+0000  (offset has NO colon; explicit
    # strptime because datetime.fromisoformat rejects it before Python 3.11).
    if _RE_TS_SUITE.fullmatch(tok):
        try:
            dt = datetime.strptime(tok, "%Y-%m-%dT%H:%M:%S%z")
            return int(dt.timestamp() * 1_000_000)
        except ValueError:
            return None
    t = tok.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(t, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1_000_000)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000)
    except ValueError:
        return None


class NcclTableHeader:
    """Column map for an nccl-tests sweep table, derived from the header LINE.

    NEVER index by position. Both dialects occur on this cluster:
      13-col: size count type redop root | time algbw busbw #wrong | (in-place x4)
      11-col: size count type            | time algbw busbw #wrong | (in-place x4)
    """

    __slots__ = ("cols", "ncols", "busbw_idx", "algbw_idx", "time_idx",
                 "wrong_idx")

    def __init__(self, header_line: str):
        toks = header_line.lstrip("#").split()
        self.cols = toks
        self.ncols = len(toks)
        self.busbw_idx = [i for i, t in enumerate(toks) if t == "busbw"]
        self.algbw_idx = [i for i, t in enumerate(toks) if t == "algbw"]
        self.time_idx = [i for i, t in enumerate(toks) if t == "time"]
        self.wrong_idx = [i for i, t in enumerate(toks) if t.lstrip("#") == "wrong"]

    def valid(self) -> bool:
        return len(self.busbw_idx) >= 1 and self.ncols in (11, 13)

    def parse_row(self, line: str) -> dict | None:
        f = line.split()
        if len(f) != self.ncols or not f[0].isdigit():
            return None
        out: dict[str, str] = {}
        for name, idx in (("size_bytes", 0), ("count_elems", 1), ("dtype", 2)):
            out[name] = f[idx]
        if self.ncols == 13:
            out["redop"] = f[3]
            out["root"] = f[4]
        for tag, idxs in (("time_us", self.time_idx), ("algbw_gbps", self.algbw_idx),
                          ("busbw_gbps", self.busbw_idx), ("wrong", self.wrong_idx)):
            for n, i in enumerate(idxs[:2]):
                if i < len(f):
                    out[("oop_" if n == 0 else "ip_") + tag] = f[i]
        return out


@dataclass
class LineParser:
    """Stateful, single-file line parser. State = the current sweep header, the
    rank<->(host,pid) map from `# Using devices`, and the current round."""

    identity: RunIdentity
    header: NcclTableHeader | None = None
    collective: str | None = None
    round: int | None = None
    rank_by_pid: dict[tuple[str, int], tuple[int, int]] = field(default_factory=dict)
    nranks: int | None = None
    nccl_version: str | None = None

    def __post_init__(self):
        # round_<r>.log carries its round in the FILENAME and emits no banner;
        # seed from the path so every line in the file is attributed correctly.
        if self.round is None and self.identity.round is not None:
            self.round = self.identity.round

    def parse(self, line: str, lineno: int) -> dict:
        s = line.rstrip("\n").rstrip("\r")
        row: dict = {
            "ts_us": None, "ts_exact": False, "severity": None,
            "msg_class": None, "rank": self.identity.rank,
            "local_rank": None, "pid": self.identity.pid, "device": None,
            "host": self.identity.host or None, "round": self.round,
            "xid": None, "kv": {},
        }
        kv = row["kv"]

        # ---- explicit timestamp -------------------------------------------
        m = _RE_TS_BRACKET_ISO.match(s)
        if m:
            us = parse_ts(m.group("ts"))
            if us is not None:
                row["ts_us"] = us
                row["ts_exact"] = True
        else:
            m2 = _RE_TS_SUITE.search(s)
            if m2:
                us = parse_ts(m2.group(0))
                if us is not None:
                    row["ts_us"] = us
                    row["ts_exact"] = True

        # ---- orchestrator: "2026-07-26 23:58:49 [INFO] tag: msg" ----------
        if self.identity.stream == "orchestrator":
            mo = re.match(r"^\S+ \S+ \[(?P<lvl>[A-Z]+)\]\s+(?P<tag>[^:]+):", s)
            if mo:
                row["severity"] = mo.group("lvl")
                kv["tag"] = mo.group("tag")
                row["msg_class"] = "HARNESS"

        # ---- NCCL rank-prefixed line --------------------------------------
        mp = _RE_NCCL_PREFIX.match(s)
        if mp:
            row["host"] = mp.group("host")
            row["pid"] = int(mp.group("pid"))
            row["device"] = int(mp.group("dev"))
            row["local_rank"] = int(mp.group("dev"))
            hit = self.rank_by_pid.get((mp.group("host"), int(mp.group("pid"))))
            if hit and row["rank"] is None:
                row["rank"] = hit[0]
            ml = _RE_NCCL_LEVEL.match(mp.group("rest"))
            if ml:
                lvl = ml.group("lvl")
                row["severity"] = lvl
                if ml.group("src"):
                    kv["nccl_src"] = ml.group("src")
                body = ml.group("msg")
                if lvl == "WARN":
                    row["msg_class"] = "NCCL_WARN"
                elif re.search(r"\b(?:graph|ring|tree|channel|topo|NVLS tree|"
                               r"Connected all|Trees|Channels)\b", body, re.I):
                    row["msg_class"] = "NCCL_TOPO"
                else:
                    row["msg_class"] = "NCCL_INFO"
                mt = _RE_TRANSPORT.search(body)
                if mt:
                    kv["transport"] = mt.group(1)
                    if row["msg_class"] == "NCCL_INFO":
                        row["msg_class"] = "TRANSPORT"
                mv = re.search(r"NCCL version\s+(\S+)", body)
                if mv:
                    self.nccl_version = mv.group(1)
                    kv["nccl_version"] = mv.group(1)
                mc = _RE_COMMINIT.search(body)
                if mc:
                    kv["comm"] = mc.group("comm")
                    kv["nranks"] = mc.group("nranks")
                    self.nranks = int(mc.group("nranks"))
                    if row["rank"] is None:
                        row["rank"] = int(mc.group("rank"))

        # ---- nccl-tests sweep output --------------------------------------
        if s.startswith("#"):
            if "busbw" in s and "size" in s:
                h = NcclTableHeader(s)
                if h.valid():
                    self.header = h
                row["msg_class"] = row["msg_class"] or "NCCL_HEADER"
            elif s.startswith("# Collective test starting:"):
                self.collective = s.split(":", 1)[1].strip()
                kv["collective"] = self.collective
                row["msg_class"] = "NCCL_HEADER"
            elif s.startswith("# Collective test concluded:"):
                kv["collective"] = s.split(":", 1)[1].strip()
                self.collective = None
                row["msg_class"] = "NCCL_HEADER"
            elif "Out of bounds values" in s:
                row["msg_class"] = "NCCL_SUMMARY"
                mo = re.search(r":\s*(\d+)\s*(OK|FAILED)", s)
                if mo:
                    kv["oob_count"] = mo.group(1)
                    kv["oob_status"] = mo.group(2)
                    if mo.group(2) == "FAILED":
                        row["severity"] = "ERROR"
            elif "Avg bus bandwidth" in s:
                row["msg_class"] = "NCCL_SUMMARY"
                mo = re.search(r":\s*([\d.]+)", s)
                if mo:
                    kv["avg_busbw_gbps"] = mo.group(1)
            else:
                md = _RE_USING_DEV.match(s)
                if md:
                    self.rank_by_pid[(md.group("host"), int(md.group("pid")))] = (
                        int(md.group("rank")), int(md.group("dev")))
                    row["rank"] = int(md.group("rank"))
                    row["host"] = md.group("host")
                    row["pid"] = int(md.group("pid"))
                    row["device"] = int(md.group("dev"))
                    row["msg_class"] = "NCCL_HEADER"
                elif re.match(r"^#\s*(nThread|nccl-tests version|Using devices)", s):
                    row["msg_class"] = "NCCL_HEADER"
                    mn = re.search(r"nGpus\s+(\d+)", s)
                    if mn:
                        kv["ngpus_per_proc"] = mn.group(1)
                    for k in ("minBytes", "maxBytes", "iters", "warmup iters",
                              "validation", "graph"):
                        mk = re.search(re.escape(k) + r":?\s+(\S+)", s)
                        if mk:
                            kv[k.replace(" ", "_")] = mk.group(1)
                elif self.header is not None or self.collective is not None:
                    # Only claim '#' lines as NCCL_HEADER while we are INSIDE a
                    # sweep block. Otherwise a shell comment in a result file
                    # (`# auto-action-trigger (llmb-run) result`) would be
                    # mislabelled as nccl-tests output.
                    row["msg_class"] = row["msg_class"] or "NCCL_HEADER"
        elif self.header is not None and s[:1].isspace() or (
                self.header is not None and s[:1].isdigit()):
            parsed = self.header.parse_row(s)
            if parsed:
                row["msg_class"] = "NCCL_RESULT"
                kv.update(parsed)
                if self.collective:
                    kv["collective"] = self.collective
                elif self.identity.workload.startswith("nccl"):
                    # standalone launcher emits no "starting:" marker; every data
                    # row is all_reduce (matches nccl_parse.inc.sh's fallback).
                    kv["collective"] = "all_reduce_perf"

        # ---- harness preamble / round banners ------------------------------
        if row["msg_class"] is None or row["msg_class"] == "NCCL_HEADER":
            mb = _RE_ROUND_BANNER.search(s)
            if mb:
                self.round = int(mb.group("r"))
                row["round"] = self.round
                kv["rounds_total"] = mb.group("n")
                row["msg_class"] = "HARNESS"
            mrr = _RE_ROUND_RESULT.search(s)
            if mrr:
                row["round"] = int(mrr.group("r"))
                kv["round_status"] = mrr.group("st")
                row["msg_class"] = "HARNESS"
                if mrr.group("st") == "FAILED":
                    row["severity"] = "ERROR"

        if row["msg_class"] is None and re.match(
                r"^\w[\w.-]*:\s+\S+=", s) and "=" in s:
            # "nccl_allreduce: nodes=18 np=72 gpus/node=4 sizes=8..1G rounds=1"
            row["msg_class"] = "HARNESS"

        # ---- failure signatures --------------------------------------------
        low = s.lower()
        if "ibv_modify_qp failed" in low or "ibv_reg_mr" in low or \
                re.search(r"\bibv_\w+ failed", low):
            row["msg_class"] = "IB_QP_FAIL"
            row["severity"] = row["severity"] or "ERROR"
        elif "connection timed out" in low or "connection closed by remote peer" in low \
                or "unhandled system error" in low or "socket timeout" in low:
            row["msg_class"] = "CONN_TIMEOUT"
            row["severity"] = row["severity"] or "ERROR"
        elif "test timeout" in low or "ncclcommabort" in low:
            row["msg_class"] = "TEST_TIMEOUT"
            row["severity"] = row["severity"] or "ERROR"
        elif "xid" in low and ("nvrm" in low or "xid (" in low):
            mx = _RE_XID.search(s)
            if mx:
                row["xid"] = int(mx.group(1))
                row["msg_class"] = "GPU_XID"
                row["severity"] = "ERROR"
        elif re.search(r"^(srun|slurmstepd|sbatch):\s*error:", s) or \
                re.search(r"error:.*(Exited|SIGNAL|CANCELLED|NODE_FAIL)", s):
            row["msg_class"] = "SLURM_ERROR"
            row["severity"] = "ERROR"
        elif re.match(r"^(?:\[)?(?:mpirun|orterun|prterun|ORTE|PMIX|PRTE)\b", s) or \
                "--------------------------------------------------------------------------" == s.strip():
            row["msg_class"] = row["msg_class"] or "MPI"

        # ---- NEMO / pretrain step lines -------------------------------------
        mn = _RE_NEMO_STEP.search(s)
        if mn:
            row["msg_class"] = "NEMO_STEP"
            kv["step_time_s"] = mn.group("step")
            kv["tflops_per_gpu"] = mn.group("tf")
        mi = _RE_ITER.search(s)
        if mi and row["msg_class"] in (None, "NEMO_STEP"):
            row["msg_class"] = "NEMO_STEP"
            kv["iteration"] = mi.group("cur")
            kv["iterations_total"] = mi.group("tot")

        # ---- dcgm diag / result verdicts -------------------------------------
        if self.identity.stream == "result_file":
            if s.strip() in ("DONE", "FAIL"):
                row["msg_class"] = "RESULT_VERDICT"
                kv["verdict"] = s.strip()
                row["severity"] = "ERROR" if s.strip() == "FAIL" else "INFO"
            elif re.match(r"^[a-z_]+=", s):
                k, v = s.split("=", 1)
                kv[k] = v
                row["msg_class"] = row["msg_class"] or "HARNESS"
        if row["msg_class"] is None and re.search(
                r"\b(dcgmi|Diagnostic|Deployment|GPU Memory|Pulse Test)\b", s):
            row["msg_class"] = "DCGM"

        if self.identity.stream == "summary_tsv" and "\t" in s:
            row["msg_class"] = "SUMMARY_TSV"
            f = s.split("\t")
            if len(f) >= 4 and f[0].isdigit():
                kv.update({"round": f[0], "status": f[1],
                           "max_wrong": f[2], "peak_busbw_gbps": f[3]})
                row["round"] = int(f[0])

        # ---- severity backstop ------------------------------------------------
        if row["severity"] is None:
            if re.search(r"\b(ERROR|FATAL|CRITICAL)\b", s):
                row["severity"] = "ERROR"
            elif re.search(r"\b(WARN|WARNING)\b", s):
                row["severity"] = "WARN"

        # ---- generic k=v harvest for harness lines ------------------------------
        if row["msg_class"] == "HARNESS":
            for k, v in _RE_KV.findall(s):
                kv.setdefault(k, v)

        if self.nccl_version and "nccl_version" not in kv:
            kv["nccl_version"] = self.nccl_version
        return row


# ---------------------------------------------------------------------------
# Loki tee policy — what is "recent + searchable" vs "durable raw archive".
# ---------------------------------------------------------------------------
# Loki gets the OPERATOR-RELEVANT subset: everything except the per-rank
# NCCL_DEBUG=INFO firehose, plus the WARN/ERROR/result lines from inside it.
# Parquet gets EVERY line plus the byte-exact original file. Rationale is in
# the module docstring of log_collector.py.
LOKI_ALWAYS_CLASSES = {
    "NCCL_WARN", "NCCL_RESULT", "NCCL_SUMMARY", "IB_QP_FAIL", "CONN_TIMEOUT",
    "TEST_TIMEOUT", "GPU_XID", "SLURM_ERROR", "HARNESS", "NEMO_STEP",
    "RESULT_VERDICT", "SUMMARY_TSV", "TRANSPORT",
}


def loki_worthy(stream: str, row: dict) -> bool:
    if row.get("severity") in ("WARN", "ERROR", "ABORT", "FATAL"):
        return True
    if row.get("msg_class") in LOKI_ALWAYS_CLASSES:
        return True
    # The rank-debug firehose is archive-only unless it matched above.
    return stream != "nccl_rank_debug"
