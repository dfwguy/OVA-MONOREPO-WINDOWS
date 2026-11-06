#!/usr/bin/env python3
"""Publish canonical Rack Status NCCL history into VictoriaMetrics.

Rack Status deliberately keeps the raw parser history, including mid-run
snapshots and records emitted by two parser paths.  This exporter does not
rewrite that evidence.  It selects the newest snapshot for each aggregated
single-rack NCCL log, merges complementary parser fields, derives an explicit
acceptance verdict, and publishes both timestamped run history and current
per-rack summaries for Grafana.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.request


DB = os.environ.get("RESULTS_DB", "/data/history/results.db")
VM = os.environ.get("VM_IMPORT_URL", "http://127.0.0.1:8429/api/v1/import/prometheus")
INTERVAL = max(15, int(os.environ.get("EXPORT_INTERVAL_SECONDS", "60")))
FLOOR = float(os.environ.get("NCCL_ALL_REDUCE_FLOOR_GBPS", "855"))

RACK_RE = re.compile(r"(example50-dh01-([defghij])(\d+))", re.I)
SU_BY_LETTER = {letter: f"SU{index}" for index, letter in enumerate("defghij", start=1)}
STATUS_CODE = {"UNKNOWN": 0, "PASS": 1, "FAIL": 2, "PARTIAL": 3}


def esc(value: object) -> str:
    return str(value if value is not None else "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def labels(values: dict[str, object]) -> str:
    return "{" + ",".join(f'{key}="{esc(value)}"' for key, value in sorted(values.items())) + "}"


def sample(name: str, value: float | int, label_values: dict[str, object] | None = None, timestamp_ms: int | None = None) -> str:
    suffix = labels(label_values or {}) if label_values else ""
    stamp = f" {timestamp_ms}" if timestamp_ms is not None else ""
    return f"{name}{suffix} {value}{stamp}"


def iso_timestamp(value: object, fallback: float | None) -> float:
    text = str(value or "").strip()
    if text:
        try:
            return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return float(fallback or time.time())


def json_obj(value: object, default):
    try:
        loaded = json.loads(str(value or ""))
        return loaded if isinstance(loaded, type(default)) else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def metric_value(metrics: dict[str, dict], *names: str) -> float | None:
    for name in names:
        row = metrics.get(name)
        if row and row.get("value") is not None:
            try:
                return float(row["value"])
            except (TypeError, ValueError):
                continue
    return None


def normalize_rack(source_rack: str) -> tuple[str, str]:
    match = RACK_RE.search(source_rack or "")
    if not match:
        return source_rack or "unknown", "unknown"
    letter = match.group(2).lower()
    return f"WH1{letter.upper()}{int(match.group(3))}", SU_BY_LETTER.get(letter, "unknown")


def load_canonical() -> tuple[list[dict], int]:
    # The source volume is mounted read-only.  Rack Status checkpoints WAL
    # before the file is exposed; immutable avoids SQLite trying to create a
    # sidecar -shm file in that read-only directory.
    uri = f"file:{DB}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        db_runs = int(connection.execute("SELECT COUNT(*) FROM runs WHERE workload_kind='nccl'").fetchone()[0])
        rows = connection.execute(
            """
            WITH newest AS (
              SELECT source_log_path, MAX(COALESCE(log_mtime,0)) AS newest_mtime
              FROM runs
              WHERE workload_kind='nccl' AND log_basename LIKE '%-NCCL-1Rack-%'
              GROUP BY source_log_path
            )
            SELECT r.*
            FROM runs r JOIN newest n
              ON r.source_log_path=n.source_log_path
             AND COALESCE(r.log_mtime,0)=n.newest_mtime
            WHERE r.workload_kind='nccl'
            ORDER BY r.source_log_path, r.updated_at
            """
        ).fetchall()
        run_ids = [row["run_id"] for row in rows]
        metrics_by_run: dict[str, dict[str, dict]] = {run_id: {} for run_id in run_ids}
        if run_ids:
            for start in range(0, len(run_ids), 400):
                batch = run_ids[start:start + 400]
                marks = ",".join("?" for _ in batch)
                for item in connection.execute(
                    f"SELECT run_id,metric_name,value,unit,labels FROM run_metrics WHERE seq=0 AND run_id IN ({marks})",
                    batch,
                ):
                    metrics_by_run[item["run_id"]][item["metric_name"]] = dict(item)
    finally:
        connection.close()

    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["source_log_path"], []).append(row)

    canonical = []
    for path, versions in grouped.items():
        preferred = next((row for row in versions if row["source"] == "parser_json_for_log_path"), versions[-1])
        merged_metrics: dict[str, dict] = {}
        collectives: set[str] = set()
        error_count = 0
        explicit_fail = False
        for row in versions:
            merged_metrics.update(metrics_by_run.get(row["run_id"], {}))
            extra = json_obj(row["extra"], {})
            parser_extra = extra.get("parser_extra") if isinstance(extra.get("parser_extra"), dict) else {}
            collectives.update(str(value) for value in parser_extra.get("nccl_collectives") or [])
            error_count += len(extra.get("errors") or []) if isinstance(extra.get("errors"), list) else 0
            explicit_fail = explicit_fail or str(row["status"] or "").lower() == "fail"

        source_rack = str(preferred["rack"] or "")
        if not source_rack:
            match = RACK_RE.search(str(preferred["log_basename"] or ""))
            source_rack = match.group(1) if match else "unknown"
        rack, su = normalize_rack(source_rack)
        all_reduce = metric_value(merged_metrics, "all_reduce_gbps", "nccl_busbw_peak")
        all_gather = metric_value(merged_metrics, "all_gather_gbps")
        alltoall = metric_value(merged_metrics, "alltoall_gbps")
        avg_busbw = metric_value(merged_metrics, "nccl_avg_busbw", "avg_bus_bandwidth")
        wrong = metric_value(merged_metrics, "nccl_out_of_bounds_values", "out_of_bounds_values")
        tests = metric_value(merged_metrics, "tests")
        if not collectives:
            if all_reduce is not None:
                collectives.add("all_reduce")
            if all_gather is not None:
                collectives.add("all_gather")
            if alltoall is not None:
                collectives.add("alltoall")

        if all_reduce is None:
            verdict = "FAIL" if explicit_fail and error_count else "UNKNOWN"
        elif all_reduce < FLOOR or (wrong is not None and wrong > 0):
            verdict = "FAIL"
        elif len(collectives) >= 5 or (tests is not None and tests >= 24):
            verdict = "PASS"
        else:
            verdict = "PARTIAL"

        started = iso_timestamp(preferred["started_at"], preferred["log_mtime"])
        identity = hashlib.sha1(
            f"{path}|{preferred['log_mtime']}|{preferred['log_size']}".encode()
        ).hexdigest()[:16]
        canonical.append({
            "run_id": identity,
            "job_id": str(preferred["job_id"] or "unknown"),
            "rack": rack,
            "source_rack": source_rack,
            "su": su,
            "status": verdict,
            "status_code": STATUS_CODE[verdict],
            "started": started,
            "all_reduce": all_reduce,
            "all_gather": all_gather,
            "alltoall": alltoall,
            "avg_busbw": avg_busbw,
            "wrong": wrong,
            "tests": tests,
            "collectives": len(collectives),
            "error_count": error_count,
            "log_basename": str(preferred["log_basename"] or ""),
        })
    canonical.sort(key=lambda run: run["started"])
    return canonical, db_runs


def payload() -> str:
    runs, db_runs = load_canonical()
    now = int(time.time())
    now_ms = now * 1000
    lines = [
        sample("iren_mkz_nccl_exporter_up", 1, {"source": "rack_status_results"}, now_ms),
        sample("iren_mkz_nccl_exporter_last_success_timestamp_seconds", now, {"source": "rack_status_results"}, now_ms),
        sample("iren_mkz_nccl_exporter_db_runs", db_runs, {"kind": "nccl"}, now_ms),
        sample("iren_mkz_nccl_canonical_runs", len(runs), {"scope": "single_rack"}, now_ms),
        sample("iren_mkz_nccl_acceptance_floor_gbps", FLOOR, {"collective": "all_reduce", "scope": "single_rack"}, now_ms),
    ]
    latest: dict[str, dict] = {}
    for run in runs:
        latest[run["rack"]] = max(run, latest.get(run["rack"], run), key=lambda item: item["started"])
        common = {key: run[key] for key in ("run_id", "job_id", "rack", "source_rack", "su", "status")}
        stamp = int(run["started"] * 1000)
        lines.append(sample("iren_mkz_nccl_run_info", 1, common, stamp))
        lines.append(sample("iren_mkz_nccl_run_verdict_code", run["status_code"], common, stamp))
        lines.append(sample("iren_mkz_nccl_run_started_timestamp_seconds", run["started"], common, stamp))
        for suffix, key in (
            ("all_reduce_gbps", "all_reduce"), ("all_gather_gbps", "all_gather"),
            ("alltoall_gbps", "alltoall"), ("avg_busbw_gbps", "avg_busbw"),
            ("wrong_values", "wrong"), ("tests", "tests"),
            ("collectives", "collectives"), ("error_count", "error_count"),
        ):
            if run[key] is not None:
                lines.append(sample(f"iren_mkz_nccl_run_{suffix}", run[key], common, stamp))

    for run in latest.values():
        common = {key: run[key] for key in ("run_id", "job_id", "rack", "source_rack", "su", "status")}
        lines.append(sample("iren_mkz_nccl_rack_latest_info", 1, common, now_ms))
        lines.append(sample("iren_mkz_nccl_rack_latest_verdict_code", run["status_code"], common, now_ms))
        lines.append(sample("iren_mkz_nccl_rack_latest_started_timestamp_seconds", run["started"], common, now_ms))
        for suffix, key in (
            ("all_reduce_gbps", "all_reduce"), ("all_gather_gbps", "all_gather"),
            ("alltoall_gbps", "alltoall"), ("avg_busbw_gbps", "avg_busbw"),
            ("wrong_values", "wrong"), ("tests", "tests"),
            ("collectives", "collectives"), ("error_count", "error_count"),
        ):
            if run[key] is not None:
                lines.append(sample(f"iren_mkz_nccl_rack_latest_{suffix}", run[key], common, now_ms))
    return "\n".join(lines) + "\n"


def push(body: str) -> None:
    request = urllib.request.Request(VM, data=body.encode(), method="POST")
    request.add_header("Content-Type", "text/plain; charset=utf-8")
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status >= 300:
            raise RuntimeError(f"VictoriaMetrics import returned {response.status}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            body = payload()
            push(body)
            print(f"published {body.count(chr(10))} NCCL validation samples", flush=True)
        except Exception as error:
            print(f"validation export failed: {error}", flush=True)
            try:
                now_ms = int(time.time() * 1000)
                push(sample("iren_mkz_nccl_exporter_up", 0, {"source": "rack_status_results"}, now_ms) + "\n")
            except Exception:
                pass
            if args.once:
                raise
        if args.once:
            return
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
