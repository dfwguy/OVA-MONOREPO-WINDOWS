#!/usr/bin/env python3
"""lake_result_map — map EVERY result file under /cluster to its Slurm job.

THE PROBLEM THIS SOLVES
    The census gives one row per job (149,283 of them) but only ~1.7% carry
    numbers, because the bringup sequencer writes
    /cluster/bringup/results/<node>/<test>.txt with no job id anywhere in the
    path, last-write-wins, rotating older attempts to <test>.failN.txt. Nothing
    joined those 137,663 files back to the jobs that produced them.

THE JOIN, AND WHY IT IS EXACT
    Slurm writes a job's output as the job exits, so a result file's mtime IS
    the job's End time. Measured on a real node: 20 of 20 jobs matched, median
    delta 0 s, max 1 s. This is not a statistical guess -- it is the same clock
    event recorded twice. Files whose name already contains a job id skip the
    correlation entirely and are mapped directly.

EVERYTHING IS LOCAL. /cluster is ext4 on this box's own NVMe and this box
EXPORTS it to the head node. Reading it over SSH would send every byte out to
the head and back across NFS to our own disk, and would put the head node's NFS
client in the path of a 232,000-file walk while it is provisioning. Nothing
here touches the head node -- no ssh, no sacct over the wire.

HONESTY RULES
    * A file that cannot be mapped is written with map_method='unmapped' and a
      reason. It is never dropped and never attached to a plausible-looking job.
    * Ambiguous matches (two jobs within the tie window) are marked
      map_method='ambiguous' rather than silently resolved.
    * Health-check artifacts get their OWN table. Forcing bios/dmesg/ib-link
      output into a benchmark-result schema would invent fields that do not
      exist.
"""
from __future__ import annotations
import argparse
import bisect
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

LAKE = os.environ.get("LAKE_ROOT", "/data/lake")
CENSUS = os.path.join(LAKE, "curated", "slurm_jobs", "part-000.parquet")
OUT_RESULTS = os.path.join(LAKE, "curated", "run_results")
OUT_HEALTH = os.path.join(LAKE, "curated", "health_artifacts")
CLUSTER = os.environ.get("CLUSTER_NAME", "IREN_MKZ")

ROOTS = [
    ("/cluster/bringup/results", "result"),
    ("/cluster/benchmark/harish/rack_status/logs", "result"),
    ("/cluster/benchmark/harish/manual_tests", "result"),
    # NOT /cluster/benchmark/harish/llmb/workloads: walking it pulled in
    # 3.26M framework internals (checkpoints, shards, configs) that are not
    # results. Its per-experiment dirs ARE job-keyed, so the few files that
    # matter there are picked up by name below.
    ("/cluster/benchmark/harish/llmb/workloads", "result_shallow"),
    ("/cluster/bringup/logs", "health"),
]
# Files that are never a benchmark result.
# nccl_debug_file.<host>.<pid>.txt is a PER-RANK NCCL_DEBUG=INFO trace, one per
# rank per collective per iteration: 1,444,120 of them in a 589 GB tree under
# llmb/workloads. They match RESULT_NAME_RE only because the name contains
# "nccl", and parsing them at a 4 MiB tail each ran for 80 minutes on
# 2026-08-16 without finishing and would have written >1.4M junk rows into
# run_results. They are debug spew, never a benchmark result. Excluded by name.
SKIP_RE = re.compile(r"\.(heartbeat|slurm-view|lock|tmp|swp)$|^\.|^nccl_debug_file\.")
# A result is a text log we can parse. Everything else in these trees is
# framework baggage and must not inflate the table.
RESULT_NAME_RE = re.compile(
    r"(allreduce|alltoall|allgather|reduce_scatter|reducescatter|sendrecv|nccl|"
    r"mnubergemm|ubergemm|burnin|llama|nemo|nemotron|dcgmi?|nvbandwidth|hpl)"
    r".*\.(txt|out|log)$", re.I)
JOBID_RE = re.compile(r"(\d{4,7})(?!.*\d{4,7})")
NODE_RE = re.compile(r"(example50-dh\d{2}-[a-z]\d+-\d+)")
# A job whose End is within this many seconds of the file mtime is the writer.
# Measured max delta was 1 s; 120 s is generous and still far below the gap
# between consecutive jobs on the same node+test.
TIE_S = int(os.environ.get("RESULT_MAP_TIE_S", "120"))
# Two candidate jobs this close to each other cannot be told apart by mtime.
AMBIG_S = int(os.environ.get("RESULT_MAP_AMBIG_S", "5"))
PARSE_TAIL = int(os.environ.get("RESULT_PARSE_TAIL", str(4 * 1024 * 1024)))

