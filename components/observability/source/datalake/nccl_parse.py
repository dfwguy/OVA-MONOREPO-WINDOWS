#!/usr/bin/env python3
"""
nccl_parse.py — pure-stdlib parser for nccl-tests sweep output
(`all_reduce_perf`, `all_reduce_perf_mpi`, `all_gather_perf`, …).

NO pyarrow / no third-party imports on purpose: this module must be unit-testable
on the ObsVM host, where pyarrow is not installed. The Arrow/Parquet side lives in
nccl_ingest.py, which imports this.

WHAT IT UNDERSTANDS
-------------------
Both nccl-tests header dialects, located FROM THE HEADER LINE, never by fixed
column index:

  13-col (reduction + rooted collectives: all_reduce, reduce_scatter, reduce, broadcast)
    size count type redop root | time algbw busbw #wrong | time algbw busbw #wrong
  11-col (all_gather, alltoall, sendrecv — no redop, no root)
    size count type            | time algbw busbw #wrong | time algbw busbw #wrong

`lib/llmb.sh::nccl_peak_busbw` documents exactly why this matters: hardcoding $8
(as nvis-rack-status-v3/bin/scripts/nccl_parse.inc.sh does) "silently reports 0
for the 11-column variants" — an all_gather run then looks identical to a dead
fabric. We inherit llmb's header-driven behaviour, not rack-status's $8.

It also lifts the surrounding run context that makes a row reproducible:
  * `# Collective test starting: <x>_perf(_mpi)?` / `concluded:` brackets
    (NEMO-container dialect). When NO `starting:` marker ever appears — the
    standalone host-binary path in nccl_allreduce.sbatch — every data row is
    attributed to all_reduce, matching nccl_parse.inc.sh lines 8-13.
  * `===== nccl_allreduce round R/N =====` round banners.
  * The nccl_allreduce.sbatch preamble (`nccl_allreduce: nodes=.. np=.. …`,
    `NCCL version=.. lib=..`, `bin=.. per-collective timeout=..s`,
    `NCCL_IB_HCA=.. NCCL_SOCKET_IFNAME=..`).
  * The `# Using devices` rank block -> hosts, nranks, gpus_per_node.
  * The `# nThread .. minBytes .. maxBytes .. validation: N` banner.
  * Footers `# Out of bounds values : n OK|FAILED` and `# Avg bus bandwidth : f`.
  * `via NET/(IB|Socket|SPCX)` transport evidence, which is how a nominally
    "NVLink" run is caught having silently fallen back to IB.

FIXTURE SAFETY
--------------
If FIXTURE_BANNER_RE matches anywhere in the input, the parse is marked
`fixture=True` and the caller CANNOT downgrade it. See nccl_ingest.py.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- unmistakable fixture marker -------------------------------------------
# Emitted by fixtures/mk_nccl_fixture.sh into every synthetic log. Detection is
# one-directional: it can only ever turn fixture ON, never off.
FIXTURE_BANNER_RE = re.compile(
    r"FIXTURE[ _-]?(?:NOT[ _-]?REAL|SYNTHETIC)|SYNTHETIC NCCL OUTPUT|NOT_REAL_DATA",
    re.IGNORECASE,
)

# --- line shapes ------------------------------------------------------------
_COLL_START_RE = re.compile(r"^#\s*Collective test starting:\s*(\S+?)(?:_perf)?(?:_mpi)?\s*$")
_COLL_END_RE = re.compile(r"^#\s*Collective test concluded:")
_ROUND_RE = re.compile(r"^=+\s*nccl_\w+\s+round\s+(\d+)\s*/\s*(\d+)\s*=+\s*$")
_RANK_RE = re.compile(
    r"^#\s*Rank\s+(\d+)\s+Group\s+(\d+)\s+Pid\s+(\d+)\s+on\s+(\S+)\s+device\s+(\d+)"
    r"(?:\s+\[([^\]]*)\])?\s*(.*)$"
)
_OOB_RE = re.compile(r"^#\s*Out of bounds values\s*:\s*(\d+)\s*(\S+)?")
_AVG_RE = re.compile(r"^#\s*Avg bus bandwidth\s*:\s*([0-9.eE+-]+)")
_NTHREAD_RE = re.compile(r"^#\s*nThread\b")
_TRANSPORT_RE = re.compile(r"\bvia\s+NET/(\S+)")
_NVLS_RE = re.compile(r"\b(NVLS|NVLink|NVL72)\b")

# nccl_allreduce.sbatch:145-148 structured preamble
_PRE_NODES_RE = re.compile(
    r"^nccl_\w+:\s*nodes=(\d+)\s+np=(\d+)\s+gpus/node=(\d+)\s+sizes=(\S+)\.\.(\S+)\s+rounds=(\d+)")
_PRE_VER_RE = re.compile(r"^nccl_\w+:\s*NCCL version=(\S+)\s+lib=(\S+)")
_PRE_BIN_RE = re.compile(r"^nccl_\w+:\s*bin=(\S+)\s+per-collective timeout=(\d+)s")
_PRE_HCA_RE = re.compile(r"^nccl_\w+:\s*NCCL_IB_HCA=(\S+)\s+NCCL_SOCKET_IFNAME=(\S+)")
_PRE_EXIT_RE = re.compile(r"^nccl_\w+:\s*exit\s+(-?\d+)")
_PRE_ROUND_RC_RE = re.compile(r"^nccl_\w+:\s*round\s+(\d+)/(\d+)\s+(OK|FAILED)(?:\s+rc=(-?\d+))?")

# canonical collective names
_COLL_CANON = {
    "all_reduce": "all_reduce", "allreduce": "all_reduce",
    "all_gather": "all_gather", "allgather": "all_gather",
    "reduce_scatter": "reduce_scatter", "reducescatter": "reduce_scatter",
    "alltoall": "alltoall", "all_to_all": "alltoall",
    "sendrecv": "sendrecv", "broadcast": "broadcast", "reduce": "reduce",
    "scatter": "scatter", "gather": "gather", "hypercube": "hypercube",
}

# header token -> logical field. '#wrong' keeps its '#'; only a bare '#' is a
# comment marker and is dropped (this is exactly llmb.sh's `if (t == "#") continue`).
_HDR_FIELD = {
    "size": "size_bytes", "count": "count_elems", "type": "dtype",
    "redop": "redop", "root": "root", "time": "time_us",
    "algbw": "algbw_gbps", "busbw": "busbw_gbps", "#wrong": "wrong",
}

PLACEMENTS = ("out_of_place", "in_place")


def canon_collective(name: str) -> str:
    n = (name or "").strip().lower()
    n = re.sub(r"_perf(_mpi)?$", "", n)
    return _COLL_CANON.get(n, n or "all_reduce")


@dataclass
class ColumnMap:
    """Data-column positions (1-based) discovered from a `# ... busbw ...` header."""
    per_field: dict = field(default_factory=dict)   # field -> [idx,...] in header order
    ncols: int = 0
    dialect: str = "unknown"                        # '13col' | '11col' | 'fallback'
    header_line: str = ""

    def idx(self, fieldname: str, placement_i: int = 0):
        v = self.per_field.get(fieldname)
        if not v:
            return None
        # size/count/type/redop/root appear once and are shared by both placements
        return v[placement_i] if len(v) > placement_i else v[0]


def parse_header(line: str) -> ColumnMap | None:
    """Build a ColumnMap from a comment line containing 'busbw'."""
    if "busbw" not in line:
        return None
    toks = [t for t in line.split() if t != "#"]
    # strip a leading '#' fused to the first token, e.g. '#       size' -> handled
    # by split() already; but '#size' would fuse — normalise defensively.
    if toks and toks[0].startswith("#") and toks[0] != "#wrong":
        toks[0] = toks[0].lstrip("#")
        if not toks[0]:
            toks = toks[1:]
    cm = ColumnMap(ncols=len(toks), header_line=line.rstrip("\n"))
    for i, t in enumerate(toks, start=1):
        f = _HDR_FIELD.get(t.lower())
        if f:
            cm.per_field.setdefault(f, []).append(i)
    if "busbw_gbps" not in cm.per_field:
        return None
    cm.dialect = {13: "13col", 11: "11col"}.get(cm.ncols, f"{cm.ncols}col")
    return cm


def _fallback_map(nf: int) -> ColumnMap | None:
    """No header seen. Mirror llmb.sh's positional fallback exactly."""
    if nf >= 13:
        pf = {"size_bytes": [1], "count_elems": [2], "dtype": [3], "redop": [4],
              "root": [5], "time_us": [6, 10], "algbw_gbps": [7, 11],
              "busbw_gbps": [8, 12], "wrong": [9, 13]}
        return ColumnMap(pf, 13, "fallback13", "")
    if nf >= 11:
        pf = {"size_bytes": [1], "count_elems": [2], "dtype": [3],
              "time_us": [4, 8], "algbw_gbps": [5, 9],
              "busbw_gbps": [6, 10], "wrong": [7, 11]}
        return ColumnMap(pf, 11, "fallback11", "")
    return None


