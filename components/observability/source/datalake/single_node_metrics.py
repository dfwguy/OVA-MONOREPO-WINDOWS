#!/usr/bin/env python3
"""Materialize current single-node validation and health data for Grafana.

The llm-pretrain-solo calculation intentionally mirrors verdict.sh: one median
per labelled rank, followed by population coefficient of variation across the
rank medians.  Current files only are used; historical .fail/.prev attempts do
not override a later successful result.
"""
from __future__ import annotations

import csv
import math
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

RESULTS = Path(os.environ.get("NVIS_RESULTS", "/cluster/bringup/results"))
OUT = Path(os.environ.get(
    "NVIS_SINGLE_NODE_CURATED",
    "/cluster/OVA/hlakshminara/opt/iren_mkz-16k-services/lake-active/curated/single_node",
))
NODE_RE = re.compile(r"^example50-(dh\d{2})-([a-z]\d{2})-(\d{2})$")
TIMING_RE = re.compile(
    r"^(\d+):.*?(?:train_step_timing[^0-9]*|"
    r"elapsed time per iteration \(ms\):\s*)([0-9]+(?:\.[0-9]*)?)"
)
HEALTH_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) EXIT: .*?\b(passed|failed) health checks\b",
    re.I,
)
DIFF_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) differs from .*?:\s*(.*)$")


def atomic_csv(name: str, fields: list[str], rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / f".{name}.tmp"
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, OUT / name)


def iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def parse_solo(path: Path) -> tuple[dict, list[dict]]:
    by_rank: dict[int, list[float]] = {}
    has_error = False
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            low = line.lower()
            if ("traceback" in low or "cuda error" in low or "nccl error" in low
                    or "out of memory" in low):
                has_error = True
            hit = TIMING_RE.search(line)
            if hit:
                by_rank.setdefault(int(hit.group(1)), []).append(float(hit.group(2)))

    medians = {rank: statistics.median(vals) for rank, vals in by_rank.items()}
    counts = {rank: len(vals) for rank, vals in by_rank.items()}
    cov = None
    if len(medians) >= 2:
        vals = list(medians.values())
        mean = statistics.mean(vals)
        cov = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)) / mean
    all_values = [v for vals in by_rank.values() for v in vals]
    overall_median = statistics.median(all_values) if all_values else None

    if not by_rank:
        status, reason = "FAIL", "no training step timings"
    elif len(by_rank) < 4:
        status, reason = "FAIL", "fewer than 4 GPUs reported step timings"
    elif any(counts.get(rank, 0) < 50 for rank in by_rank):
        status, reason = "FAIL", "a GPU reported fewer than 50 step timings"
    elif has_error:
        status, reason = "FAIL", "training error in result"
    elif cov is not None and cov > 0.02:
        status, reason = "FAIL", "per-GPU step times disagree -- spread above 0.02"
    elif overall_median is not None and overall_median > 3510:
        status, reason = "FAIL", "step time above 3510 ms"
    else:
        status, reason = "PASS", ""

    fastest = min(medians.values()) if medians else None
    slowest = max(medians.values()) if medians else None
    spread = ((slowest / fastest - 1) * 100) if fastest else None
    worst_rank = max(medians, key=medians.get) if medians else None
    summary = {
        "solo_status": status,
        "solo_reason": reason,
        "solo_mtime": iso_mtime(path),
        "gpu_count": len(medians),
        "min_iterations": min(counts.values()) if counts else 0,
        "cov": round(cov, 8) if cov is not None else "",
        "cov_pct": round(cov * 100, 4) if cov is not None else "",
        "relative_spread_pct": round(spread, 4) if spread is not None else "",
        "fastest_ms": round(fastest, 3) if fastest is not None else "",
        "slowest_ms": round(slowest, 3) if slowest is not None else "",
        "overall_median_ms": round(overall_median, 3) if overall_median is not None else "",
        "slowest_gpu": worst_rank if worst_rank is not None else "",
        "near_limit": 1 if cov is not None and 0.018 <= cov <= 0.02 else 0,
    }
    gpu_rows = []
    for rank in sorted(medians):
        med = medians[rank]
        gpu_rows.append({
            "gpu": rank,
            "iterations": counts[rank],
            "median_ms": round(med, 3),
            "relative_to_fastest_pct": round((med / fastest - 1) * 100, 4),
        })
    return summary, gpu_rows