# Rack-status campaign output is intentionally discovered separately from the
# older result trees.  /cluster/OVA/logs also contains staging logs, per-rank
# NCCL traces, debug captures and ad-hoc operator files; walking it with the
# broad RESULT_NAME_RE would turn those into apparent validation attempts.
# These are the authoritative top-level stdout names produced by the SU1-SU14
# NCCL, NeMo and MNUberGEMM launchers.
CAMPAIGN_RESULT_ROOT = os.environ.get("CAMPAIGN_RESULT_ROOT", "/cluster/OVA/logs")
CAMPAIGN_PARSE_TAIL = int(os.environ.get(
    "CAMPAIGN_RESULT_PARSE_TAIL", str(512 * 1024)))
CAMPAIGN_GLOBS = (
    "SU*/rack*/singleNodeNCCL/nvftp-nccl-five-collective-*.out",
    "SU*/rack*/singleRackNCCL/nvftp-nccl-five-collective-*.out",
    "SU*/rack*/multiNodeNCCL/nvftp-nccl-five-collective-*.out",
    "SU*/rack*/singleNodeNeMo/sn-llama/rack-status-NEMO-*.txt",
    "SU*/rack*/singleRackNeMo/nemo-*.out",
    "SU*/rack*/multiNodeNeMo/nemo-*.out",
    "iren_mkz-16k-validation/nemo-*.out",
    "SU*/rack*/singleNodeMNU/mnubergemm-*.out",
    "SU*/rack*/multiNodeMNU/mnubergemm-*.out",
)
_SU = r"(?:[1-9]|1[0-4])"
_RACK = r"(?:0[1-8]|1[7-9]|2[0-4])"
_JID = r"\d{4,7}"
CAMPAIGN_PATH_RE = re.compile(
    rf"^(?:SU{_SU}/rack{_RACK}/(?:"
    rf"(?:singleNodeNCCL|singleRackNCCL|multiNodeNCCL)/"
    rf"nvftp-nccl-five-collective-{_JID}\.out|"
    rf"singleNodeNeMo/sn-llama/rack-status-NEMO-[^/]+-{_JID}\.txt|"
    rf"(?:singleRackNeMo|multiNodeNeMo)/nemo-[^/]+-{_JID}\.out|"
    rf"(?:singleNodeMNU|multiNodeMNU)/mnubergemm-[^/]+-{_JID}\.out"
    rf")|iren_mkz-16k-validation/nemo-[^/]+-{_JID}\.out)$")
CAMPAIGN_NCCL_COLLECTIVES = {
    "all_reduce", "alltoall", "sendrecv", "all_gather", "reduce_scatter"}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lake_run_backfill import (  # noqa: E402
    parse_nccl, parse_llama_nemo, parse_mnubergemm, verdict_for)

TEST_PARSER = [
    (re.compile(r"nvbandwidth", re.I), "nvbandwidth", None),
    (re.compile(r"dcgmi", re.I), "dcgm", None),
    (re.compile(r"allreduce|alltoall|allgather|reduce|sendrecv|nccl", re.I),
     "nccl", parse_nccl),
    (re.compile(r"mnubergemm|ubergemm|burnin", re.I), "mnubergemm", parse_mnubergemm),
    (re.compile(r"llama|nemo|nemotron|llm-pretrain", re.I), "llama", parse_llama_nemo),
]


def pick_parser(name: str):
    for rx, cls, fn in TEST_PARSER:
        if rx.search(name):
            if cls == "nvbandwidth":
                return cls, parse_nvbandwidth
            if cls == "dcgm":
                return cls, parse_dcgm
            return cls, fn
    return None, None