def _num(tok: str, cast, default=None):
    if tok is None:
        return default
    t = tok.strip()
    if t in ("", "N/A", "n/a", "NA", "-"):
        return default
    try:
        return cast(t)
    except ValueError:
        try:
            return cast(float(t))
        except ValueError:
            return default


@dataclass
class ParsedRun:
    """Everything one nccl-tests log file yielded."""
    rows: list = field(default_factory=list)          # list[dict] — one per size x placement
    hosts: list = field(default_factory=list)         # ordered, de-duplicated
    ranks: list = field(default_factory=list)         # dicts from the `# Using devices` block
    nranks: int | None = None
    nnodes: int | None = None
    gpus_per_node: int | None = None
    nccl_version: str | None = None
    nccl_lib_path: str | None = None
    nccl_tests_bin: str | None = None
    transport: str | None = None
    avg_busbw_gbps: float | None = None
    oob_ok: bool | None = None
    oob_count: int | None = None
    rounds_declared: int | None = None
    exit_rc: int | None = None
    validation_enabled: bool | None = None
    size_min: str | None = None
    size_max: str | None = None
    dialects: set = field(default_factory=set)
    kv: dict = field(default_factory=dict)
    fixture: bool = False
    src_file: str = ""
    warnings: list = field(default_factory=list)


