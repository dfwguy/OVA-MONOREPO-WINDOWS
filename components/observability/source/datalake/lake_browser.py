#!/usr/bin/env python3
"""lake_browser — a read-only web UI to ask the Parquet lake questions.

There was no Parquet/DuckDB browser on this box; queries meant knowing which
parquet file to open and how to join it. This serves the three lake tables as
views over local files, with the common questions as one-click presets and a
free-text SQL box for everything else.

    jobs    one row per Slurm job    147,809 rows
    results one row per result FILE
    health  one row per health artifact

Read-only by construction: anything that is not a SELECT/WITH/DESCRIBE/SHOW is
rejected before it reaches DuckDB. The service container also mounts the lake
read-only. This is a reporting surface over a production lake, not an admin
console.

Start:  nohup gsheets-venv/bin/python lake_browser.py &   then http://<host>:9415
"""
from __future__ import annotations
import html
import json
import os
import re
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import duckdb

L = os.environ.get("LAKE_CURATED", "/data/lake/curated")
PORT = int(os.environ.get("BROWSER_PORT", "9415"))
BIND = os.environ.get("BROWSER_BIND", "0.0.0.0")
ROW_CAP = int(os.environ.get("BROWSER_ROW_CAP", "2000"))
SURFACE = os.environ.get("BROWSER_SURFACE", "Parquet Browser")

VIEWS = [
    ("jobs", f"{L}/slurm_jobs/*.parquet"),
    ("results", f"{L}/run_results/*.parquet"),
    ("health", f"{L}/health_artifacts/*.parquet"),
]

CSV_VIEWS = [
    ("single_node", f"{L}/single_node/node_summary.csv"),
    ("solo_gpu", f"{L}/single_node/solo_gpu.csv"),
    ("single_node_tests", f"{L}/single_node/test_status.csv"),
]

# Only statements that read. Checked before execution, not after.
SAFE_RE = re.compile(r"^\s*(select|with|describe|show|summarize|pragma table_info)\b",
                     re.I | re.S)
BANNED_RE = re.compile(
    r"\b(attach|copy|install|load|export|import|create|insert|update|delete|"
    r"drop|alter|call)\b", re.I)

PRESETS = [
    ("Llama runs on SU4 — who, when, outcome",
     "SELECT job_id, attempt, job_name, user, state, start, elapsed, node_count,\n"
     "       rack_count, json_extract_string(log_paths_json,'$[0]') AS log\n"
     "FROM jobs WHERE workload_class='llama' AND sus_json LIKE '%SU4%'\n"
     "ORDER BY start DESC LIMIT 100"),
    ("Pass / fail / incomplete by workload",
     "SELECT workload_class, state, count(*) AS jobs\n"
     "FROM jobs GROUP BY 1,2 ORDER BY workload_class, jobs DESC"),
    ("Every job that touched rack h03",
     "SELECT job_id, job_name, workload_class, user, state, start, elapsed\n"
     "FROM jobs WHERE racks_json LIKE '%\"h03\"%' ORDER BY start DESC LIMIT 200"),
    ("Best NCCL busbw (16 GiB out-of-place) per SU",
     "SELECT j.sus_json AS su, r.job_id, j.node_count AS nodes,\n"
     "  round(CAST(json_extract(r.metrics_json,'$.busbw.all_reduce') AS DOUBLE),2) AS all_reduce,\n"
     "  round(CAST(json_extract(r.metrics_json,'$.busbw.all_gather') AS DOUBLE),2) AS all_gather,\n"
     "  round(CAST(json_extract(r.metrics_json,'$.busbw.alltoall') AS DOUBLE),2) AS alltoall\n"
     "FROM results r JOIN jobs j ON j.job_id=r.job_id\n"
     "WHERE r.workload='nccl' AND r.verdict='PASS'\n"
     "  AND json_extract(r.metrics_json,'$.busbw.all_reduce') IS NOT NULL\n"
     "ORDER BY all_reduce DESC LIMIT 50"),
    ("Best Llama TFLOP/s per GPU",
     "SELECT j.sus_json AS su, r.job_id, j.node_count AS nodes,\n"
     "  round(CAST(json_extract(r.metrics_json,'$.tflops_per_gpu_median') AS DOUBLE),1) AS tflops,\n"
     "  round(CAST(json_extract(r.metrics_json,'$.step_time_s_mean') AS DOUBLE),3) AS step_s\n"
     "FROM results r JOIN jobs j ON j.job_id=r.job_id\n"
     "WHERE r.workload='llama'\n"
     "  AND json_extract(r.metrics_json,'$.tflops_per_gpu_median') IS NOT NULL\n"
     "ORDER BY tflops DESC LIMIT 50"),
    ("Failures in the last 3 days, by class",
     "SELECT workload_class, state, count(*) AS jobs\n"
     "FROM jobs WHERE start >= strftime(now() - INTERVAL 3 DAY, '%Y-%m-%dT%H:%M:%S')\n"
     "  AND state NOT IN ('COMPLETED','PENDING','RUNNING')\n"
     "GROUP BY 1,2 ORDER BY jobs DESC"),
    ("Everything measured on one tray",
     "SELECT node, test, workload, verdict, map_method,\n"
     "       strftime(to_timestamp(mtime),'%Y-%m-%d %H:%M') AS measured_at,\n"
     "       substr(metrics_json,1,120) AS metrics\n"
     "FROM results WHERE node='example50-dh01-h03-14'\n"
     "  AND metrics_json NOT IN ('','{}') ORDER BY mtime DESC LIMIT 100"),
    ("Coverage: how much do we actually have",
     "SELECT (SELECT count(DISTINCT job_id) FROM jobs) AS jobs_total,\n"
     "       (SELECT count(DISTINCT job_id) FROM results\n"
     "          WHERE job_id<>'' AND map_method<>'unmapped') AS jobs_with_result,\n"
     "       (SELECT count(*) FROM results WHERE metrics_json NOT IN ('','{}'))\n"
     "         AS files_parsed,\n"
     "       (SELECT count(DISTINCT node) FROM results WHERE node<>'') AS trays_measured"),
]

