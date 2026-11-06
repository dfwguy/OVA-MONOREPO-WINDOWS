#!/usr/bin/env python3
"""ask — one place to ask the lake a question.

The lake had three tables in three shapes and answering "what did rack h03 do"
meant knowing which parquet to open and how to join it. This wraps that:

    ask.py node example50-dh01-h03-14      everything that ever ran on a tray
    ask.py rack h03                     every job that touched a rack
    ask.py job 147537                   one job, with its results
    ask.py best nccl                    best measured busbw per SU
    ask.py best llama                   best TFLOP/s per SU
    ask.py failures --since 2026-08-12  what failed, and where
    ask.py coverage                     how much of the fleet we actually have
    ask.py sql "SELECT ..."             raw DuckDB over jobs/results/health

Tables (all local parquet, no service required):
    jobs    one row per Slurm job          /data/lake/curated/slurm_jobs
    results one row per result FILE        /data/lake/curated/run_results
    health  one row per health artifact    /data/lake/curated/health_artifacts

A note on joins that matters: `results.job_id` is EMPTY for files whose job
could not be identified. 73,281 bringup files had their mtimes flattened by a
bulk copy on 2026-08-09, so their attribution is unrecoverable -- but their
numbers are intact and they are still keyed by (node, test). Query by node when
you want measurements; query by job_id when you need provenance. Do not treat an
empty job_id as "no data".
"""
from __future__ import annotations
import json
import sys

import duckdb

L = "/data/lake/curated"
VIEWS = f"""
CREATE OR REPLACE VIEW jobs AS SELECT * FROM read_parquet('{L}/slurm_jobs/*.parquet');
CREATE OR REPLACE VIEW results AS SELECT * FROM read_parquet('{L}/run_results/*.parquet');
CREATE OR REPLACE VIEW health AS SELECT * FROM read_parquet('{L}/health_artifacts/*.parquet');
"""


def con():
    c = duckdb.connect()
    c.execute("SET memory_limit='4GB'")
    for stmt in VIEWS.strip().split(";"):
        if stmt.strip():
            c.execute(stmt)
    return c