def parse_nccl_log(path: str, text: str | None = None) -> ParsedRun:
    """Parse one nccl-tests sweep file into a ParsedRun. Never raises on bad lines."""
    if text is None:
        with open(path, "r", errors="replace") as fh:
            text = fh.read()

    pr = ParsedRun(src_file=os.path.abspath(path))
    if FIXTURE_BANNER_RE.search(text):
        pr.fixture = True

    cm: ColumnMap | None = None
    cur_coll: str | None = None
    saw_start_marker = False
    cur_round = 1
    seen_hosts: dict[str, None] = {}
    dev_per_host: dict[str, set] = {}

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\n")
        s = line.strip()
        if not s:
            continue

        # ---- round banner (outside the '#' family) -------------------------
        m = _ROUND_RE.match(s)
        if m:
            cur_round = int(m.group(1))
            pr.rounds_declared = pr.rounds_declared or int(m.group(2))
            cm = None            # each round reprints its own header
            cur_coll = None if saw_start_marker else cur_coll
            continue

        # ---- harness preamble ---------------------------------------------
        if s.startswith("nccl_"):
            m = _PRE_NODES_RE.match(s)
            if m:
                pr.nnodes = int(m.group(1))
                pr.nranks = int(m.group(2))
                pr.gpus_per_node = int(m.group(3))
                pr.size_min, pr.size_max = m.group(4), m.group(5)
                pr.rounds_declared = int(m.group(6))
                continue
            m = _PRE_VER_RE.match(s)
            if m:
                pr.nccl_version, pr.nccl_lib_path = m.group(1), m.group(2)
                continue
            m = _PRE_BIN_RE.match(s)
            if m:
                pr.nccl_tests_bin = m.group(1)
                pr.kv["nccl_test_timeout_s"] = m.group(2)
                continue
            m = _PRE_HCA_RE.match(s)
            if m:
                pr.kv["NCCL_IB_HCA"] = m.group(1)
                pr.kv["NCCL_SOCKET_IFNAME"] = m.group(2)
                continue
            m = _PRE_EXIT_RE.match(s)
            if m:
                pr.exit_rc = int(m.group(1))
                continue
            m = _PRE_ROUND_RC_RE.match(s)
            if m:
                pr.kv[f"round{m.group(1)}_status"] = m.group(3)
                if m.group(4):
                    pr.kv[f"round{m.group(1)}_rc"] = m.group(4)
                continue

        # ---- transport evidence (can appear on any line) -------------------
        if pr.transport is None:
            m = _TRANSPORT_RE.search(s)
            if m:
                pr.transport = f"NET/{m.group(1).rstrip(',.')}"
            elif "NVLS" in s or "via NVLink" in s:
                if _NVLS_RE.search(s):
                    pr.transport = "NVLink/intra"

        # ---- comment family -------------------------------------------------
        if s.startswith("#"):
            m = _COLL_START_RE.match(s)
            if m:
                cur_coll = canon_collective(m.group(1))
                saw_start_marker = True
                continue
            if _COLL_END_RE.match(s):
                cur_coll = None
                continue
            m = _RANK_RE.match(s)
            if m:
                host = m.group(4)
                seen_hosts.setdefault(host, None)
                dev_per_host.setdefault(host, set()).add(int(m.group(5)))
                pr.ranks.append({
                    "rank": int(m.group(1)), "group": int(m.group(2)),
                    "pid": int(m.group(3)), "host": host,
                    "device": int(m.group(5)), "bus_id": m.group(6) or "",
                    "gpu_model": (m.group(7) or "").strip(),
                })
                continue
            m = _OOB_RE.match(s)
            if m:
                pr.oob_count = int(m.group(1))
                verdict = (m.group(2) or "").upper()
                pr.oob_ok = (verdict == "OK") if verdict else (pr.oob_count == 0)
                continue
            m = _AVG_RE.match(s)
            if m:
                pr.avg_busbw_gbps = float(m.group(1))
                continue
            if _NTHREAD_RE.match(s):
                mv = re.search(r"validation:\s*(\d+)", s)
                if mv:
                    pr.validation_enabled = mv.group(1) != "0"
                # NB `iters` must not be captured out of `warmup iters`/`agg iters`
                for k, rx in (("minBytes", r"minBytes\s+(\S+)"),
                              ("maxBytes", r"maxBytes\s+(\S+)"),
                              ("warmup_iters", r"warmup iters:\s*(\S+)"),
                              ("iters", r"(?<!warmup )(?<!agg )iters:\s*(\S+)"),
                              ("agg_iters", r"agg iters:\s*(\S+)"),
                              ("graph", r"graph:\s*(\S+)")):
                    mk = re.search(rx, s)
                    if mk:
                        pr.kv[k] = mk.group(1)
                continue
            # header line?
            got = parse_header(s)
            if got:
                cm = got
                pr.dialects.add(got.dialect)
            continue

        # ---- data row --------------------------------------------------------
        toks = s.split()
        if not toks or not toks[0].isdigit():
            continue
        use = cm or _fallback_map(len(toks))
        if use is None:
            continue
        if use is not cm and use.dialect.startswith("fallback"):
            pr.dialects.add(use.dialect)
        maxidx = max(i for v in use.per_field.values() for i in v)
        if len(toks) < maxidx:
            pr.warnings.append(f"{path}:{lineno}: {len(toks)} fields < {maxidx} expected "
                               f"({use.dialect}) — row skipped")
            continue

        coll = cur_coll if cur_coll else (canon_collective("all_reduce")
                                          if not saw_start_marker else None)
        if coll is None:
            continue

        def g(f, p=0):
            i = use.idx(f, p)
            return toks[i - 1] if i else None

        base = {
            "collective": coll,
            "round": cur_round,
            "size_bytes": _num(g("size_bytes"), int),
            "count_elems": _num(g("count_elems"), int),
            "dtype": g("dtype"),
            "redop": g("redop"),
            "root": _num(g("root"), int),
            "src_lineno": lineno,
            "dialect": use.dialect,
        }
        for p, placement in enumerate(PLACEMENTS):
            if use.idx("busbw_gbps", p) is None:
                continue
            row = dict(base)
            row["placement"] = placement
            row["time_us"] = _num(g("time_us", p), float)
            row["algbw_gbps"] = _num(g("algbw_gbps", p), float)
            row["busbw_gbps"] = _num(g("busbw_gbps", p), float)
            # `#wrong` is N/A when the banner said `validation: 0`; -1 encodes that
            row["wrong"] = _num(g("wrong", p), int, default=-1)
            pr.rows.append(row)

    pr.hosts = list(seen_hosts.keys())
    if pr.ranks:
        pr.nranks = pr.nranks or len(pr.ranks)
        pr.nnodes = pr.nnodes or len(pr.hosts)
        if pr.gpus_per_node is None and dev_per_host:
            pr.gpus_per_node = max(len(v) for v in dev_per_host.values())
    if pr.nnodes is None and pr.nranks and pr.gpus_per_node:
        pr.nnodes = pr.nranks // pr.gpus_per_node
    return pr


