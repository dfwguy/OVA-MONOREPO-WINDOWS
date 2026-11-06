#!/usr/bin/env python3
"""lake_run_backfill — put EVERY validation run into the Parquet lake.

WHY THIS EXISTS
---------------
Run capture used to be a side effect of HTTP traffic to the rack-status app:
a run was recorded only if (a) it wrote an aggregated result log into one
watched directory, (b) something made an HTTP request that caused THAT log to
be parsed by the universal parser, and (c) an unsupervised `nohup` scan loop
happened to be alive. That loop died on 2026-08-07 and nobody noticed for six
days. Measured coverage on 2026-08-13:

    NEMO         70/72   97%
    NCCL        130/358  36%      (137 runs had no lake row at all)
    Llama-405B   26/66   39%      (0 of 3 at the 1024-GPU tier)
    MNUberGEMM    0/8     0%
    burn-in       0/2883  0%

The two best numbers ever produced on this cluster -- 147437 at 2577.7 and
147537 at 2596.4 TFLOP/s/GPU -- existed only as files on the head node.

This ingester inverts the dependency. Slurm is the source of truth for "a run
happened"; the head-node log is the source of truth for "here is what it did".
Neither depends on a UI, a browser, or a shell loop staying alive. Anything
sacct knows about gets ingested, whoever launched it and however it was
launched.

DESIGN RULES
    * IDEMPOTENT. run_id is derived from the Slurm job id, so re-running is
      safe and cheap; already-present runs are skipped, not duplicated.
    * NEVER DELETES. It only reads logs and POSTs. The lake dedups on
      (artifact_path, sha256) within a run_id.
    * A PARSE FAILURE IS RECORDED, NOT SWALLOWED. A run whose log cannot be
      parsed is still ingested, with parse_ok=false and the reason, because
      "we have no result for this run" is itself the finding. Blank never
      means healthy.
    * -D ON EVERY sacct CALL. Without it, requeued runs are hidden: job 147437
      is NODE_FAIL then COMPLETED and only -D shows both.

Usage:
    lake_run_backfill.py --since 2026-07-20            # backfill
    lake_run_backfill.py --since 2026-08-13 --dry-run  # show, write nothing
    lake_run_backfill.py --watch                       # continuous
"""
from __future__ import annotations
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

LAKE_URL = os.environ.get("LAKE_ARTIFACT_URL", "http://127.0.0.1:9410/v1/artifacts")
CLUSTER = os.environ.get("CLUSTER_NAME", "IREN_MKZ")
SSH_HOST = os.environ.get("RACK_SSH_HOST", "192.0.2.2")
SSH_USER = os.environ.get("RACK_SSH_USER", "cmods")
SSH_KEY = os.environ.get("RACK_SSH_KEY", "/home/nvis/.ssh/id_bcm")
LOG_DIR = os.environ.get("RACK_STATUS_LOG_DIR",
                         "/cluster/benchmark/harish/rack_status/logs")
BURNIN_DIR = os.environ.get("BURNIN_RESULTS_DIR", "/cluster/bringup/results")
# Large multi-SU runs do NOT write into LOG_DIR at all. Each one gets its own
# report directory whose name ends in the job id -- NCCLALL175093,
# llama405b_..._20260817T221400Z with rank-logs/ inside. Scanning only LOG_DIR
# filed every one of them as "no log on head node": jobs 175062-175093, the
# entire 7,168- and 7,612-rank campaign, sat in the lake as empty ERROR rows
# while their .raw files held clean results on disk.
REPORT_ROOT = os.environ.get("RACK_REPORT_ROOT", "/cluster/benchmark/harish/xxx")
STATE = os.environ.get("BACKFILL_STATE", "/data/lake/_state/run_backfill.json")
# ABSOLUTE PATH. cron runs with an empty environment and no PATH, so a bare
# "sacct" raises FileNotFoundError there while working perfectly in an
# interactive shell -- caught only by testing under `env -i`.
SACCT = os.environ.get("RACK_SLURM_SACCT",
                       "/cm/local/apps/slurm/25.05/bin/sacct")
SLURM_CONF = os.environ.get(
    "SLURM_CONF", "/cm/shared/apps/slurm/etc/slurm/slurm.conf")