def iter_campaign_result_paths(root: str = CAMPAIGN_RESULT_ROOT):
    """Yield only authoritative SU1-SU14 campaign stdout files.

    Both the constrained globs and the full relative-path allowlist are
    deliberate.  The second gate prevents a future broad glob change from
    admitting job detail, staging, raw, debug, or out-of-scope SU/rack files.
    """
    base = Path(root)
    if not base.is_dir():
        return
    seen = set()
    for pattern in CAMPAIGN_GLOBS:
        for path in base.glob(pattern):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if not CAMPAIGN_PATH_RE.fullmatch(rel):
                continue
            seen.add(str(path))
    yield from sorted(seen)


def campaign_workload(path: str) -> tuple[str, object]:
    """Return the parser for an already allowlisted campaign path."""
    rel = Path(path).as_posix()
    if "/singleNodeNCCL/" in rel or "/singleRackNCCL/" in rel \
            or "/multiNodeNCCL/" in rel:
        return "nccl", parse_campaign_nccl
    if "/singleNodeNeMo/" in rel or "/singleRackNeMo/" in rel \
            or "/multiNodeNeMo/" in rel:
        return "nemo", parse_llama_nemo
    if "/iren_mkz-16k-validation/nemo-" in rel and rel.endswith(".out"):
        return "nemo", parse_llama_nemo
    if "/singleNodeMNU/" in rel or "/multiNodeMNU/" in rel:
        return "mnubergemm", parse_mnubergemm
    return "", None


def read_campaign_text(path: str, size: int) -> str:
    """Read campaign evidence without rereading multi-GB NeMo logs.

    MNU's HOSTLIST is at the head while every strict terminal marker and all
    recent performance samples are at the tail.  Preserve both, and read small
    files once.
    """
    head_n = 64 * 1024
    with open(path, "rb") as fh:
        if size <= head_n + CAMPAIGN_PARSE_TAIL:
            return fh.read().decode("utf-8", "replace")
        head = fh.read(head_n)
        fh.seek(size - CAMPAIGN_PARSE_TAIL)
        tail = fh.read()
    return (head + b"\nCAMPAIGN_TAIL_FOLLOWS\n" + tail).decode(
        "utf-8", "replace")


def parse_campaign_nccl(txt: str):
    """Parse the strict five-collective campaign wrapper markers."""
    tests = []
    for line in re.findall(r"^TEST_END\s+.*$", txt, re.M):
        fields = dict(re.findall(r"(\w+)=([^\s]+)", line))
        if "collective" in fields:
            tests.append({
                "collective": fields["collective"],
                "rc": int(fields["rc"]) if fields.get("rc", "").isdigit() else None,
                "correctness": fields.get("correctness", ""),
            })
    end = re.findall(r"^FIVE_COLLECTIVE_SWEEP_END\s+.*$", txt, re.M)
    terminal = dict(re.findall(r"(\w+)=([^\s]+)", end[-1])) if end else {}
    result = {
        "collectives": len(tests),
        "collective_names": sorted({x["collective"] for x in tests}),
        "failed_collectives": sum(
            x["rc"] != 0 or x["correctness"] != "OK" for x in tests),
        "terminal_rc": int(terminal["rc"])
        if terminal.get("rc", "").isdigit() else None,
        "detail_rc": int(terminal["detail_rc"])
        if terminal.get("detail_rc", "").isdigit() else None,
        "terminal_marker": bool(end),
    }
    if not tests and not end:
        return result, False, "no strict NCCL campaign markers"
    return result, True, ""