# --- run identity ------------------------------------------------------------
# Nothing in the suite emits a run identifier; identity is scattered across the
# state path, the slurm jobid and the log basename. Reconstruct it deterministically.
_EPOCH_FLOOR = 1_600_000_000     # 10-digit "jobid" >= this is really an epoch
                                 # (nccl_fullrack_rounds.sh substitutes date +%s)

_LOG_PATTERNS = [
    # rack-status single-rack: <user>-NCCL-1Rack-<rack>-<N>N-<jobid>.txt
    (re.compile(r"^(?P<user>[^/]+?)-NCCL-1Rack-(?P<unit>.+?)-(?P<nnodes>\d+)N-(?P<job>\d+)\.txt$"),
     dict(harness="rackstatus", workload="nccl_allreduce", unit_kind="rack")),
    # rack-status cross-rack: nccl-mpi_<label>_<jobid>.out
    (re.compile(r"^nccl-mpi_(?P<unit>.+)_(?P<job>\d+)\.out$"),
     dict(harness="rackstatus", workload="nccl_multi", unit_kind="group")),
    # llmb launched from rack-status: llmb-nccl_<rack_label>_<jobid>.out
    (re.compile(r"^llmb-nccl_(?P<unit>.+)_(?P<job>\d+)\.out$"),
     dict(harness="llmb", workload="nccl_single", unit_kind="rack")),
    # stage-1 acceptance rounds: rounds_<UTCSTAMP>/round_<r>.log
    (re.compile(r"^round_(?P<run_seq>\d+)\.log$"),
     dict(harness="rackstatus", workload="nccl_rounds", unit_kind="rack")),
    # llmb-run microbenchmark_nccl sweep file: [nccl_]LOG_<collective>_<gpus>_iterN.txt
    # (lib/llmb.sh discovers these as `*LOG_<collective>_*.txt`)
    (re.compile(r"^(?:\w+_)?LOG_(?P<coll>[a-z_]+?)_(?P<gpus>\d+)_(?P<iter>iter\d+)\.txt$"),
     dict(harness="llmb", workload="nccl_single", unit_kind="rack")),
]