# A complete NCCL sweep concludes 24 collectives. Fewer means the run died
# early: its numbers are real but its coverage is not, and the two must never
# be reported as the same thing.
FULL_SWEEP = 24

# A job is only "done" once Slurm says it reached one of these.
TERMINAL_STATES = ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL",
                   "OUT_OF_MEMORY", "BOOT_FAIL", "PREEMPTED", "DEADLINE")

# Jobs that legitimately produce no benchmark result: image staging, preflight
# gates, environment checks. Recording these as ERROR drowns the runs that are
# genuinely missing data, which is the whole signal this tool exists to give.
HELPER_RE = re.compile(
    r"image-stage|image-ib-gate|runtime-gate|preflight|replacements|stage-", re.I)

CLASSES = (
    ("nccl", re.compile(r"nccl|microbenchmark", re.I)),
    ("llama", re.compile(r"llama", re.I)),
    ("nemo", re.compile(r"nemo|nemotron", re.I)),
    ("mnubergemm", re.compile(r"mnu|bergemm", re.I)),
    ("burnin", re.compile(r"^burnin-", re.I)),
)


def classify(name: str) -> str | None:
    for cls, rx in CLASSES:
        if rx.search(name or ""):
            return cls
    return None


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600, **kw)


# /cluster IS LOCAL ON THIS BOX. The ObsVM exports it (/etc/exports:
# "/cluster 192.0.2.3/16") off its own /dev/nvme2n1; the head node is an NFS
# *client* of us. Reading these logs by SSHing to the head node sent every byte
# out to the head, back across NFS, and into our own local disk -- double the
# network cost, and it put the head node's NFS client in the path of our bulk
# reads on a box already under provisioning pressure. Read the local path.
LOCAL_ROOTS = ("/cluster",)