def show(rows, hdr):
    if not rows:
        print("  (nothing)")
        return
    w = [max(len(str(h)), max(len(str(r[i])[:44]) for r in rows))
         for i, h in enumerate(hdr)]
    print("  " + " | ".join(str(h).ljust(w[i]) for i, h in enumerate(hdr)))
    print("  " + "-+-".join("-" * x for x in w))
    for r in rows:
        print("  " + " | ".join(str(v)[:44].ljust(w[i]) for i, v in enumerate(r)))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    c = con()

    if cmd == "node":
        n = args[0]
        show(c.execute("""SELECT job_id, job_name, workload_class, state, start,
              elapsed FROM jobs WHERE nodes_json LIKE ? ORDER BY start DESC LIMIT 40""",
              [f"%{n}%"]).fetchall(),
             ["job", "name", "class", "state", "start", "elapsed"])
        print(f"\n  measured results on {n}:")
        show(c.execute("""SELECT test, workload, verdict, map_method,
              strftime(to_timestamp(mtime),'%Y-%m-%d %H:%M') AS when_,
              substr(metrics_json,1,60) FROM results WHERE node = ?
              AND metrics_json NOT IN ('','{}') ORDER BY mtime DESC LIMIT 25""",
              [n]).fetchall(),
             ["test", "workload", "verdict", "mapped_by", "when", "metrics"])

    elif cmd == "rack":
        r = args[0]
        show(c.execute("""SELECT workload_class, state, count(*) n,
              min(start) first_seen, max(start) last_seen FROM jobs
              WHERE racks_json LIKE ? GROUP BY 1,2 ORDER BY n DESC LIMIT 25""",
              [f'%"{r}"%']).fetchall(),
             ["class", "state", "jobs", "first", "last"])

    elif cmd == "job":
        j = args[0]
        show(c.execute("""SELECT job_id, attempt, job_name, user, workload_class,
              state, start, elapsed, node_count, rack_count, sus_json
              FROM jobs WHERE job_id = ? ORDER BY attempt""", [j]).fetchall(),
             ["job", "try", "name", "user", "class", "state", "start", "elapsed",
              "nodes", "racks", "sus"])
        print("\n  result files:")
        show(c.execute("""SELECT artifact_name, node, verdict, map_method,
              substr(metrics_json,1,70) FROM results WHERE job_id = ? LIMIT 20""",
              [j]).fetchall(),
             ["file", "node", "verdict", "mapped_by", "metrics"])

    elif cmd == "best":
        what = args[0] if args else "nccl"
        if what == "nccl":
            # busbw at 16 GiB out-of-place is the acceptance metric; the
            # "Avg bus bandwidth" line averages every message size and reads ~7x low.
            show(c.execute("""SELECT j.sus_json su, r.job_id, j.node_count nodes,
                  round(CAST(json_extract(r.metrics_json,'$.busbw.all_reduce') AS DOUBLE),2) all_reduce,
                  round(CAST(json_extract(r.metrics_json,'$.busbw.all_gather') AS DOUBLE),2) all_gather,
                  round(CAST(json_extract(r.metrics_json,'$.busbw.alltoall') AS DOUBLE),2) alltoall
                  FROM results r JOIN jobs j ON j.job_id=r.job_id
                  WHERE r.workload='nccl' AND r.verdict='PASS'
                  AND json_extract(r.metrics_json,'$.busbw.all_reduce') IS NOT NULL
                  ORDER BY all_reduce DESC LIMIT 15""").fetchall(),
                 ["su", "job", "nodes", "all_reduce", "all_gather", "alltoall"])
        else:
            show(c.execute("""SELECT j.sus_json su, r.job_id, j.node_count nodes,
                  round(CAST(json_extract(r.metrics_json,'$.tflops_per_gpu_median') AS DOUBLE),1) tflops,
                  round(CAST(json_extract(r.metrics_json,'$.step_time_s_mean') AS DOUBLE),3) step_s
                  FROM results r JOIN jobs j ON j.job_id=r.job_id
                  WHERE r.workload='llama'
                  AND json_extract(r.metrics_json,'$.tflops_per_gpu_median') IS NOT NULL
                  ORDER BY tflops DESC LIMIT 15""").fetchall(),
                 ["su", "job", "nodes", "tflops_per_gpu", "step_s"])

    elif cmd == "failures":
        since = args[1] if len(args) > 1 else "2026-08-01"
        show(c.execute("""SELECT workload_class, state, count(*) n,
              count(DISTINCT job_id) jobs FROM jobs
              WHERE start >= ? AND state NOT IN ('COMPLETED','PENDING','RUNNING')
              GROUP BY 1,2 ORDER BY n DESC LIMIT 20""", [since]).fetchall(),
             ["class", "state", "rows", "jobs"])

    elif cmd == "runs":
        # ask.py runs llama SU4   -> the operator's canonical question:
        # every run of a workload on an SU, with who/when/logs and a
        # pass-fail-incomplete tally.
        wl = args[0] if args else "llama"
        su = args[1].upper() if len(args) > 1 else None
        where = "workload_class = ?" + (" AND sus_json LIKE ?" if su else "")
        params = [wl] + ([f"%{su}%"] if su else [])
        show(c.execute(f"""SELECT job_id, attempt, job_name, user, state,
              start, elapsed, node_count, rack_count,
              json_extract_string(log_paths_json,'$[0]') AS log
              FROM jobs WHERE {where} ORDER BY start DESC LIMIT 40""",
              params).fetchall(),
             ["job", "try", "name", "who", "state", "start", "elapsed",
              "nodes", "racks", "log"])
        print(f"\n  outcome tally — {wl}" + (f" on {su}" if su else "") + ":")
        show(c.execute(f"""SELECT state, count(*) n FROM jobs WHERE {where}
              GROUP BY 1 ORDER BY n DESC""", params).fetchall(), ["state", "jobs"])
        print("\n  measured results for those jobs:")
        show(c.execute(f"""SELECT r.workload, r.verdict, count(*) n
              FROM results r JOIN jobs j ON j.job_id = r.job_id
              WHERE j.{where} AND r.metrics_json NOT IN ('','{{}}')
              GROUP BY 1,2 ORDER BY n DESC LIMIT 10""", params).fetchall(),
             ["workload", "verdict", "files"])

    elif cmd == "coverage":
        tot = c.execute("SELECT count(DISTINCT job_id) FROM jobs").fetchone()[0]
        cov = c.execute("""SELECT count(DISTINCT job_id) FROM results
                           WHERE job_id<>'' AND map_method<>'unmapped'""").fetchone()[0]
        par = c.execute("""SELECT count(*) FROM results
                           WHERE metrics_json NOT IN ('','{}')""").fetchone()[0]
        nod = c.execute("SELECT count(DISTINCT node) FROM results WHERE node<>''").fetchone()[0]
        print(f"  jobs in census                : {tot:,}")
        print(f"  jobs with an attributed result: {cov:,}  ({100*cov/max(tot,1):.1f}%)")
        print(f"  result files with parsed numbers: {par:,}")
        print(f"  distinct trays with measurements: {nod:,}")
        show(c.execute("""SELECT workload, map_method, count(*) n FROM results
              WHERE workload<>'' GROUP BY 1,2 ORDER BY n DESC LIMIT 12""").fetchall(),
             ["workload", "mapped_by", "files"])

    elif cmd == "sql":
        rows = c.execute(args[0]).fetchall()
        cols = [d[0] for d in c.description]
        show(rows[:200], cols)
        if len(rows) > 200:
            print(f"  ... {len(rows)-200} more rows")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