def campaign_verdict_from_file(workload: str, result: dict, parse_ok: bool,
                               reason: str, slurm_state: str,
                               txt: str) -> tuple[str, str]:
    """Fail-closed verdict for an authoritative campaign stdout.

    A metric alone is never a campaign PASS.  Each workload must carry its own
    completion/correctness markers and the census must say COMPLETED.
    """
    state = (slurm_state or "").split(" by")[0].strip().upper()
    completed = state == "COMPLETED"
    if workload == "nccl":
        names = set(result.get("collective_names") or [])
        bad = result.get("failed_collectives", 0)
        terminal_bad = (result.get("terminal_marker") and
                        (result.get("terminal_rc") != 0 or
                         result.get("detail_rc") != 0))
        if bad or terminal_bad:
            return "FAIL", "five-collective wrapper reported failure"
        strict = (parse_ok and names == CAMPAIGN_NCCL_COLLECTIVES and
                  result.get("collectives") == 5 and
                  result.get("terminal_marker") and
                  result.get("terminal_rc") == 0 and
                  result.get("detail_rc") == 0)
        if strict and completed:
            return "PASS", "5/5 collectives correct; sweep/detail rc=0"
        detail = reason or f"only {len(names)}/5 strict collectives"
        if strict and not completed:
            detail = f"strict markers present; Slurm says {state or 'UNKNOWN'}"
        return "PARTIAL", detail

    if workload in ("llama", "nemo"):
        fail = re.findall(r"^NEMO_VALIDATION_FAIL\b.*$", txt, re.M)
        passed = re.findall(
            r"^NEMO_VALIDATION_PASS\s+max_steps=(\d+)\s+nodes=(\d+)\s*$",
            txt, re.M)
        result["validation_pass_marker"] = bool(passed)
        result["validation_fail_marker"] = bool(fail)
        if passed:
            result["validation_max_steps"] = int(passed[-1][0])
            result["validation_nodes"] = int(passed[-1][1])
        if fail or result.get("nan_iterations"):
            return "FAIL", fail[-1] if fail else "non-zero NaN iterations"
        steps = result.get("validation_max_steps")
        strict = (parse_ok and bool(passed) and steps is not None and
                  result.get("iterations") == steps and
                  result.get("iterations_target") == steps)
        if strict and completed:
            return "PASS", f"explicit NeMo pass at {steps}/{steps} steps"
        detail = reason or "missing complete NeMo pass evidence"
        if strict and not completed:
            detail = f"strict marker present; Slurm says {state or 'UNKNOWN'}"
        return "PARTIAL", detail

    if workload == "mnubergemm":
        hostlist = re.findall(r"^HOSTLIST:\s*(\S.*)$", txt, re.M)
        expected = set(re.findall(
            r"example50-dh\d{2}-[a-z]\d+-\d+", hostlist[-1] if hostlist else ""))
        quals = re.findall(
            r"G:\s*(\d+)\s+(example50-dh\d{2}-[a-z]\d+-\d+)\s+L:.*"
            r"returning QUAL_OK\s*$", txt, re.M)
        by_host = {}
        for gpu, host in quals:
            by_host.setdefault(host, set()).add(int(gpu))
        teardown = bool(re.search(r"normal mpi teardown\s*$", txt, re.M))
        explicit_bad = bool(re.search(
            r"returning QUAL_(?!OK\b)|QUAL_RUNTIME_ERROR|Xid detected|"
            r"XID MONITOR\s*:\s*found\s*\[[^\]\s]",
            txt, re.I))
        result.update(
            expected_hosts=sorted(expected), qual_ok_hosts=sorted(by_host),
            qual_ok_count=len(quals), normal_mpi_teardown=teardown)
        if explicit_bad or result.get("fault"):
            return "FAIL", "MNUberGEMM reported GPU/runtime fault"
        strict = (parse_ok and bool(expected) and set(by_host) == expected and
                  all(gpus == {0, 1, 2, 3} for gpus in by_host.values()) and
                  len(quals) == 4 * len(expected) and teardown)
        if strict and completed:
            return "PASS", (f"{len(expected)} node(s), 4 QUAL_OK each; "
                            "normal MPI teardown")
        detail = reason or "missing complete QUAL_OK/MPI teardown evidence"
        if strict and not completed:
            detail = f"strict markers present; Slurm says {state or 'UNKNOWN'}"
        return "PARTIAL", detail

    return "UNKNOWN", "unsupported campaign workload"


def _exit_status(txt: str) -> int | None:
    hits = re.findall(r"^exit status:\s*(\d+)\s*$", txt, re.M | re.I)
    return int(hits[-1]) if hits else None


def parse_nvbandwidth(txt: str):
    """Parse the explicit SUM/CV records written by nvbandwidth.

    The bring-up wrapper can leave a trailing ``PENDING`` token even after the
    tool exits, so the verdict is derived from nvbandwidth's own measurements
    and exit status, never from Slurm or the wrapper token.
    """
    sums = {k: float(v) for k, v in re.findall(
        r"^SUM\s+(\S+)\s+([-+0-9.eE]+)\s*$", txt, re.M)}
    cvs = {k: float(v) for k, v in re.findall(
        r"^COEFFICIENT_OF_VARIATION\s+(\S+)\s+([-+0-9.eE]+)\s*$", txt, re.M)}
    status = _exit_status(txt)
    failed = bool(re.search(
        r"CUDA runtime sanity check failed|\bError when executing\b|^FAIL\s*$",
        txt, re.M | re.I))
    res = {"exit_status": status, "sum_gbps": sums, "coefficient_of_variation": cvs}
    if failed or (status is not None and status != 0):
        res["outcome"] = "fail"
        return res, True, "nvbandwidth reported failure"
    if status == 0 and sums:
        res["outcome"] = "pass"
        return res, True, ""
    return res, False, "no completed nvbandwidth measurements"