def parse_health(path: Path) -> dict:
    last = None
    detail_by_time: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            d = DIFF_RE.match(line.rstrip())
            if d:
                detail_by_time[d.group(1)] = d.group(2).strip()
            h = HEALTH_RE.match(line.rstrip())
            if h:
                last = (h.group(1), h.group(2).upper())
    if not last:
        return {"health_status": "UNKNOWN", "health_time": "", "health_detail": ""}
    stamp, status = last
    return {
        "health_status": "PASS" if status == "PASSED" else "FAIL",
        "health_time": stamp,
        "health_detail": detail_by_time.get(stamp, ""),
    }


def parse_quick_view(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            hit = re.match(r"^([a-z0-9-]+):\s+([^<\n]+?)(?:\s+<-\s+(.*))?$", line, re.I)
            if not hit:
                continue
            test, raw, reason = hit.group(1), hit.group(2).strip(), (hit.group(3) or "").strip()
            if raw == "DONE":
                status = "PASS"
            elif reason or raw in {"FAILED", "FAIL"}:
                status = "FAIL"
            elif raw.startswith("BURN-IN OFF") or raw in {"OFF", "DISABLED"}:
                status = "DISABLED"
            else:
                status = "PENDING"
            rows.append({"test": test, "test_status": status, "raw_status": raw, "reason": reason})
    return rows


def main() -> None:
    summaries, gpu_rows, tests = [], [], []
    generated = datetime.now(timezone.utc).isoformat()
    nodes = []
    for path in RESULTS.iterdir():
        if path.is_dir() and NODE_RE.match(path.name):
            nodes.append(path)

    for node_dir in sorted(nodes):
        node = node_dir.name
        match = NODE_RE.match(node)
        assert match
        common = {
            "node": node,
            "datahall": match.group(1),
            "rack": match.group(2),
            "rack_id": f"{match.group(1)}-{match.group(2)}",
            "position": int(match.group(3)),
            # Physical suffixes are 11-18 and 28-37; normalize them to the
            # rack's 18 left-to-right heatmap slots.
            "position_slot": ({p: i + 1 for i, p in enumerate(
                list(range(11, 19)) + list(range(28, 38))
            )})[int(match.group(3))],
            "generated_at": generated,
        }
        solo_path = node_dir / "llm-pretrain-solo.txt"
        if solo_path.exists():
            summary, per_gpu = parse_solo(solo_path)
        else:
            summary = {
                "solo_status": "MISSING", "solo_reason": "no current llm-pretrain-solo.txt",
                "solo_mtime": "", "gpu_count": 0, "min_iterations": 0, "cov": "",
                "cov_pct": "", "relative_spread_pct": "", "fastest_ms": "",
                "slowest_ms": "", "overall_median_ms": "", "slowest_gpu": "",
                "near_limit": 0,
            }
            per_gpu = []
        health_path = node_dir / "health.log"
        health = parse_health(health_path) if health_path.exists() else {
            "health_status": "MISSING", "health_time": "", "health_detail": ""
        }
        summaries.append(common | summary | health)
        gpu_rows.extend(common | row | {
            "solo_status": summary["solo_status"], "cov": summary["cov"],
            "cov_pct": summary["cov_pct"], "relative_spread_pct": summary["relative_spread_pct"],
        } for row in per_gpu)
        quick = node_dir / "quick-view.txt"
        if quick.exists():
            tests.extend(common | row for row in parse_quick_view(quick))

    atomic_csv("node_summary.csv", list(summaries[0]), summaries)
    atomic_csv("solo_gpu.csv", list(gpu_rows[0]), gpu_rows)
    atomic_csv("test_status.csv", list(tests[0]), tests)
    print(f"nodes={len(summaries)} gpu_rows={len(gpu_rows)} tests={len(tests)} out={OUT}")


if __name__ == "__main__":
    main()