PAGE = """<!doctype html><meta charset=utf-8><title>NVIS __SURFACE__</title>
<style>
:root{color-scheme:dark}
body{background:#0f1117;color:#e6e6e6;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:20px 26px}
h1{font-size:17px;margin:0 0 4px;font-weight:600}
.sub{color:#8b93a7;font-size:12px;margin-bottom:16px}
textarea{width:100%;height:130px;background:#161923;color:#e6e6e6;border:1px solid #2b3040;
 border-radius:6px;padding:10px;font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;resize:vertical}
button{background:#2f6f4f;color:#fff;border:0;border-radius:6px;padding:8px 16px;font-size:13px;cursor:pointer;margin-top:8px}
button:hover{background:#3a8a62}
.presets{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 14px}
.presets a{background:#1b1f2b;border:1px solid #2b3040;color:#9fb8ff;padding:5px 10px;
 border-radius:14px;font-size:12px;text-decoration:none}
.presets a:hover{border-color:#4a5570;color:#c7d6ff}
table{border-collapse:collapse;width:100%;margin-top:14px;font-size:12.5px}
th{background:#1b1f2b;text-align:left;padding:7px 9px;position:sticky;top:0;border-bottom:1px solid #2b3040}
td{padding:6px 9px;border-bottom:1px solid #191d27;vertical-align:top;
 max-width:520px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
tr:hover td{background:#151925}
.err{background:#2b1618;border:1px solid #5a2a2e;color:#ffb4b4;padding:10px;border-radius:6px;
 white-space:pre-wrap;font:12px ui-monospace,monospace}
.meta{color:#8b93a7;font-size:12px;margin-top:10px}
code{color:#9fb8ff}
</style>
<h1>NVIS 16K __SURFACE__</h1>
<div class=sub>Tables: <code>jobs</code> (one row per Slurm job) &middot;
<code>results</code> (one row per result file) &middot; <code>health</code>.
Read-only. All data local on /cluster + /data/lake.</div>
<div class=presets>__PRESETS__</div>
<form method=get>
<textarea name=q spellcheck=false>__Q__</textarea>
<button type=submit>Run</button>
</form>
__RESULT__
"""


def render(q, body):
    presets = "".join(
        f'<a href="/?q={urllib.parse.quote(sql)}">{html.escape(label)}</a>'
        for label, sql in PRESETS)
    return (PAGE.replace("__SURFACE__", html.escape(SURFACE))
            .replace("__PRESETS__", presets)
            .replace("__Q__", html.escape(q or ""))
            .replace("__RESULT__", body))


def query_is_safe(q):
    """Reject all non-reporting SQL before it reaches DuckDB."""
    return bool(SAFE_RE.match(q)) and not BANNED_RE.search(q)


def open_catalog():
    """Build ephemeral views over the read-only Parquet mount."""
    con = duckdb.connect(":memory:")
    con.execute("SET memory_limit='4GB'")
    for name, glob in VIEWS:
        try:
            con.execute(f"CREATE OR REPLACE VIEW {name} AS "
                        f"SELECT * FROM read_parquet('{glob}')")
        except Exception:
            pass  # an empty 16K table must not break the other views
    for name, path in CSV_VIEWS:
        try:
            con.execute(f"CREATE OR REPLACE VIEW {name} AS "
                        f"SELECT * FROM read_csv_auto('{path}', header=true)")
        except Exception:
            pass
    return con


def run_query(q):
    if not query_is_safe(q):
        return ('<div class=err>Read-only surface: only SELECT / WITH / DESCRIBE '
                '/ SHOW / SUMMARIZE are allowed.</div>')
    con = open_catalog()
    try:
        cur = con.execute(q)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(ROW_CAP)
    except Exception as e:
        return f'<div class=err>{html.escape(str(e))}</div>'
    if not rows:
        return '<div class=meta>0 rows.</div>'
    out = ["<table><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in cols) + "</tr>"]
    for r in rows:
        out.append("<tr>" + "".join(
            f"<td title='{html.escape(str(v))}'>{html.escape(str(v)[:200])}</td>"
            for v in r) + "</tr>")
    out.append("</table>")
    out.append(f'<div class=meta>{len(rows)} rows'
               f'{" (capped)" if len(rows) >= ROW_CAP else ""}.</div>')
    return "".join(out)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/healthz":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok\n"); return
        q = urllib.parse.parse_qs(u.query).get("q", [""])[0]
        if u.path == "/api" and q:
            try:
                if not query_is_safe(q):
                    raise ValueError("read-only surface: query rejected")
                con = open_catalog()
                cur = con.execute(q)
                body = json.dumps({"columns": [d[0] for d in cur.description],
                                   "rows": cur.fetchmany(ROW_CAP)}, default=str).encode()
                ct = "application/json"
            except Exception as e:
                body = json.dumps({"error": str(e)}).encode(); ct = "application/json"
        else:
            body = render(q, run_query(q) if q else "").encode()
            ct = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"{SURFACE} on {BIND}:{PORT}", flush=True)
    ThreadingHTTPServer((BIND, PORT), H).serve_forever()