def parse_dcgm(txt: str):
    """Parse DCGM's named diagnostic rows and explicit exit status."""
    tests = {}
    for name, result in re.findall(
            r"^\|\s*([A-Za-z][A-Za-z0-9_ -]*?)\s*\|\s*(Pass|Fail|Warn|Skip)\s*\|",
            txt, re.M | re.I):
        key = re.sub(r"\s+", "_", name.strip().lower())
        if key not in {"warning", "result"}:
            tests[key] = result.upper()
    gpu_results = re.findall(r"GPU\d+:\s*(Pass|Fail|Warn|Skip)", txt, re.I)
    status = _exit_status(txt)
    failed = (any(v == "FAIL" for v in tests.values())
              or any(v.upper() == "FAIL" for v in gpu_results)
              or bool(re.search(r"^Error:|diagnostic was killed", txt, re.M | re.I))
              or (status is not None and status != 0))
    res = {
        "exit_status": status,
        "tests": tests,
        "gpu_pass": sum(v.upper() == "PASS" for v in gpu_results),
        "gpu_fail": sum(v.upper() == "FAIL" for v in gpu_results),
    }
    version = re.search(r"\|\s*DCGM Version\s*\|\s*([^|]+)", txt, re.I)
    if version:
        res["dcgm_version"] = version.group(1).strip()
    if failed:
        res["outcome"] = "fail"
        return res, True, "DCGM reported failure"
    if status == 0 and tests and all(v in ("PASS", "SKIP") for v in tests.values()):
        res["outcome"] = "pass"
        return res, True, ""
    return res, False, "no completed DCGM diagnostic result"


def verdict_from_file(workload: str, result: dict, parse_ok: bool,
                      reason: str, slurm_state: str) -> tuple[str, str]:
    """Verdict for one result file, preserving full-run semantics elsewhere."""
    if workload == "nccl" and result:
        if result.get("failed_collectives"):
            return "FAIL", f"{result['failed_collectives']}/{result.get('collectives', 0)} collectives wrong"
        if (result.get("collectives") == 1 and result.get("busbw")):
            return "PASS", "single collective completed with 0 wrong values"
    if workload in ("nvbandwidth", "dcgm"):
        outcome = result.get("outcome")
        if outcome == "pass":
            return "PASS", "tool completed with explicit passing results"
        if outcome == "fail":
            return "FAIL", reason
        return "INCOMPLETE", reason
    return verdict_for(workload, result, slurm_state)


def load_jobs():
    """job index from the census: by id, and by (node -> [(end_ts, job)])."""
    import duckdb
    con = duckdb.connect()
    rows = con.execute(
        f'SELECT job_id, attempt, job_name, workload_class, state, "end", '
        f'nodes_json, result_path FROM read_parquet(\'{CENSUS}\')').fetchall()
    by_id, by_node = {}, {}
    for jid, att, name, cls, state, endt, nodes_json, rp in rows:
        by_id.setdefault(jid, (jid, att, name, cls, state, endt, rp))
        ts = None
        if endt and endt not in ("Unknown", "None", ""):
            try:
                ts = datetime.fromisoformat(endt).timestamp()
            except ValueError:
                ts = None
        if ts is None:
            continue
        try:
            nodes = json.loads(nodes_json or "[]")
        except Exception:
            nodes = []
        for n in nodes:
            by_node.setdefault(n, []).append((ts, jid, att, name, cls, state, rp))
    for n in by_node:
        by_node[n].sort()
    return by_id, by_node


