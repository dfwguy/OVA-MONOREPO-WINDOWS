#!/usr/bin/env python3
"""lake_job_census — ONE PARQUET ROW FOR EVERY SLURM JOB. No exceptions.

The point of the lake was to log everything. Until now it logged only what a
browser happened to ask the rack-status app to parse, so 147,707 jobs produced
19,449 artifact rows and whole workload classes (MNUberGEMM, burn-in) were at
zero. This writes the census instead: who ran it, what it was, what it touched,
what happened, where the raw log is, and the numbers when a log exists.

WHY A TABLE AND NOT ARTIFACTS
    The artifact lane is one HTTP POST per run with the content inline. At
    147,707 jobs that is 147,707 POSTs and gigabytes of duplicated log text.
    A job census is a narrow, columnar fact table -- one row per job, the raw
    log referenced by PATH not by value -- which is what "show me every job on
    rack h03 that failed" actually needs to read.

WHAT IS AND IS NOT RECOVERABLE (state this plainly, do not paper over it)
    87,534 single-node NCCL jobs write their result to only 10,587 distinct
    paths: /cluster/bringup/results/<node>/<test>.txt is overwritten per node,
    last-write-wins, with older attempts rotated to .failN.txt. So EVERY job
    gets a census row -- id, owner, scope, state, timing, nodes, racks, log
    path -- but for roughly half of the single-node runs the result CONTENT was
    overwritten before anything could read it. That is recorded per row as
    result_status='overwritten', never as a pass and never as a blank.

    burnin-<node> IS MNUberGEMM: same sbatch script, different job name. Neither
    the job name nor any filename contains "mnubergemm", which is why both
    classes read 0% for weeks. Only SubmitLine spans the two naming eras, so
    SubmitLine is what classification keys on.

Everything is read from LOCAL disk. /cluster is an ext4 filesystem on this box
that we EXPORT to the head node; reading it over SSH sent every byte out and
back across NFS to our own disk.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

LAKE_ROOT = os.environ.get("LAKE_ROOT", "/data/lake")
OUT_DIR = os.path.join(LAKE_ROOT, "curated", "slurm_jobs")
LOG_DIR = os.environ.get("RACK_STATUS_LOG_DIR",
                         "/cluster/benchmark/harish/rack_status/logs")
BRINGUP = os.environ.get("BRINGUP_RESULTS", "/cluster/bringup/results")
SACCT = os.environ.get("RACK_SLURM_SACCT",
                       "/cm/local/apps/slurm/25.05/bin/sacct")
SLURM_CONF = os.environ.get(
    "SLURM_CONF", "/cm/shared/apps/slurm/etc/slurm/slurm.conf")
CLUSTER = os.environ.get("CLUSTER_NAME", "IREN_MKZ")

FIELDS = ("JobID,JobName,User,Account,Partition,State,ExitCode,Submit,Start,End,"
          "Elapsed,ElapsedRaw,NNodes,NCPUS,ReqTRES,NodeList,WorkDir,SubmitLine")

# Classification keys on SubmitLine first because JobName changed convention
# mid-campaign: July jobs are named for the script (allreduce.sbatch), August
# jobs are named bringup-<node> / burnin-<node>. SubmitLine spans both eras.
# Classification is SCRIPT-FIRST. Keyword matching on the whole SubmitLine
# misclassified job 147537 (su4-llama405b-fp8-1024) as "nccl", because a Llama
# submit line legitimately sets NCCL_* env vars — so "nccl" matched before
# "llama" ever got a chance. The sbatch script being executed is the actual
# statement of intent; env vars are decoration. Name is the tiebreak, generic
# keywords the last resort.
SCRIPT_CLASS = (
    (re.compile(r"mnubergemm|ubergemm", re.I), "mnubergemm"),
    (re.compile(r"llama|llm-pretrain", re.I), "llama"),
    (re.compile(r"nemo|nemotron", re.I), "nemo"),
    (re.compile(r"hpl", re.I), "hpl"),
    (re.compile(r"nvbandwidth|nvloom|clusterkit", re.I), "nvbandwidth"),
    (re.compile(r"allreduce|nccl|microbench", re.I), "nccl"),
)
# Order matters: most specific workload first, generic infrastructure last.
CLASS_RULES = (
    ("mnubergemm", re.compile(r"mnubergemm|ubergemm", re.I)),
    ("llama", re.compile(r"llama", re.I)),
    ("nemo", re.compile(r"nemo|nemotron", re.I)),
    ("hpl", re.compile(r"\bhpl\b", re.I)),
    ("nvbandwidth", re.compile(r"nvbandwidth|nvloom|clusterkit", re.I)),
    ("nccl", re.compile(r"nccl|allreduce|microbenchmark", re.I)),
    ("healthcheck", re.compile(r"health|bios|dmesg|ib-link|imex|preflight|gate|"
                               r"sysinfo|inventory|stage|image", re.I)),
    ("bringup", re.compile(r"bringup", re.I)),
)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=1800, **kw)


def classify(name: str, submitline: str) -> str:
    """Script first, then job name, then any keyword. See SCRIPT_CLASS."""
    for tok in re.findall(r"\S+\.(?:sbatch|sh|py)\b", submitline or ""):
        for rx, cls in SCRIPT_CLASS:
            if rx.search(tok):
                return cls
    for cls, rx in CLASS_RULES:
        if rx.search(name or ""):
            return cls
    for cls, rx in CLASS_RULES:
        if rx.search(submitline or ""):
            return cls
    return "other"


def result_path_from_submitline(sl: str, job_id: str = "") -> str | None:
    """--output=/cluster/bringup/results/<node>/<test>.txt names the result file."""
    m = re.search(r"--output=(\S+)", sl or "")
    if m:
        path = m.group(1)
        if job_id:
            path = path.replace("%j", job_id).replace("%J", job_id)
        return path
    m = re.search(r"RESULT_FILE=(\S+?)(?:,|\s|$)", sl or "")
    if not m:
        return None
    path = m.group(1)
    if job_id:
        path = path.replace("%j", job_id).replace("%J", job_id)
    return path


def scope_of(nodelist: str) -> tuple[list[str], list[str], int]:
    nodes = re.findall(r"example50-dh\d{2}-[a-z]\d+-\d+", nodelist or "")
    if not nodes and nodelist and nodelist not in ("None assigned", ""):
        exp = sh(["/cm/local/apps/slurm/25.05/bin/scontrol", "show", "hostnames",
                  nodelist], env=dict(os.environ, SLURM_CONF=SLURM_CONF))
        nodes = [n for n in exp.stdout.split() if n.startswith("example50")]
    racks = sorted({n.rsplit("-", 1)[0] for n in nodes})
    su_of = {"d": "SU1", "e": "SU2", "f": "SU3", "g": "SU4",
             "h": "SU5", "i": "SU6", "j": "SU7"}
    sus = sorted({su_of.get(r.split("-")[-1][0], "?") for r in racks})
    return racks, sus, len(nodes)


def index_logs() -> dict:
    """job_id -> [log paths]. One local scan; the job id is the rightmost
    4-7 digit run in the basename across all 89 observed filename patterns."""
    idx: dict[str, list[str]] = {}
    jid_re = re.compile(r"(\d{4,7})(?!.*\d{4,7})")
    for root in (LOG_DIR,):
        try:
            for f in os.listdir(root):
                m = jid_re.search(f)
                if m:
                    idx.setdefault(m.group(1), []).append(os.path.join(root, f))
        except OSError:
            pass
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-20")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    env = dict(os.environ, SLURM_CONF=SLURM_CONF)
    print(f"querying sacct since {a.since} (with -D: requeues are separate rows)",
          flush=True)
    r = sh([SACCT, "-D", "-a", "-X", "-S", a.since, "-P", "--delimiter=\x1f",
            f"--format={FIELDS}"], env=env)
    if r.returncode != 0:
        sys.exit(f"sacct failed: {r.stderr[:300]}")
    lines = r.stdout.splitlines()
    hdr = lines[0].split("\x1f")
    print(f"  sacct rows: {len(lines)-1}", flush=True)

    logs = index_logs()
    print(f"  log files indexed: {sum(len(v) for v in logs.values())} "
          f"across {len(logs)} job ids", flush=True)

    rows = []
    now = int(time.time())
    seen_attempt: dict[str, int] = {}
    # SubmitLine contains EMBEDDED NEWLINES, so one text line != one record.
    # Splitting per line dropped 2,216 of 3,021 rows; my first "fix" (fold on
    # field count) dropped more, because a wrapped SubmitLine can itself contain
    # the delimiter. The reliable boundary is structural: a NEW record always
    # begins with the JobID field, i.e. digits followed by the delimiter.
    # Everything else is a continuation of the previous record's SubmitLine.
    rec_start = re.compile(r"^\d+(?:[_.][^\x1f]*)?\x1f")
    records, buf = [], ""
    for raw in lines[1:]:
        if rec_start.match(raw):
            if buf:
                records.append(buf)
            buf = raw
        else:
            buf += " " + raw
    if buf:
        records.append(buf)
    print(f"  records reassembled: {len(records)}", flush=True)

    for rec in records:
        f = rec.split("\x1f")
        if len(f) < len(hdr):
            f = f + [""] * (len(hdr) - len(f))
        elif len(f) > len(hdr):
            # over-split: the tail belongs to the final field (SubmitLine)
            f = f[:len(hdr) - 1] + ["\x1f".join(f[len(hdr) - 1:])]
        d = dict(zip(hdr, f))
        jid = d.get("JobID", "")
        if not jid or not jid.split("_")[0].split(".")[0].isdigit():
            continue
        name, sl = d.get("JobName", ""), d.get("SubmitLine", "")
        cls = classify(name, sl)
        racks, sus, nnodes_real = scope_of(d.get("NodeList", ""))
        # Requeues: -D gives one row per attempt. Number them so no attempt is
        # silently collapsed into another.
        seen_attempt[jid] = seen_attempt.get(jid, 0) + 1
        rp = result_path_from_submitline(sl, jid)
        joblogs = logs.get(jid, [])
        # A bringup result path is shared by many jobs (last-write-wins), so its
        # presence does NOT mean this job's numbers survived.
        shared = bool(rp and rp.startswith(BRINGUP))
        if joblogs:
            status = "log_present"
        elif rp and os.path.exists(rp):
            status = "overwritten" if shared else "log_present"
        else:
            status = "no_log"
        try:
            el = int(d.get("ElapsedRaw") or 0)
        except ValueError:
            el = 0
        rows.append(dict(
            cluster=CLUSTER, job_id=jid, attempt=seen_attempt[jid],
            job_name=name, workload_class=cls,
            user=d.get("User", ""), account=d.get("Account", ""),
            partition=d.get("Partition", ""),
            state=(d.get("State", "") or "").split(" by")[0],
            state_full=d.get("State", ""), exit_code=d.get("ExitCode", ""),
            submit=d.get("Submit", ""), start=d.get("Start", ""),
            end=d.get("End", ""), elapsed=d.get("Elapsed", ""), elapsed_s=el,
            nnodes=d.get("NNodes", ""), ncpus=d.get("NCPUS", ""),
            req_tres=d.get("ReqTRES", ""), nodelist=d.get("NodeList", ""),
            nodes_json=json.dumps(sorted({n for n in re.findall(
                r"example50-dh\d{2}-[a-z]\d+-\d+", d.get("NodeList", ""))})),
            node_count=nnodes_real,
            racks_json=json.dumps(racks), rack_count=len(racks),
            sus_json=json.dumps(sus), su_count=len(sus),
            workdir=d.get("WorkDir", ""), submit_line=sl,
            result_path=rp or "", log_paths_json=json.dumps(joblogs),
            log_count=len(joblogs), result_status=status,
            captured_at=now,
        ))
        if a.limit and len(rows) >= a.limit:
            break

    # SELF-RECONCILE. A census that silently drops rows is worse than no census.
    # Compare against a JobID-only sacct in the SAME run (sacct is live data, so
    # a separately-timed query drifts by whatever started in between).
    tr = sh([SACCT, "-D", "-a", "-X", "-S", a.since, "-P", "--format=JobID",
             "--noheader"], env=env)
    truth = [x for x in tr.stdout.splitlines() if x.strip()]
    print(f"  census rows built: {len(rows)}   sacct truth: {len(truth)}", flush=True)
    if truth and abs(len(rows) - len(truth)) > max(5, len(truth) * 0.001):
        sys.exit(f"FATAL: built {len(rows)} rows but sacct says {len(truth)} — "
                 f"refusing to publish a census with unexplained drops")
    import collections
    print("  by class :", dict(collections.Counter(r["workload_class"] for r in rows)))
    print("  by status:", dict(collections.Counter(r["result_status"] for r in rows)))
    print("  by state :", dict(collections.Counter(r["state"] for r in rows).most_common(6)))
    if a.dry_run:
        print("DRY RUN — nothing written")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'")
    con.execute("SET temp_directory='/data/lake/tmp'")
    tmp = os.path.join(OUT_DIR, "_census.ndjson")
    with open(tmp, "w") as fh:
        for r_ in rows:
            fh.write(json.dumps(r_) + "\n")
    dst = os.path.join(OUT_DIR, "part-000.parquet")
    next_dst = os.path.join(OUT_DIR, f".part-000.{os.getpid()}.parquet")
    # Declare the schema. Type INFERENCE from a sample fails on row 79,563:
    # sacct fields are free text and a column that looks numeric for 79k rows
    # (ncpus, elapsed_s) can arrive empty or non-numeric later. An explicit
    # contract also means the table's shape is reviewable here rather than
    # being whatever the first N rows implied.
    COLS = {
        "cluster": "VARCHAR", "job_id": "VARCHAR", "attempt": "INTEGER",
        "job_name": "VARCHAR", "workload_class": "VARCHAR", "user": "VARCHAR",
        "account": "VARCHAR", "partition": "VARCHAR", "state": "VARCHAR",
        "state_full": "VARCHAR", "exit_code": "VARCHAR", "submit": "VARCHAR",
        "start": "VARCHAR", "end": "VARCHAR", "elapsed": "VARCHAR",
        "elapsed_s": "BIGINT", "nnodes": "VARCHAR", "ncpus": "VARCHAR",
        "req_tres": "VARCHAR", "nodelist": "VARCHAR", "nodes_json": "VARCHAR",
        "node_count": "INTEGER", "racks_json": "VARCHAR", "rack_count": "INTEGER",
        "sus_json": "VARCHAR", "su_count": "INTEGER", "workdir": "VARCHAR",
        "submit_line": "VARCHAR", "result_path": "VARCHAR",
        "log_paths_json": "VARCHAR", "log_count": "INTEGER",
        "result_status": "VARCHAR", "captured_at": "BIGINT",
    }
    colspec = ", ".join(f"'{k}': '{v}'" for k, v in COLS.items())
    con.execute(
        f"COPY (SELECT * FROM read_json('{tmp}', format='newline_delimited', "
        f"columns={{{colspec}}})) "
        f"TO '{next_dst}' (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 6)")
    n = con.execute(f"SELECT count(*) FROM read_parquet('{next_dst}')").fetchone()[0]
    os.unlink(tmp)
    os.replace(next_dst, dst)
    print(f"WROTE {n} rows -> {dst} "
          f"({os.path.getsize(dst)/1024**2:.1f} MiB)", flush=True)
    if n != len(rows):
        sys.exit(f"FATAL: wrote {n} but built {len(rows)} — refusing to claim success")


def _has_pandas() -> bool:
    try:
        import pandas  # noqa
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