def read_log(path: str, tail_bytes: int = 0) -> str:
    """Read a run log from the LOCAL filesystem. No SSH, no NFS round trip."""
    try:
        if tail_bytes:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                fh.seek(max(0, fh.tell() - tail_bytes))
                return fh.read().decode("utf-8", "replace")
        with open(path, "r", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def list_logs(log_dir: str) -> list[str]:
    try:
        return sorted(os.listdir(log_dir))
    except OSError:
        return []


# The wrapper log in LOG_DIR is not always the log with the numbers in it.
# Up to 2026-08-14 the NEMO harness ran training inline, so the wrapper held the
# `Step Time ... MODEL_TFLOP/s/GPU` lines and parsing it was correct. The
# Nemotron-H harness instead hands the work to `srun --output <experiments
# path>`, leaving the wrapper with only the sbatch trace -- 5.8 KB of `+ export`
# lines and `job exited with code 0`. Parsing that yields "no TFLOP or step-time
# lines", so EVERY NEMO run after 2026-08-14 landed parse_ok=false / verdict
# ERROR while the training logs recorded a clean ~1975 TFLOP/s. The run had not
# failed; we were reading the wrong file. Follow the delegation.
SRUN_OUT_RE = re.compile(r"--output[= ]+(\S+)")


def resolve_delegated_log(txt: str, jid: str) -> str:
    """Path the wrapper delegated its real output to, or "" if it did not.

    `%j` is Slurm's job-id token; `${SLURM_RESTART_COUNT:-0}` survives
    unexpanded in the un-traced copy of the command. Both are globbed rather
    than assumed, so a requeued run resolves to its latest attempt instead of
    silently missing (see the requeue trap in sacct without -D).
    """
    for raw in dict.fromkeys(SRUN_OUT_RE.findall(txt or "")):
        pat = raw.replace("%j", str(jid))
        pat = re.sub(r"\$\{SLURM_RESTART_COUNT:-\d+\}", "*", pat)
        hits = [p for p in glob.glob(pat) if os.path.isfile(p)]
        if hits:
            # Latest attempt wins: a requeued job writes one file per restart.
            return max(hits, key=os.path.getmtime)
    return ""


def _report_dir_for(jid: str) -> str:
    """The report directory that BELONGS to this job, or "".

    Matching the directory NAME on the job id is wrong and dangerous: these
    dirs are timestamp-named and often cite a *reference* job, so
    llama405b_..._exact175064_...T221400Z is job 175085's directory but
    contains the string 175064. Globbing `*175064*` would hand job 175064 the
    Llama run's logs. Identify the owner by a file the job itself wrote --
    slurm-<jid>.out/.err, attempt-<jid>.*, or its own rank-logs.
    """
    pats = [f"*/slurm-{jid}.out", f"*/slurm-{jid}.err", f"*/attempt-{jid}.*",
            f"*/rank-logs/*-{jid}-*"]
    hits = []
    for pat in pats:
        for f in glob.glob(os.path.join(REPORT_ROOT, pat)):
            d = os.path.dirname(f)
            if os.path.basename(d) == "rank-logs":
                d = os.path.dirname(d)
            hits.append(d)
    if not hits:
        return ""
    # Newest wins if a job somehow touched two dirs (retries reuse a tree).
    return max(set(hits), key=os.path.getmtime)


def report_dir_logs(jid: str, cls: str) -> tuple[str, str]:
    """(label, text) for a job's own report directory, or ("", "").

    NCCL sweeps write one .raw per collective (test-1-all_reduce-8k-32g.raw ...).
    They are CONCATENATED: parse_nccl already walks multiple "Collective test
    concluded" blocks, so one merged parse yields busbw per collective and a
    correct collective count. A collective killed before it concluded simply
    does not appear -- which is the honest outcome, not a zero.

    Llama/NeMo write per-rank logs; only global rank 0 prints the perf table,
    and that is the file whose name ends -0.out.
    """
    d = _report_dir_for(jid)
    if not d:
        return "", ""
    if cls in ("llama", "nemo"):
        hits = sorted(glob.glob(os.path.join(d, "rank-logs", f"*-{jid}-*-0.out")))
        if hits:
            return os.path.relpath(hits[0], REPORT_ROOT), read_log(hits[0])
    raws = sorted(r for r in glob.glob(os.path.join(d, "*.raw"))
                  if not r.endswith(".live.log"))
    if not raws:
        return "", ""
    txt = "\n".join(read_log(r) for r in raws)
    names = "+".join(os.path.basename(r) for r in raws) if len(raws) <= 6 \
        else f"{len(raws)} raws"
    return os.path.basename(d) + "/" + names, txt


def ssh(script: str) -> str:
    r = sh(["ssh", "-i", SSH_KEY, "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no", f"{SSH_USER}@{SSH_HOST}", script])
    return r.stdout


def jobs_since(since: str) -> dict:
    """Every benchmark job Slurm knows about. -D or requeued runs vanish."""
    env = dict(os.environ, SLURM_CONF=SLURM_CONF)
    r = sh([SACCT, "-D", "-a", "-X", "-S", since, "-P",
            "--format=JobID,JobName,User,NNodes,State,Start,End,Elapsed,NodeList"],
           env=env)
    if r.returncode != 0:
        sys.exit(f"sacct failed: {r.stderr[:300]}")
    out = {}
    for line in r.stdout.splitlines()[1:]:
        f = line.split("|")
        if len(f) < 9:
            continue
        jid, name = f[0], f[1]
        cls = classify(name)
        if not cls or not jid.isdigit():
            continue
        prev = out.get(jid)
        # Requeued: keep the LAST attempt, which is the one that stuck.
        if prev and prev["start"] > f[5]:
            continue
        racks = sorted({m for m in re.findall(r"example50-dh01-([a-z]\d+)-", f[8])})
        out[jid] = dict(job_id=jid, name=name, cls=cls, user=f[2], nnodes=f[3],
                        state=f[4], start=f[5], end=f[6], elapsed=f[7],
                        nodelist=f[8], racks=racks)
    return out


# --------------------------------------------------------------------------- #
# Parsers — one per workload. Each returns (result_dict, parse_ok, reason).
# Patterns are taken from real logs, quoted in the docstrings so the next
# person can find the source line without guessing.
# --------------------------------------------------------------------------- #
# nccl-tests rounds the message size DOWN to a multiple of the rank count for
# alltoall / all_gather / reduce_scatter, so "16 GiB" is 17,179,869,184 B only
# when the ranks divide it evenly. At 5,120 ranks it is 17,179,852,800 and at
# 7,612 ranks 17,179,857,728. Matching the exact constant silently skipped the
# busbw for three of five collectives on every wide run.
_GIB16 = 17179869184


def _is_16gib(tok: str) -> bool:
    try:
        v = int(tok)
    except ValueError:
        return False
    return _GIB16 * 0.999 <= v <= _GIB16


def parse_nccl(txt: str) -> tuple[dict, bool, str]:
    """busbw at 16 GiB OUT-OF-PLACE, per collective, plus correctness.

    The acceptance metric is the 16 GiB out-of-place busbw column, NOT the
    '# Avg bus bandwidth' line, which averages every message size and reads
    ~7x lower. Correctness comes from '# Out of bounds values : N OK|FAILED';
    a run can exit 0 and still be wrong (job 147392 wrote 2560 bad values).
    """
    colls, cur = [], None
    for line in txt.splitlines():
        m = re.match(r"#\s*Collective test concluded:\s*(\S+)", line)
        if m and cur is not None:
            cur["name"] = m.group(1).replace("_perf_mpi", "")
            colls.append(cur)
            cur = None
            continue
        mo = re.match(r"#\s*Out of bounds values\s*:\s*(\d+)\s*(\S+)", line)
        if mo:
            cur = cur or {}
            cur["oob"] = int(mo.group(1))
            cur["verdict"] = mo.group(2)
            continue
        p = line.split()
        if len(p) >= 13 and _is_16gib(p[0]):
            cur = cur or {}
            try:
                cur["busbw_16gib_oop"] = float(p[7])
                cur["wrong_oop"] = p[8]
            except (ValueError, IndexError):
                pass
    if not colls:
        return {}, False, "no collective concluded"
    bad = [c for c in colls if c.get("verdict") not in ("OK", None)]
    bw = {}
    for c in colls:
        n = c.get("name")
        if n and c.get("busbw_16gib_oop") is not None:
            bw[n] = max(bw.get(n, 0.0), c["busbw_16gib_oop"])
    # Cause vs consequence: 'unhandled cuda error' means THIS node's CUDA
    # context died; 'remote process exited' means a peer died and this node
    # noticed. Counting both named 4 healthy trays as faulty on job 147393.
    cause = sorted(set(re.findall(
        r"^(example50-dh01-[a-z]\d+-\d+): Test NCCL failure [a-z_]+\.cu:\d+ "
        r"'(?:unhandled cuda error|internal error|invalid usage|Cuda failure)",
        txt, re.M)))
    return (dict(collectives=len(colls), failed_collectives=len(bad),
                 busbw=bw, fault_nodes=cause), True,
            "")


def parse_llama_nemo(txt: str) -> tuple[dict, bool, str]:
    """TFLOP/s/GPU and step time. Real line shape:

        Step Time : 56.85s GPU utilization: 2182.4MODEL_TFLOP/s/GPU[Rank 640]
        iteration  50/50 | ... elapsed time per iteration (ms): 47550.8 | ...

    Mean is taken over iterations 6-50, dropping the first five as warm-up —
    the same window the existing exemplar artifacts declare, so numbers stay
    comparable to what is already published.
    """
    def _f(pat):
        out = []
        for x in re.findall(pat, txt):
            try:
                out.append(float(x))
            except ValueError:
                continue
        return out
    tf = _f(r"GPU utilization:\s*([0-9.]+)MODEL_TFLOP")
    st = _f(r"elapsed time per iteration \(ms\):\s*([0-9.]+)")
    iters = re.findall(r"iteration\s+(\d+)/\s*(\d+)", txt)
    nan = re.search(r"number of nan iterations:\s*(\d+)", txt)
    tf = [x for x in tf if x > 100]
    if not tf and not st:
        return {}, False, "no TFLOP or step-time lines"
    w_tf = sorted(tf)[len(tf) // 10:] if len(tf) > 10 else tf
    w_st = st[5:] if len(st) > 5 else st
    res = dict(
        iterations=int(iters[-1][0]) if iters else None,
        iterations_target=int(iters[-1][1]) if iters else None,
        nan_iterations=int(nan.group(1)) if nan else None,
    )
    if w_tf:
        res["tflops_per_gpu_median"] = round(sorted(w_tf)[len(w_tf) // 2], 2)
        res["tflops_per_gpu_mean"] = round(sum(w_tf) / len(w_tf), 2)
    if w_st:
        res["step_time_s_mean"] = round(sum(w_st) / len(w_st) / 1000, 4)
    return res, True, ""


def parse_mnubergemm(txt: str) -> tuple[dict, bool, str]:
    """GFlops plus fault classes.

    QUAL_RUNTIME_ERROR is NOT a synonym for Xid. Both are recorded separately
    because reporting an induced runtime error as 'GPU Xid - hardware fault'
    invents a hardware diagnosis for a different failure.
    """
    # GFlops values are scientific notation, e.g. "GFlops:6.1224e+05". A naive
    # [0-9.e+]+ class truncates at the exponent and float() then raises.
    gf = []
    for x in re.findall(r"GFlops:\s*([-+0-9.]+(?:[eE][-+]?\d+)?)", txt):
        try:
            gf.append(float(x))
        except ValueError:
            continue
    xids = sorted({int(x) for x in re.findall(r"Xid detected (\d+)", txt)})
    ind = sorted({int(x) for x in
                  re.findall(r"QUAL_RUNTIME_ERROR \(induced by (\d+)\)", txt)})
    if not gf and not xids and not ind:
        return {}, False, "no GFlops or fault lines"
    res = dict(samples=len(gf), xids=xids, induced_codes=ind,
               fault=("xid" if xids else ("qual_error" if ind else None)))
    if gf:
        s = sorted(gf)
        res.update(gflops_median=s[len(s) // 2], gflops_min=s[0], gflops_max=s[-1])
    return res, True, ""


PARSERS = {"nccl": parse_nccl, "llama": parse_llama_nemo,
           "nemo": parse_llama_nemo, "mnubergemm": parse_mnubergemm,
           # burn-in output IS mnubergemm output — same GFlops/Xid/QUAL lines,
           # just written per-tray by the fleet burn-in wrapper.
           "burnin": parse_mnubergemm}


def verdict_for(cls: str, res: dict, state: str) -> tuple[str, str]:
    """PASS requires completion AND correctness AND full coverage."""
    base = (state or "").split(" by")[0].strip().upper()
    terminal_bad = base in ("NODE_FAIL", "FAILED", "CANCELLED", "TIMEOUT",
                            "OUT_OF_MEMORY", "BOOT_FAIL")
    if cls == "nccl":
        if not res:
            return "ERROR", "no collective completed"
        if res.get("failed_collectives"):
            return "FAIL", (f"{res['failed_collectives']}/{res['collectives']} "
                            f"collectives wrong")
        n = res.get("collectives", 0)
        if terminal_bad:
            return "PARTIAL", f"{n}/{FULL_SWEEP} collectives, Slurm says {base}"
        if n < FULL_SWEEP:
            return "PARTIAL", f"only {n}/{FULL_SWEEP} collectives"
        return "PASS", f"{n} collectives, 0 wrong"
    if cls in ("llama", "nemo"):
        if not res:
            return "ERROR", "no performance lines"
        it, tgt = res.get("iterations"), res.get("iterations_target")
        if res.get("nan_iterations"):
            return "FAIL", f"{res['nan_iterations']} nan iterations"
        if terminal_bad:
            return "PARTIAL", f"Slurm says {base}"
        if it and tgt and it < tgt:
            return "PARTIAL", f"{it}/{tgt} iterations"
        return "PASS", f"{it}/{tgt} iterations" if it else "completed"
    if cls == "mnubergemm":
        if res.get("fault") == "xid":
            return "FAIL", f"Xid {res.get('xids')}"
        if res.get("fault") == "qual_error":
            return "FAIL", f"QUAL_RUNTIME_ERROR induced by {res.get('induced_codes')}"
        return ("PASS", "no faults") if res else ("ERROR", "no data")
    return "UNKNOWN", ""


def push(run: dict, log_name: str, log_text: str, res: dict, ok: bool,
         reason: str, verdict: str, detail: str, dry: bool) -> bool:
    body = json.dumps(dict(
        run_id=f"{CLUSTER}-backfill-{run['cls']}-{run['job_id']}",
        cluster=CLUSTER, job_id=run["job_id"], harness=run["cls"],
        capture_kind="run", source_host=SSH_HOST,
        captured_by="lake_run_backfill", fixture=False,
        captured_at=int(time.time()),
        resolve_context={"slurm_state": run["state"], "nnodes": run["nnodes"],
                         "racks": ",".join(run["racks"]),
                         "start": run["start"], "end": run["end"],
                         "elapsed": run["elapsed"], "job_name": run["name"]},
        artifacts=[{
            "artifact_path": f"synthesized:result-{run['cls']}-{run['job_id']}.json",
            "artifact_type": "parsed_result", "encoding": "utf8",
            "content": json.dumps(dict(
                job_id=run["job_id"], job_name=run["name"], workload=run["cls"],
                nnodes=int(run["nnodes"]) if str(run["nnodes"]).isdigit() else None,
                racks=run["racks"], slurm_state=run["state"],
                start=run["start"], end=run["end"], elapsed=run["elapsed"],
                verdict=verdict, detail=detail,
                parse_ok=ok, parse_error=reason,
                source_log=log_name, result=res), sort_keys=True),
        }]), sort_keys=True)
    if dry:
        return True
    req = urllib.request.Request(LAKE_URL, data=body.encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status < 300
    except Exception as e:
        print(f"  PUSH FAILED {run['job_id']}: {str(e)[:120]}", flush=True)
        return False


def load_state() -> dict:
    try:
        return json.load(open(STATE))
    except Exception:
        return {"done": {}}


def save_state(st: dict):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh)
    os.replace(tmp, STATE)


def run_once(since: str, dry: bool, force: bool = False) -> dict:
    jobs = jobs_since(since)
    st = load_state()
    done = set() if force else set(st.get("done", {}))
    todo = {j: r for j, r in jobs.items() if j not in done}
    print(f"slurm jobs since {since}: {len(jobs)}   already ingested: "
          f"{len(jobs) - len(todo)}   to do: {len(todo)}", flush=True)
    if not todo:
        return {"ingested": 0, "skipped": len(jobs)}

    # One remote listing for every job at once — 2,000 SSH round trips would
    # be exactly the head-node session storm this deployment already suffers.
    all_files = list_logs(LOG_DIR)
    by_job: dict[str, list[str]] = {}
    jid_re = re.compile(r"(\d{4,7})(?!.*\d{4,7})")
    for f in all_files:
        m = jid_re.search(f)
        if m and m.group(1) in todo:
            by_job.setdefault(m.group(1), []).append(f)

    # Prefer the log that actually carries results, per workload.
    PREF = {
        # The third pattern is the catch-all for harness-named runs such as
        # su6-nccl-fp8-1024-meta-fixed-148463.out. Without it the first two
        # (llmb-only, and .txt-only with a capital NCCL) matched nothing, and a
        # complete 24-collective 2.3 MB log was filed as "no parseable log" --
        # the SU6/SU7 1024-GPU sweeps were invisible for exactly this reason.
        # Keep it LAST: the specific names stay preferred when both exist.
        "nccl": [r"^llmb-nccl_nodes_\d+\.out$", r"NCCL.*\.txt$",
                 r"nccl.*\.(out|txt|log)$"],
        "llama": [r"^llama405b-train-\d+\.out$", r"llama.*\.out$"],
        "nemo": [r"NEMO.*\.txt$", r"^llmb-nemo.*\.log$", r"nemo.*\.out$"],
        "mnubergemm": [r"mnubergemm.*\.(txt|out)$", r"MNU.*\.txt$"],
    }
    counts = {"ingested": 0, "no_log": 0, "parse_fail": 0, "push_fail": 0}
    verdicts: dict[str, int] = {}
    for jid, run in sorted(todo.items()):
        files = by_job.get(jid, [])
        pick = None
        # Set by any branch that has ALREADY parsed its own text. Without it the
        # trailing `else` re-reads LOG_DIR/<pick> -- a path that does not exist
        # for report-dir or burn-in payloads -- and silently replaces a good
        # result with "no collective concluded". That is why 175062-175093
        # ingested with the right source_log and null busbw.
        handled = False
        for rx in PREF.get(run["cls"], []):
            for f in files:
                if re.search(rx, f):
                    pick = f
                    break
            if pick:
                break
        if not pick and run["cls"] == "burnin":
            # burn-in writes one rolling file per TRAY, keyed by node name in the
            # job name (burnin-example50-dh01-e17-30), not by job id in the log dir.
            node = run["name"].replace("burnin-", "").strip()
            txt = read_log(os.path.join(BURNIN_DIR, node,
                                        "mnubergemm-run1.txt"), tail_bytes=200_000)
            if txt.strip():
                res, ok, reason = parse_mnubergemm(txt)
                verdict, detail = verdict_for("mnubergemm", res, run["state"])
                pick = f"{node}/mnubergemm-run1.txt"
                handled = True
                if not ok:
                    counts["parse_fail"] += 1
        if not pick:
            # No log in LOG_DIR - the run may own a report directory instead.
            label, rtxt = report_dir_logs(jid, run["cls"])
            if rtxt.strip():
                res, ok, reason = PARSERS[run["cls"]](rtxt)
                verdict, detail = verdict_for(
                    "mnubergemm" if run["cls"] == "burnin" else run["cls"],
                    res, run["state"])
                pick = label
                handled = True
                counts["report_dir"] = counts.get("report_dir", 0) + 1
                if not ok:
                    counts["parse_fail"] += 1
        if not pick:
            # Record the run anyway: "this run left no parseable log" is a
            # finding, and a silently missing row is how we got here.
            helper = bool(HELPER_RE.search(run["name"]))
            ok, reason, res = False, ("no log on head node" if not files
                                      else f"no parseable log among {len(files)}"), {}
            verdict = "NO_RESULT_EXPECTED" if helper else "ERROR"
            detail = ("staging/preflight helper job, no benchmark result by design"
                      if helper else reason)
            counts["no_log"] += 1
        elif not handled:
            txt = read_log(os.path.join(LOG_DIR, pick))
            res, ok, reason = PARSERS[run["cls"]](txt)
            if not ok:
                # Wrapper carried no numbers -- it may only be a launcher.
                alt = resolve_delegated_log(txt, jid)
                if alt:
                    atxt = read_log(alt)
                    if atxt.strip():
                        ares, aok, areason = PARSERS[run["cls"]](atxt)
                        if aok:
                            # Record the file actually parsed, not the wrapper,
                            # so source_log stays checkable by a human.
                            res, ok, reason, pick = ares, aok, areason, alt
                            counts["delegated"] = counts.get("delegated", 0) + 1
            verdict, detail = verdict_for(
                "mnubergemm" if run["cls"] == "burnin" else run["cls"],
                res, run["state"])
            if not ok:
                counts["parse_fail"] += 1
        if push(run, pick or "", "", res, ok, reason, verdict, detail, dry):
            counts["ingested"] += 1
            verdicts[verdict] = verdicts.get(verdict, 0) + 1
            # Only a TERMINAL job is done. Marking a RUNNING one done freezes
            # its snapshot forever: 175064 and 175093 were still reading
            # slurm_state=RUNNING hours after they finished, because the first
            # ingest claimed them and nothing ever revisited them.
            base = (run["state"] or "").split(" by")[0].strip().upper()
            if not dry and base in TERMINAL_STATES:
                st.setdefault("done", {})[jid] = {"verdict": verdict,
                                                  "at": int(time.time())}
        else:
            counts["push_fail"] += 1
    if not dry:
        save_state(st)
    print(f"  {counts}   verdicts={verdicts}", flush=True)
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-20")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="re-ingest even if state says done")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=600)
    a = ap.parse_args()
    if a.watch:
        while True:
            try:
                run_once(a.since, a.dry_run)
            except Exception as e:
                print(f"cycle error: {type(e).__name__}: {e}", flush=True)
            time.sleep(a.interval)
    else:
        run_once(a.since, a.dry_run, a.force)


if __name__ == "__main__":
    main()