def match_by_mtime(cands, mtime, basename):
    """Closest job by End time, preferring one whose result_path matches."""
    if not cands:
        return None, "no jobs for this node", None
    same = [c for c in cands if c[6] and os.path.basename(c[6]).split(".")[0]
            == basename.split(".")[0]]
    pool = same or cands
    keys = [c[0] for c in pool]
    i = bisect.bisect_left(keys, mtime)
    near = [pool[j] for j in (i - 1, i, i + 1) if 0 <= j < len(pool)]
    if not near:
        return None, "no candidate in range", None
    near.sort(key=lambda c: abs(c[0] - mtime))
    best = near[0]
    delta = mtime - best[0]
    if abs(delta) > TIE_S:
        return None, f"nearest job is {delta:+.0f}s away (>{TIE_S}s)", delta
    if len(near) > 1 and abs(abs(near[1][0] - mtime) - abs(delta)) < AMBIG_S:
        return best, "ambiguous", delta
    return best, "", delta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse", action="store_true",
                    help="parse metrics out of each mapped result (slower)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    t0 = time.time()
    by_id, by_node = load_jobs()
    print(f"census: {len(by_id)} jobs, {len(by_node)} nodes with end-times "
          f"({time.time()-t0:.1f}s)", flush=True)

    results, health = [], []
    stats = {"walked": 0, "by_jobid": 0, "by_stepid": 0, "by_mtime": 0, "ambiguous": 0,
             "unmapped": 0, "parsed": 0, "skipped": 0}
    now = int(time.time())

    sources = ROOTS + [(CAMPAIGN_RESULT_ROOT, "campaign_result")]
    for root, kind in sources:
        if not os.path.isdir(root):
            continue
        if kind == "campaign_result":
            walker = ((os.path.dirname(fp), [], [os.path.basename(fp)])
                      for fp in iter_campaign_result_paths(root))
        else:
            walker = os.walk(root)
        for dirpath, dirnames, filenames in walker:
            for fn in filenames:
                if SKIP_RE.search(fn):
                    stats["skipped"] += 1
                    continue
                # Per-tree filtering. A single global name filter cut the
                # job-keyed logs along with the framework noise and halved
                # coverage. Each tree needs its own rule:
                #   bringup/results  -> predictable <test>.txt names, filter
                #   rack_status/logs -> every file IS a job output, take all
                #   manual_tests     -> same
                #   llmb/workloads   -> 3.26M framework files; keep ONLY those
                #                       whose name carries a job id
                if kind == "health":
                    pass
                elif root.endswith("bringup/results"):
                    if not RESULT_NAME_RE.search(fn):
                        stats["skipped"] += 1
                        continue
                elif kind == "result_shallow":
                    if not JOBID_RE.search(fn):
                        stats["skipped"] += 1
                        continue
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                stats["walked"] += 1
                if a.limit and stats["walked"] > a.limit:
                    break
                node = None
                m = NODE_RE.search(fp)
                if m:
                    node = m.group(1)
                # STRATEGY ORDER: exact first, correlation last, never a guess.
                #   1. job id in the filename            -> exact
                #   2. "srun: Step created for StepId=N" -> exact (in ~7% of
                #      bringup results; joins the census 100% when present)
                #   3. mtime == job End                  -> exact when the mtime
                #      is real; measured 20/20 at median 0 s
                #   4. otherwise UNMAPPED, with the reason recorded
                # 90% of /cluster/bringup/results carries mtime 2026-08-09
                # 17:48-17:49 -- a two-minute window across 73,281 files, i.e. a
                # bulk copy that overwrote every original mtime. For those,
                # strategy 3 is not merely weak, it is invalid.
                jid, method, delta, why = None, "", None, ""
                jm = JOBID_RE.search(fn)
                if jm and jm.group(1) in by_id:
                    jid, method, delta, why = jm.group(1), "jobid", 0.0, ""
                    stats["by_jobid"] += 1
                elif jm and kind == "campaign_result":
                    # The authoritative campaign filename already names its
                    # job. If that job is absent from the census, timestamp
                    # correlation must not attach it to a different job.
                    method, delta = "unmapped", 0.0
                    why = f"embedded job {jm.group(1)} absent from census"
                    stats["unmapped"] += 1
                if jid is None and kind == "result" and st.st_size:
                    try:
                        with open(fp, "rb") as fh:
                            head = fh.read(8192).decode("utf-8", "replace")
                        sm = re.search(r"StepId=(\d+)", head)
                        if sm and sm.group(1) in by_id:
                            jid, method, delta, why = sm.group(1), "stepid", 0.0, ""
                            stats["by_stepid"] = stats.get("by_stepid", 0) + 1
                    except OSError:
                        pass
                if jid is None and method != "unmapped":
                    hit, why, delta = match_by_mtime(
                        by_node.get(node or "", []), st.st_mtime, fn)
                    if hit:
                        jid = hit[1]
                        method = "ambiguous" if why == "ambiguous" else "mtime"
                        stats["ambiguous" if why == "ambiguous" else "by_mtime"] += 1
                    else:
                        method = "unmapped"
                        stats["unmapped"] += 1
                rec = dict(cluster=CLUSTER, job_id=jid or "", node=node or "",
                           artifact_path=fp, artifact_name=fn,
                           mtime=int(st.st_mtime), size_bytes=st.st_size,
                           map_method=method, map_delta_s=float(delta or 0),
                           map_note=why, captured_at=now)
                if kind == "health":
                    health.append(rec)
                    continue
                if kind == "campaign_result":
                    cls, fn_parse = campaign_workload(fp)
                else:
                    cls, fn_parse = pick_parser(fn)
                rec["workload"] = cls or ""
                rec["test"] = re.sub(r"\.(fail\d+)?\.?(txt|out|log)$", "", fn)
                rec["verdict"] = ""
                rec["detail"] = ""
                rec["metrics_json"] = ""
                # Parse whether or not the job could be identified. 73,281
                # bringup files had their mtimes flattened by a bulk copy on
                # 2026-08-09, so their JOB is unrecoverable -- but their NUMBERS
                # are intact, and "what did h03-14's allreduce measure" is the
                # question people actually ask.
                if fn_parse and st.st_size > 0:
                    try:
                        if kind == "campaign_result":
                            txt = read_campaign_text(fp, st.st_size)
                        else:
                            with open(fp, "rb") as fh:
                                if st.st_size > PARSE_TAIL:
                                    fh.seek(st.st_size - PARSE_TAIL)
                                txt = fh.read().decode("utf-8", "replace")
                        res, ok, reason = fn_parse(txt)
                        jstate = by_id.get(jid, (None,)*5 + ("",))[4] if jid else ""
                        if kind == "campaign_result":
                            v, d = campaign_verdict_from_file(
                                cls, res, ok, reason, jstate or "", txt)
                        else:
                            v, d = verdict_from_file(
                                cls, res, ok, reason, jstate or "")
                        rec.update(verdict=v, detail=d,
                                   metrics_json=json.dumps(res, sort_keys=True))
                        stats["parsed"] += 1
                    except Exception as e:
                        rec["detail"] = f"parse error: {type(e).__name__}"
                results.append(rec)
            if a.limit and stats["walked"] > a.limit:
                break

    print(f"walk done in {time.time()-t0:.1f}s: {stats}", flush=True)
    mapped = (stats["by_jobid"] + stats.get("by_stepid", 0)
              + stats["by_mtime"] + stats["ambiguous"])
    tot = mapped + stats["unmapped"]
    print(f"  MAPPED {mapped}/{tot} = {100*mapped/max(tot,1):.1f}%", flush=True)
    if a.dry_run:
        print("DRY RUN — nothing written")
        return

    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'")
    con.execute("SET temp_directory='/data/lake/tmp'")
    for rows, outdir, label in ((results, OUT_RESULTS, "run_results"),
                                (health, OUT_HEALTH, "health_artifacts")):
        if not rows:
            continue
        os.makedirs(outdir, exist_ok=True)
        tmp = os.path.join(outdir, "_rows.ndjson")
        with open(tmp, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        dst = os.path.join(outdir, "part-000.parquet")
        next_dst = os.path.join(outdir, f".part-000.{os.getpid()}.parquet")
        con.execute(
            f"COPY (SELECT * FROM read_json('{tmp}', format='newline_delimited', "
            f"sample_size=-1, union_by_name=true)) TO '{next_dst}' "
            f"(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 6)")
        n = con.execute(f"SELECT count(*) FROM read_parquet('{next_dst}')").fetchone()[0]
        os.unlink(tmp)
        os.replace(next_dst, dst)
        print(f"WROTE {n} rows -> {dst} ({os.path.getsize(dst)/1024**2:.1f} MiB)")
        if n != len(rows):
            sys.exit(f"FATAL: {label} wrote {n} of {len(rows)} — not claiming success")


if __name__ == "__main__":
    main()
