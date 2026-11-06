#!/usr/bin/env python3
"""Export a bounded Slurm/job-log snapshot for the IREN_MKZ job dashboard.

The collector deliberately uses one sacct call, one scontrol call, and a shallow
scan of the benchmark log directory.  Log parsing is capped to the newest 2 MiB
of at most four files per active/recent job.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time


SLURM_BIN = Path(os.environ.get("SLURM_BIN", "/cm/local/apps/slurm/25.05/bin"))
SLURM_CONF = os.environ.get("SLURM_CONF", "/cm/shared/apps/slurm/etc/slurm/slurm.conf")
LOG_DIR = Path(os.environ.get("NVIS_JOB_LOG_DIR", "/home/cmods/benchmark/harish"))
STATE_FILE = Path(os.environ.get("NVIS_JOB_STATE_FILE", "/var/lib/nvis-headnode/job-collector-state.json"))
RECENT_LIMIT = int(os.environ.get("NVIS_JOB_RECENT_LIMIT", "300"))
PARSE_LIMIT = int(os.environ.get("NVIS_JOB_PARSE_LIMIT", "50"))
HISTORICAL_MIN_NODES = int(os.environ.get("NVIS_JOB_HISTORY_MIN_NODES", "128"))
HISTORICAL_LIMIT = int(os.environ.get("NVIS_JOB_HISTORY_LIMIT", "32"))
HISTORICAL_PARSE_LIMIT = int(os.environ.get("NVIS_JOB_HISTORY_PARSE_LIMIT", "8"))
# One IREN_MKZ job can legitimately span all 2,016 current compute nodes (and
# the next cluster shape is 4,032).  The old literal 512 silently truncated the
# job->node bridge, so JobID dashboards showed only SU1/SU2 for a 1,792-node
# allocation.  Keep the bound configurable, publish completeness below, and
# default above the documented maximum cluster size.
JOB_NODE_LIMIT = int(os.environ.get("NVIS_JOB_NODE_LIMIT", "4096"))
ACTIVE_TELEMETRY_NODE_LIMIT = int(os.environ.get("NVIS_ACTIVE_TELEMETRY_NODE_LIMIT", "4096"))
ACTIVE_NODE_TARGETS_FILE = Path(os.environ.get(
    "NVIS_ACTIVE_NODE_TARGETS_FILE",
    "/var/lib/nvis-observability/prometheus-targets/active-validation-node.json",
))
ACTIVE_DCGM_TARGETS_FILE = Path(os.environ.get(
    "NVIS_ACTIVE_DCGM_TARGETS_FILE",
    "/var/lib/nvis-observability/prometheus-targets/active-validation-dcgm.json",
))
MAX_FILES_PER_JOB = 4
TAIL_BYTES = 2 * 1024 * 1024
LOG_SUFFIXES = {".txt", ".out", ".log", ".err", ".raw", ".tsv"}
ACTIVE_STATES = {"PENDING", "CONFIGURING", "RUNNING", "COMPLETING", "SUSPENDED", "RESIZING"}
ACTIVE_TELEMETRY_STATES = {"CONFIGURING", "RUNNING", "COMPLETING"}
ACTIVE_TELEMETRY_WORKLOADS = {"nccl", "nemo", "llama", "mnubergemm"}
STATE_CODES = {
    "UNKNOWN": 0,
    "PENDING": 1,
    "CONFIGURING": 2,
    "RUNNING": 3,
    "COMPLETING": 4,
    "COMPLETED": 5,
    "CANCELLED": 6,
    "FAILED": 7,
    "TIMEOUT": 8,
    "NODE_FAIL": 9,
    "OUT_OF_MEMORY": 10,
    "PREEMPTED": 11,
    "SUSPENDED": 12,
}


def run(command: list[str], timeout: int = 30) -> str:
    env = os.environ.copy()
    env["SLURM_CONF"] = SLURM_CONF
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"{' '.join(command)}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def clean_state(value: str | None) -> str:
    value = (value or "UNKNOWN").strip().upper().split()[0].rstrip("+")
    return value if value else "UNKNOWN"


def parse_iso(value: str | None) -> float:
    if not value or value in {"None", "Unknown", "N/A"}:
        return 0.0
    try:
        return dt.datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def parse_duration(value: str | None) -> float:
    if not value or value in {"None", "Unknown", "N/A", "UNLIMITED", "Partition_Limit"}:
        return 0.0
    try:
        days = 0
        if "-" in value:
            day_text, value = value.split("-", 1)
            days = int(day_text)
        fields = [int(part) for part in value.split(":")]
        if len(fields) == 3:
            hours, minutes, seconds = fields
        elif len(fields) == 2:
            hours, minutes, seconds = 0, fields[0], fields[1]
        else:
            return float(fields[0])
        return float(days * 86400 + hours * 3600 + minutes * 60 + seconds)
    except (ValueError, TypeError):
        return 0.0


def number(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def tres_value(tres: str | None, key: str) -> float:
    if not tres:
        return 0.0
    match = re.search(rf"(?:^|,){re.escape(key)}=([0-9.]+)(?:,|$)", tres)
    return number(match.group(1)) if match else 0.0


def workload_for(record: dict[str, object]) -> str:
    # Identity-bearing fields take precedence over campaign/work-directory
    # names.  A Llama job commonly lives below a "llama-nccl" campaign path;
    # classifying the concatenated string by the first "nccl" token mislabeled
    # those jobs and routed their dashboard panels incorrectly.
    field_groups = (
        ("job_name",),
        ("stdout",),
        ("command",),
        ("workdir",),
    )
    classifiers = (
        ("mnubergemm", ("mnubergemm", "ubergemm", "mnub")),
        ("llama", ("llama", "llmb")),
        ("nemo", ("nemo", "nemotron", "megatron", "pretrain")),
        ("nccl", ("nccl",)),
        ("hpl", ("hpl", "linpack")),
    )
    for keys in field_groups:
        text = " ".join(str(record.get(key, "")) for key in keys).lower()
        for workload, tokens in classifiers:
            if any(token in text for token in tokens):
                return workload
    return "other"


def retain_history(records: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    """Keep bounded recent jobs plus recent multi-node validation workloads."""
    ordered = sorted(records.items(), key=lambda item: (number(item[1].get("submit_ts")), int(item[0])))
    recent = dict(ordered[-RECENT_LIMIT:])
    historical = [
        (job_id, rec) for job_id, rec in ordered
        if (
            number(rec.get("requested_nodes")) >= HISTORICAL_MIN_NODES
            and workload_for(rec) in ACTIVE_TELEMETRY_WORKLOADS
        )
    ][-HISTORICAL_LIMIT:]
    for job_id, rec in historical:
        recent[job_id] = rec
    return dict(sorted(recent.items(), key=lambda item: (number(item[1].get("submit_ts")), int(item[0]))))


def stall_threshold_seconds(workload: str) -> int:
    # MNUberGEMM's audited dual-mode profile intentionally idles for 360 s and
    # commonly emits summary samples 8-10 minutes apart.  Keep the general
    # five-minute detector for every other workload while allowing one full
    # MNU work/idle reporting cycle before declaring it stalled.
    return 900 if workload == "mnubergemm" else 300


def read_sacct() -> tuple[dict[str, dict[str, object]], str]:
    fields = (
        "JobIDRaw,JobName,User,Partition,State,Reason,Submit,Eligible,Start,End,"
        "ElapsedRaw,TimelimitRaw,NNodes,NCPUS,ReqTRES,AllocTRES,NodeList,ExitCode,DerivedExitCode"
    )
    try:
        output = run(
            [
                str(SLURM_BIN / "sacct"), "-a", "-X", "-S", "now-2days", "-P", "-n",
                f"--format={fields}",
            ],
            timeout=30,
        )
    except Exception as exc:  # leave active jobs observable if accounting is briefly unavailable
        return {}, str(exc)

    records: list[dict[str, object]] = []
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) < 19 or not parts[0].isdigit():
            continue
        (
            job_id, job_name, user, partition, state, reason, submit, eligible, start, end,
            elapsed_raw, timelimit_raw, nnodes, ncpus, req_tres, alloc_tres, nodelist,
            exit_code, derived_exit_code,
        ) = parts[:19]
        state = clean_state(state)
        rec: dict[str, object] = {
            "job_id": job_id,
            "job_name": job_name,
            "user": user,
            "partition": partition,
            "state": state,
            "reason": reason if reason not in {"", "None"} else "None",
            "submit_ts": parse_iso(submit),
            "eligible_ts": parse_iso(eligible),
            "start_ts": parse_iso(start),
            "end_ts": parse_iso(end),
            "elapsed": number(elapsed_raw),
            "timelimit": number(timelimit_raw) * 60,
            "requested_nodes": tres_value(req_tres, "node") or number(nnodes),
            "allocated_nodes": 0 if state == "PENDING" else number(nnodes),
            "cpus": number(ncpus),
            "requested_gpus": tres_value(req_tres, "gres/gpu"),
            "allocated_gpus": tres_value(alloc_tres, "gres/gpu"),
            "req_tres": req_tres,
            "alloc_tres": alloc_tres,
            "nodelist": nodelist,
            "requested_nodelist": nodelist,
            "exit_code": exit_code,
            "derived_exit_code": derived_exit_code,
            "stdout": "",
            "command": "",
            "workdir": "",
        }
        records.append(rec)
    records.sort(key=lambda rec: (number(rec.get("submit_ts")), int(str(rec["job_id"]))))
    return retain_history({str(rec["job_id"]): rec for rec in records}), ""


def parse_scontrol_line(line: str) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        tokens = shlex.split(line)
    except ValueError:
        tokens = line.split()
    for token in tokens:
        if "=" in token:
            key, value = token.split("=", 1)
            values[key] = value
    return values


def merge_active(records: dict[str, dict[str, object]]) -> tuple[set[str], str]:
    try:
        output = run([str(SLURM_BIN / "scontrol"), "show", "job", "-o"], timeout=20)
    except Exception as exc:
        return set(), str(exc)
    active: set[str] = set()
    now = time.time()
    for line in output.splitlines():
        values = parse_scontrol_line(line)
        job_id = values.get("JobId", "")
        if not job_id.isdigit():
            continue
        state = clean_state(values.get("JobState"))
        if state not in ACTIVE_STATES:
            continue
        active.add(job_id)
        rec = records.setdefault(job_id, {"job_id": job_id})
        rec.update(
            {
                "job_name": values.get("JobName", rec.get("job_name", "unknown")),
                "user": re.sub(r"\(.*", "", values.get("UserId", str(rec.get("user", "unknown")))),
                "partition": values.get("Partition", rec.get("partition", "unknown")),
                "state": state,
                "reason": values.get("Reason", rec.get("reason", "None")),
                "submit_ts": parse_iso(values.get("SubmitTime")) or number(rec.get("submit_ts")),
                "eligible_ts": parse_iso(values.get("EligibleTime")) or number(rec.get("eligible_ts")),
                "start_ts": parse_iso(values.get("StartTime")) if state != "PENDING" else 0.0,
                "end_ts": 0.0,
                "elapsed": parse_duration(values.get("RunTime")),
                "timelimit": parse_duration(values.get("TimeLimit")) or number(rec.get("timelimit")),
                "requested_nodes": tres_value(values.get("ReqTRES"), "node") or number(values.get("NumNodes")),
                "allocated_nodes": 0.0 if state == "PENDING" else number(values.get("NumNodes")),
                "cpus": number(values.get("NumCPUs")),
                "requested_gpus": tres_value(values.get("ReqTRES"), "gres/gpu"),
                "allocated_gpus": tres_value(values.get("AllocTRES"), "gres/gpu"),
                "req_tres": values.get("ReqTRES", ""),
                "alloc_tres": values.get("AllocTRES", ""),
                "requested_nodelist": values.get("ReqNodeList", values.get("NodeList", "")),
                "nodelist": values.get("NodeList", ""),
                "stdout": values.get("StdOut", ""),
                "command": values.get("Command", ""),
                "workdir": values.get("WorkDir", ""),
                "exit_code": values.get("ExitCode", rec.get("exit_code", "0:0")),
                "derived_exit_code": rec.get("derived_exit_code", "0:0"),
                "seen_ts": now,
            }
        )
    return active, ""


def split_hostlist(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(value):
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return [part for part in parts if part]


def expand_hostlist(value: str, limit: int | None = None) -> list[str]:
    if limit is None:
        limit = JOB_NODE_LIMIT
    if not value or value in {"(null)", "None", "None assigned"}:
        return []
    hosts: list[str] = []
    for part in split_hostlist(value):
        match = re.fullmatch(r"(.*)\[([0-9,-]+)\](.*)", part)
        if not match:
            hosts.append(part)
            continue
        prefix, body, suffix = match.groups()
        for item in body.split(","):
            if "-" in item:
                first, last = item.split("-", 1)
                width = max(len(first), len(last))
                hosts.extend(f"{prefix}{number_:0{width}d}{suffix}" for number_ in range(int(first), int(last) + 1))
            else:
                hosts.append(f"{prefix}{item}{suffix}")
            if len(hosts) >= limit:
                return hosts[:limit]
    return hosts[:limit]


def topology_for_node(node: str) -> tuple[str, str, str]:
    match = re.match(r"example50-(dh01|dh02)-([a-z])(\d+)-", node)
    if not match:
        return "unknown", "unknown", "unknown"
    data_hall, letter, ordinal = match.groups()
    datahall = f"{'WH1' if data_hall == 'dh01' else 'EH1'}{letter.upper()}"
    rack = f"{datahall}{int(ordinal)}"
    # The live 16K inventory maps DH02 A..K to SU1..SU11 and DH01
    # A..C to SU12..SU14.  This is intentionally explicit: the retired 8K
    # collector assumed DH01 D..J and silently attributed current jobs to the
    # wrong Super Units.
    if data_hall == "dh02" and "a" <= letter <= "k":
        su_number = ord(letter) - ord("a") + 1
    elif data_hall == "dh01" and "a" <= letter <= "c":
        su_number = ord(letter) - ord("a") + 12
    else:
        su_number = 0
    su = f"SU{su_number}" if su_number else "unknown"
    return datahall, rack, su


def discover_logs(job_ids: set[str]) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {job_id: [] for job_id in job_ids}
    if not LOG_DIR.is_dir():
        return found
    root_depth = len(LOG_DIR.parts)
    newest_relevant_mtime = time.time() - 3 * 86400
    try:
        for current, dirs, files in os.walk(LOG_DIR):
            depth = len(Path(current).parts) - root_depth
            if depth >= 4:
                dirs[:] = []
            elif depth == 0:
                # sacct is bounded to two days. Do not traverse years of
                # campaign history on every minute scrape.
                retained_dirs: list[str] = []
                for dirname in dirs:
                    try:
                        if (Path(current) / dirname).stat().st_mtime >= newest_relevant_mtime:
                            retained_dirs.append(dirname)
                    except OSError:
                        continue
                dirs[:] = retained_dirs
            else:
                # A job-NNNNN directory is authoritative ownership. Prune it
                # before os.walk materializes its potentially thousands of
                # per-rank stderr names when that job is outside parse_ids.
                dirs[:] = [
                    dirname for dirname in dirs
                    if not (
                        re.fullmatch(r"job-(\d{5,})", dirname)
                        and re.fullmatch(r"job-(\d{5,})", dirname).group(1) not in job_ids
                    )
                ]
            # Job IDs appear in campaign stdout filenames and job-NNNNN
            # directories. Carry directory matches downward so raw per-test
            # logs without an ID in their basename are still discovered.
            path_tokens = set(re.findall(r"(?<!\d)(\d{5,})(?!\d)", str(Path(current).relative_to(LOG_DIR))))
            inherited = path_tokens & job_ids
            for filename in files:
                if Path(filename).suffix.lower() not in LOG_SUFFIXES:
                    continue
                file_tokens = set(re.findall(r"(?<!\d)(\d{5,})(?!\d)", filename)) & job_ids
                for job_id in inherited | file_tokens:
                    found[job_id].append(Path(current) / filename)
    except OSError:
        return found
    return found


def discover_stdout_sibling_logs(stdout: str, job_id: str) -> list[Path]:
    """Find job-owned application logs beside the scheduler stdout path."""
    if not stdout:
        return []
    parent = Path(stdout).parent
    try:
        is_directory = parent.is_dir()
    except OSError:
        return []
    if not is_directory:
        return []
    found: list[Path] = []
    try:
        entries = os.scandir(parent)
    except OSError:
        return found
    with entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False) or Path(entry.name).suffix.lower() not in LOG_SUFFIXES:
                continue
            tokens = set(re.findall(r"(?<!\d)(\d{5,})(?!\d)", entry.name))
            if job_id in tokens:
                found.append(Path(entry.path))
    return found


def tail_text(path: Path) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - TAIL_BYTES))
            data = handle.read(TAIL_BYTES)
        if size > TAIL_BYTES:
            data = data.split(b"\n", 1)[-1]
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def last_float(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not matches:
        return None
    value = matches[-1]
    if isinstance(value, tuple):
        value = value[-1]
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def benign_error_line(line: str) -> bool:
    """Recognize exact, proven non-fatal startup/status messages.

    Keep this deliberately narrow: genuine PMIx, NCCL, CUDA, NVML, Xid, and
    MNUberGEMM errors must continue to contribute to the dashboard counters.
    """
    normalized = line.strip()
    if normalized == "!A! - Authentication error, communication disabled.":
        # nvidia-imex-ctl connectivity-table legend, not a reported node state.
        return True
    if re.search(r"PMIX ERROR: ERROR in file gds_ds12_lock_pthread\.c at line 168$", normalized):
        return True
    return bool(
        re.search(
            r"NCCL INFO TUNER/Plugin: Failed to find ncclTunerPlugin_v[234] symbol"
            r"(?:, using internal tuner instead)?\.$",
            normalized,
        )
    )


def parse_logs(paths: list[Path]) -> dict[str, object]:
    stats: list[tuple[Path, os.stat_result]] = []
    for path in paths:
        try:
            stats.append((path, path.stat()))
        except OSError:
            pass
    # Dedicated per-rank NCCL INFO captures can be many MiB and duplicate the
    # launcher/raw correctness result. Prefer application/raw/summary files;
    # fall back to NCCL INFO only when it is the sole evidence available.
    preferred_stats = [item for item in stats if "nccl-info" not in item[0].name.lower()]
    if preferred_stats:
        stats = preferred_stats
    stats.sort(key=lambda item: item[1].st_mtime)
    chosen = stats[-MAX_FILES_PER_JOB:]
    text = "\n".join(tail_text(path) for path, _ in chosen)
    # Parse progress across the entire bounded byte window. Verbose NCCL INFO can
    # exceed 10,000 lines between NeMo iterations; only error counters use the
    # narrower line window.
    lines = text.splitlines()[-10000:]
    iteration_matches = re.findall(r"\biteration\s+(\d+)\s*/\s*(\d+)", text, flags=re.IGNORECASE)
    progress_current = progress_total = None
    if iteration_matches:
        progress_current, progress_total = (float(value) for value in iteration_matches[-1])
    tests_total = last_float(r"\btests\s*=\s*(\d+)", text)
    concluded = len(re.findall(r"Collective test concluded", text, flags=re.IGNORECASE))
    collected = last_float(r"collective\s+blocks\s*=\s*(\d+)", text)
    nccl_completed = max(float(concluded), collected or 0.0)
    if progress_current is None and nccl_completed and tests_total:
        progress_current, progress_total = nccl_completed, tests_total
    error_re = re.compile(r"(?i)(\berror\b|exception|traceback|\bfailed\b|\bfailure\b|(?<!non-)\bfatal\b|xid|out.of.memory|\boom\b|timeout|cancelled|node_fail|MNUB \[E\])")
    warning_re = re.compile(r"(?i)(warn|warning)")
    slurm_error_re = re.compile(r"(?i)(slurm|srun|slurmstepd|step).*?(error|failed|cancel|terminat|timeout|node_fail)")
    xid_re = re.compile(
        r"(?i)\b(?:xid|cuda(?: runtime)? error|cudart error)\b"
        r"|\bnvml\b.*\b(?:error|failed|failure)\b"
        r"|\b(?:error|failed|failure)\b.*\bnvml\b"
    )
    nccl_re = re.compile(r"(?i)\b(nccl|collective|all_reduce|allreduce|bus bandwidth)\b")
    expected_got = re.compile(
        r"(?i)\[(\d+)\].*?\b(reduce[- ]scatter|all[- ]reduce|all[- ]gather|all[- ]to[- ]all|sendrecv)"
        r".*?\bSM\s+(\d+)\s+\[(\d+)\].*?\bexpecting\s+([^\s]+)\s+got\s+([^\s]+)"
    )
    correctness_sample_counts: dict[tuple[str, ...], int] = {}
    expected_got_failures = 0
    for line in text.splitlines():
        match = expected_got.search(line)
        if match:
            expected_got_failures += 1
            gpu, collective, sm, lane, expected, actual = match.groups()
            key = (gpu, collective.lower().replace(" ", "-"), sm, lane, expected, actual)
            if key in correctness_sample_counts or len(correctness_sample_counts) < 32:
                correctness_sample_counts[key] = correctness_sample_counts.get(key, 0) + 1
    correctness_samples = [
        {
            "kind": "expected_got", "gpu": gpu, "collective": collective,
            "sm": sm, "lane": lane, "expected": expected, "actual": actual,
            "occurrences": str(occurrences),
        }
        for (gpu, collective, sm, lane, expected, actual), occurrences in correctness_sample_counts.items()
    ]
    oob_values = [float(value) for value in re.findall(
        r"(?im)^\s*#\s*Out of bounds values\s*:\s*(\d+)", text
    )]
    nccl_wrong_values = 0.0
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 13 and fields[0].isdigit() and fields[1].isdigit():
            try:
                nccl_wrong_values = max(nccl_wrong_values, float(fields[8]) + float(fields[12]))
            except (ValueError, IndexError):
                pass
    return {
        "files": chosen,
        "bytes": float(sum(item.st_size for _, item in stats)),
        "mtime": float(max((item.st_mtime for _, item in stats), default=0.0)),
        "error_lines": float(
            sum(
                bool(error_re.search(line))
                and "no error" not in line.lower()
                and "non-fatal async event" not in line.lower()
                and not benign_error_line(line)
                for line in lines
            )
        ),
        "warning_lines": float(sum(bool(warning_re.search(line)) for line in lines)),
        "slurm_error_lines": float(sum(bool(slurm_error_re.search(line)) for line in lines)),
        "xid_lines": float(sum(bool(xid_re.search(line)) for line in lines)),
        "nccl_lines": float(sum(bool(nccl_re.search(line)) for line in lines)),
        "progress_current": progress_current,
        "progress_total": progress_total,
        "step_time": last_float(r"Step Time\s*:\s*([0-9.]+)\s*s", text),
        "tflops": last_float(r"([0-9.]+)\s*(?:MODEL_)?TFLOP/s/GPU", text),
        "loss": last_float(r"\blm loss\s*:\s*([0-9.eE+\-]+)", text),
        "nccl_completed": nccl_completed,
        "nccl_total": tests_total,
        "nccl_bus_bw": last_float(r"Avg bus bandwidth\s*:\s*([0-9.]+)", text),
        "correctness_failures": float(expected_got_failures + sum(value > 0 for value in oob_values)),
        "expected_got_failures": float(expected_got_failures),
        "nccl_oob_failed_tests": float(sum(value > 0 for value in oob_values)),
        "nccl_wrong_values": nccl_wrong_values,
        "correctness_samples": correctness_samples,
    }


def escape_label(value: object, limit: int = 240) -> str:
    text = str(value or "unknown").replace("\n", " ").replace("\r", " ")[:limit]
    return text.replace("\\", "\\\\").replace('"', '\\"')


class Prometheus:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.seen: set[str] = set()

    def emit(self, name: str, value: float | int, labels: dict[str, object] | None = None, help_text: str = "") -> None:
        if value is None or not math.isfinite(float(value)):
            return
        if name not in self.seen:
            self.lines.extend([f"# HELP {name} {help_text or name}", f"# TYPE {name} gauge"])
            self.seen.add(name)
        label_text = ""
        if labels:
            label_text = "{" + ",".join(f'{key}="{escape_label(val)}"' for key, val in sorted(labels.items())) + "}"
        self.lines.append(f"{name}{label_text} {float(value):.12g}")


def load_state() -> dict[str, object]:
    try:
        value = json.loads(STATE_FILE.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_atomic(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def build_active_telemetry_targets(
    records: dict[str, dict[str, object]], active: set[str]
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, int]]:
    """Build bounded file-SD targets for active validation allocations only.

    Prometheus runs in a Docker network whose resolver cannot resolve the
    compute-node names, so resolution happens once here on the host.  Labels
    retain the canonical hostname for job-to-node joins and operator display.
    """
    candidates: dict[str, dict[str, str]] = {}
    expected = 0
    truncated = 0
    for job_id in sorted(active, key=lambda value: int(value)):
        rec = records.get(job_id) or {}
        state = clean_state(str(rec.get("state") or "UNKNOWN"))
        workload = workload_for(rec)
        if state not in ACTIVE_TELEMETRY_STATES or workload not in ACTIVE_TELEMETRY_WORKLOADS:
            continue
        nodes = expand_hostlist(str(rec.get("nodelist") or ""), limit=JOB_NODE_LIMIT)
        expected += len(nodes)
        for node in nodes:
            if node in candidates:
                continue
            if len(candidates) >= ACTIVE_TELEMETRY_NODE_LIMIT:
                truncated += 1
                continue
            datahall, rack, su = topology_for_node(node)
            candidates[node] = {
                "job_id": job_id,
                "workload": workload,
                "node": node,
                "instance": node,
                "rack": rack,
                "su": su,
                "datahall": datahall,
                "telemetry_scope": "active-validation",
            }

    node_groups: list[dict[str, object]] = []
    dcgm_groups: list[dict[str, object]] = []
    dns_failed = 0
    for node, labels in candidates.items():
        try:
            ip = socket.gethostbyname(node)
        except OSError:
            dns_failed += 1
            continue
        node_groups.append({"targets": [f"{ip}:9100"], "labels": labels})
        dcgm_groups.append({"targets": [f"{ip}:9400"], "labels": labels})
    stats = {
        "expected": expected,
        "selected": len(candidates),
        "resolved": len(node_groups),
        "dns_failed": dns_failed,
        "truncated": truncated,
    }
    return node_groups, dcgm_groups, stats


def main() -> int:
    started = time.monotonic()
    now = time.time()
    output_path = Path(sys.argv[1] if len(sys.argv) > 1 else "/var/lib/node_exporter/textfile_collector/jobs.prom")
    records, sacct_error = read_sacct()
    active, scontrol_error = merge_active(records)
    records = retain_history(records)
    parse_ids = set(active)
    parse_ids.update(list(records.keys())[-PARSE_LIMIT:])
    historical_parse_ids = [
        job_id for job_id, rec in records.items()
        if number(rec.get("requested_nodes")) >= HISTORICAL_MIN_NODES
        and workload_for(rec) in ACTIVE_TELEMETRY_WORKLOADS
    ][-HISTORICAL_PARSE_LIMIT:]
    parse_ids.update(historical_parse_ids)
    logs_by_job = discover_logs(parse_ids)
    prior_state = load_state()
    next_state: dict[str, object] = {}
    prom = Prometheus()

    for job_id, rec in records.items():
        state = clean_state(str(rec.get("state", "UNKNOWN")))
        rec["state"] = state
        workload = workload_for(rec)
        is_active = job_id in active
        stdout = str(rec.get("stdout", ""))
        stdout_file = Path(stdout).name if stdout else "unknown"
        info_labels = {
            "job_id": job_id,
            "job_name": rec.get("job_name", "unknown"),
            "user": rec.get("user", "unknown"),
            "partition": rec.get("partition", "unknown"),
            "state": state,
            "reason": rec.get("reason", "None"),
            "workload": workload,
            "stdout_file": stdout_file,
            "requested_nodelist": rec.get("requested_nodelist", "unknown"),
            "exit_code": rec.get("exit_code", "unknown"),
        }
        prom.emit("nvis_slurm_job_info", 1, info_labels, "Slurm job identity and current/latest scheduler record")
        labels = {"job_id": job_id}
        prom.emit("nvis_slurm_job_state_code", STATE_CODES.get(state, 0), {**labels, "state": state}, "Numeric Slurm state for Grafana value mapping")
        prom.emit("nvis_slurm_job_active", int(is_active), labels, "Whether the job is present in the active Slurm queue")
        reason_text = str(rec.get("reason", "None")).lower()
        exit_text = str(rec.get("exit_code", "0:0"))
        scheduler_issue = int(
            state in {"FAILED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY", "CANCELLED"}
            or exit_text not in {"", "0:0", "unknown"}
            or any(token in reason_text for token in ("launch_failed", "failed", "held", "node_fail", "timeout", "cancel"))
        )
        prom.emit(
            "nvis_slurm_job_scheduler_issue", scheduler_issue, labels,
            "Scheduler state, reason, or exit code indicates a job issue",
        )
        prom.emit("nvis_slurm_job_submit_timestamp_seconds", number(rec.get("submit_ts")), labels)
        prom.emit("nvis_slurm_job_eligible_timestamp_seconds", number(rec.get("eligible_ts")), labels)
        if number(rec.get("start_ts")):
            prom.emit("nvis_slurm_job_start_timestamp_seconds", number(rec.get("start_ts")), labels)
        if number(rec.get("end_ts")):
            prom.emit("nvis_slurm_job_end_timestamp_seconds", number(rec.get("end_ts")), labels)
        prom.emit("nvis_slurm_job_elapsed_seconds", number(rec.get("elapsed")), labels)
        prom.emit("nvis_slurm_job_timelimit_seconds", number(rec.get("timelimit")), labels)
        prom.emit("nvis_slurm_job_requested_nodes", number(rec.get("requested_nodes")), labels)
        prom.emit("nvis_slurm_job_allocated_nodes", number(rec.get("allocated_nodes")), labels)
        prom.emit("nvis_slurm_job_cpus", number(rec.get("cpus")), labels)
        prom.emit("nvis_slurm_job_requested_gpus", number(rec.get("requested_gpus")), labels)
        prom.emit("nvis_slurm_job_allocated_gpus", number(rec.get("allocated_gpus")), labels)
        submit_ts = number(rec.get("submit_ts"))
        eligible_ts = number(rec.get("eligible_ts")) or submit_ts
        start_ts = number(rec.get("start_ts"))
        prom.emit("nvis_slurm_job_age_seconds", max(0.0, now - submit_ts) if submit_ts else 0.0, labels)
        if state == "PENDING":
            queue_age = max(0.0, now - eligible_ts) if eligible_ts else 0.0
        elif start_ts and eligible_ts:
            queue_age = max(0.0, start_ts - eligible_ts)
        else:
            queue_age = 0.0
        prom.emit("nvis_slurm_job_queue_age_seconds", queue_age, labels)

        allocation = "requested" if state == "PENDING" else "allocated"
        compact_nodes = str(rec.get("requested_nodelist" if state == "PENDING" else "nodelist", ""))
        expanded_nodes = expand_hostlist(compact_nodes)
        expected_nodes = int(number(rec.get("requested_nodes" if state == "PENDING" else "allocated_nodes")))
        prom.emit(
            "nvis_slurm_job_node_edges_expected", expected_nodes, labels,
            "Scheduler-reported node count expected in the JobID to node bridge",
        )
        prom.emit(
            "nvis_slurm_job_node_edges_emitted", len(expanded_nodes), labels,
            "Expanded node membership edges emitted for this JobID",
        )
        prom.emit(
            "nvis_slurm_job_node_mapping_complete", int(len(expanded_nodes) == expected_nodes), labels,
            "1 only when emitted JobID membership edges equal the scheduler-reported node count",
        )
        for node in expanded_nodes:
            datahall, rack, su = topology_for_node(node)
            prom.emit(
                "nvis_slurm_job_node_info", 1,
                {"job_id": job_id, "node": node, "rack": rack, "su": su, "datahall": datahall, "allocation": allocation},
                "Requested or allocated compute nodes for active jobs",
            )

        parsed: dict[str, object] = {}
        if job_id in parse_ids:
            candidates = list(logs_by_job.get(job_id, []))
            for sibling in discover_stdout_sibling_logs(stdout, job_id):
                if sibling not in candidates:
                    candidates.append(sibling)
            if stdout:
                stdout_path = Path(stdout)
                try:
                    is_file = stdout_path.is_file()
                except OSError:
                    is_file = False
                if is_file and stdout_path not in candidates:
                    candidates.append(stdout_path)
            parsed = parse_logs(candidates)
        files = parsed.get("files", []) if parsed else []
        prom.emit("nvis_slurm_job_log_files", len(files), labels, "Number of matching job log files parsed")
        if parsed:
            for path, file_stat in files:
                kind = "autocollect" if "autocollect" in path.name.lower() else "stdout"
                file_labels = {**labels, "filename": path.name, "log_kind": kind}
                prom.emit("nvis_slurm_job_log_file_info", 1, file_labels, "Matching top-level benchmark log file")
                prom.emit("nvis_slurm_job_log_file_bytes", file_stat.st_size, file_labels)
            prom.emit("nvis_slurm_job_log_bytes", number(parsed.get("bytes")), labels)
            mtime = number(parsed.get("mtime"))
            if mtime:
                prom.emit("nvis_slurm_job_log_mtime_seconds", mtime, labels)
                prom.emit("nvis_slurm_job_log_age_seconds", max(0.0, now - mtime), labels)
            for key in ("error_lines", "warning_lines", "slurm_error_lines", "xid_lines", "nccl_lines"):
                prom.emit(f"nvis_slurm_job_log_tail_{key}", number(parsed.get(key)), labels, "Matches in the bounded job-log tail")
            progress_current = parsed.get("progress_current")
            progress_total = parsed.get("progress_total")
            if progress_current is not None and progress_total is not None and number(progress_total) > 0:
                prom.emit("nvis_slurm_job_progress_current", number(progress_current), labels)
                prom.emit("nvis_slurm_job_progress_total", number(progress_total), labels)
                prom.emit("nvis_slurm_job_progress_ratio", min(1.0, number(progress_current) / number(progress_total)), labels)
            for metric, key in (
                ("nvis_slurm_job_latest_step_time_seconds", "step_time"),
                ("nvis_slurm_job_latest_tflops_per_gpu", "tflops"),
                ("nvis_slurm_job_latest_loss", "loss"),
                ("nvis_slurm_job_nccl_completed_tests", "nccl_completed"),
                ("nvis_slurm_job_nccl_total_tests", "nccl_total"),
                ("nvis_slurm_job_nccl_avg_bus_bandwidth_gbps", "nccl_bus_bw"),
                ("nvis_slurm_job_correctness_failures", "correctness_failures"),
                ("nvis_slurm_job_expected_got_failures", "expected_got_failures"),
                ("nvis_slurm_job_nccl_oob_failed_tests", "nccl_oob_failed_tests"),
                ("nvis_slurm_job_nccl_wrong_values", "nccl_wrong_values"),
            ):
                if parsed.get(key) is not None:
                    prom.emit(metric, number(parsed.get(key)), labels)
            for sample in parsed.get("correctness_samples", []):
                if isinstance(sample, dict):
                    sample_labels = {key: value for key, value in sample.items() if key != "occurrences"}
                    prom.emit(
                        "nvis_slurm_job_correctness_sample_info", number(sample.get("occurrences"), 1),
                        {**labels, **sample_labels},
                        "Bounded exact expected/got correctness evidence from the application log",
                    )

        progress_marker = parsed.get("progress_current") if parsed else None
        if progress_marker is None:
            progress_marker = number(parsed.get("bytes")) if parsed else 0.0
        prior = prior_state.get(job_id, {}) if isinstance(prior_state.get(job_id), dict) else {}
        marker_text = f"{state}:{progress_marker}"
        last_change = number(prior.get("last_change"), now)
        if prior.get("marker") != marker_text or state != "RUNNING":
            last_change = now
        stalled_seconds = max(0.0, now - last_change) if state == "RUNNING" else 0.0
        run_age = max(number(rec.get("elapsed")), max(0.0, now - start_ts) if start_ts else 0.0)
        stalled_threshold = stall_threshold_seconds(workload)
        stuck = int(state == "RUNNING" and run_age >= 600 and stalled_seconds >= stalled_threshold)
        prom.emit("nvis_slurm_job_progress_stalled_seconds", stalled_seconds, labels)
        prom.emit(
            "nvis_slurm_job_stuck",
            stuck,
            labels,
            "Running job exceeded its workload-aware no-log/progress threshold",
        )
        next_state[job_id] = {"marker": marker_text, "last_change": last_change, "seen": now}

    errors = [error for error in (sacct_error, scontrol_error) if error]
    telemetry_stats = {
        "expected": 0, "selected": 0, "resolved": 0, "dns_failed": 0, "truncated": 0,
    }
    if not scontrol_error:
        node_targets, dcgm_targets, telemetry_stats = build_active_telemetry_targets(records, active)
        write_atomic(ACTIVE_NODE_TARGETS_FILE, json.dumps(node_targets, separators=(",", ":")) + "\n")
        write_atomic(ACTIVE_DCGM_TARGETS_FILE, json.dumps(dcgm_targets, separators=(",", ":")) + "\n")
    for key, value in telemetry_stats.items():
        prom.emit(
            f"nvis_slurm_active_telemetry_{key}_nodes",
            value,
            help_text=f"Active validation telemetry target discovery: {key} nodes",
        )
    prom.emit(
        "nvis_slurm_active_telemetry_discovery_success",
        int(not scontrol_error),
        help_text="Whether active validation telemetry discovery used a current Slurm snapshot",
    )
    prom.emit("nvis_slurm_collector_success", int(not errors), help_text="Whether Slurm accounting and controller snapshots both succeeded")
    prom.emit("nvis_slurm_collector_duration_seconds", time.monotonic() - started)
    prom.emit("nvis_slurm_jobs_observed", len(records))
    prom.emit("nvis_slurm_active_jobs_observed", len(active))
    prom.emit("nvis_slurm_collector_errors", len(errors))
    write_atomic(output_path, "\n".join(prom.lines) + "\n")
    write_atomic(STATE_FILE, json.dumps(next_state, separators=(",", ":")) + "\n", mode=0o600)
    if errors:
        print("; ".join(errors), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