def derive_run_identity(path: str, cluster: str = "IREN_MKZ",
                        overrides: dict | None = None) -> dict:
    """
    Reconstruct (harness, workload, unit_kind, unit_id, run_seq, job_id, run_id,
    unit_key) from a log path. `overrides` always wins.

    run_id  = <cluster>-<harness>-<workload>-<unit_id>[-r<seq>]-<job_key>
    job_key = j<slurm_jobid> when known, else t<epoch_seconds>.
    The jobid is INSIDE run_id on purpose: MAX_ATTEMPTS=3 retries reuse the same
    (unit, workload, run_seq) with a NEW jobid, and each attempt is physically a
    distinct run. `unit_key` is the retry-stable grouping key.
    """
    o = dict(overrides or {})
    base = os.path.basename(path)
    parent = os.path.basename(os.path.dirname(path))
    info = dict(harness="manual", workload="nccl_allreduce", unit_kind="rack",
                unit_id="UNKNOWN", run_seq=1, job_id=None, job_key=None)

    for rx, defaults in _LOG_PATTERNS:
        m = rx.match(base)
        if not m:
            continue
        info.update(defaults)
        gd = m.groupdict()
        if gd.get("unit"):
            info["unit_id"] = gd["unit"].replace("+", "_")
        if gd.get("run_seq"):
            info["run_seq"] = int(gd["run_seq"])
        if gd.get("job"):
            j = int(gd["job"])
            # 10-digit values >= 2020-09 are epochs from nccl_fullrack_rounds.sh
            info["job_key"] = (f"t{j}" if j >= _EPOCH_FLOOR else f"j{j}")
            info["job_id"] = gd["job"]
        if gd.get("nnodes"):
            info["nnodes_hint"] = int(gd["nnodes"])
        if gd.get("iter"):
            info["iter_label"] = gd["iter"]
        if gd.get("coll"):
            # llmb sweep: the collective is in the filename and the unit is the
            # enclosing experiment dir (…/experiments/<exp>_<jobid>/LOG_…/<file>)
            info["collective_hint"] = canon_collective(gd["coll"])
            info["unit_id"] = gd["coll"]
        if gd.get("gpus"):
            info["ngpus_hint"] = int(gd["gpus"])
        break
    else:
        # llmb experiment tree: .../experiments/<exp>_<jobid>/LOG_<tag>_<jobid>_<n>/...
        mm = re.search(r"/experiments/(?P<exp>[^/]+?)_(?P<job>\d+)/", path)
        if mm:
            info.update(harness="llmb", workload="nccl_single", unit_kind="rack",
                        unit_id=mm.group("exp"), job_id=mm.group("job"),
                        job_key=f"j{mm.group('job')}")

    # rounds_<UTCSTAMP>/round_<r>.log -> unit id from the rounds dir stamp
    if info["workload"] == "nccl_rounds" and parent.startswith("rounds_"):
        info.setdefault("rounds_stamp", parent[len("rounds_"):])
        info["kv_rounds_stamp"] = parent[len("rounds_"):]
        if info["unit_id"] == "UNKNOWN":
            info["unit_id"] = parent[len("rounds_"):]

    # llmb sweep filenames carry the collective + an iterN tag
    mi = re.search(r"_(iter\d+)", base)
    if mi:
        info["iter_label"] = mi.group(1)

    if not info.get("job_key"):
        try:
            ep = int(os.path.getmtime(path))
        except OSError:
            ep = int(datetime.now(tz=timezone.utc).timestamp())
        info["job_key"] = f"t{ep}"

    info.update(o)

    seq = f"-r{info['run_seq']:02d}" if int(info.get("run_seq", 1)) > 1 else ""
    if not info.get("run_id"):
        info["run_id"] = (f"{cluster}-{info['harness']}-{info['workload']}-"
                          f"{info['unit_id']}{seq}-{info['job_key']}")
    if not info.get("unit_key"):
        info["unit_key"] = (f"{cluster}-{info['workload']}-{info['unit_id']}"
                            f"-r{int(info.get('run_seq', 1)):02d}")
    return info
