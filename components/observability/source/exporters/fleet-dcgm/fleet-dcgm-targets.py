#!/usr/bin/env python3
"""Publish bounded file-SD targets for fleet GPU reliability counters.

The DCGM endpoint is small (~26 KiB / 174 samples per GB300 tray), but the
Prometheus jobs retain only operator-facing GPU and host/HCA families. One
bounded Slurm query also publishes the live node-state worklist; target files
are rewritten only when membership changes.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time


SLURM_BIN = Path(os.environ.get("SLURM_BIN", "/cm/local/apps/slurm/current/bin"))
SLURM_CONF = os.environ.get("SLURM_CONF", "/cluster/slurm/etc/slurm/slurm.conf")
TARGET_FILE = Path(os.environ.get(
    "NVIS_FLEET_DCGM_TARGETS_FILE",
    "/var/lib/nvis-observability/prometheus-targets/fleet-dcgm.json",
))
NODE_TARGET_FILE = Path(os.environ.get(
    "NVIS_FLEET_NODE_TARGETS_FILE",
    "/var/lib/nvis-observability/prometheus-targets/fleet-node.json",
))
METRICS_FILE = Path(os.environ.get(
    "NVIS_FLEET_DCGM_METRICS_FILE",
    "/var/lib/prometheus/node-exporter/nvis-fleet-dcgm.prom",
))
NODE_LIMIT = max(1, min(4096, int(os.environ.get("NVIS_FLEET_DCGM_NODE_LIMIT", "4096"))))
RESOLVE_WORKERS = max(1, min(64, int(os.environ.get("NVIS_FLEET_DCGM_RESOLVE_WORKERS", "32"))))


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def write_if_changed(path: Path, content: str) -> None:
    try:
        if path.read_text() == content:
            return
    except FileNotFoundError:
        pass
    write_atomic(path, content)


def topology(node: str) -> tuple[str, str, str]:
    match = re.match(r"example50-(dh01|dh02)-([a-z])(\d+)-", node)
    if not match:
        return "unknown", "unknown", "unknown"
    hall, letter, ordinal = match.groups()
    datahall = f"{'WH1' if hall == 'dh01' else 'EH1'}{letter.upper()}"
    rack = f"{datahall}{int(ordinal)}"
    if hall == "dh02" and "a" <= letter <= "k":
        number = ord(letter) - ord("a") + 1
    elif hall == "dh01" and "a" <= letter <= "c":
        number = ord(letter) - ord("a") + 12
    else:
        number = 0
    return datahall, rack, f"SU{number}" if number else "unknown"


def read_node_records() -> list[dict]:
    environment = os.environ.copy()
    environment["SLURM_CONF"] = SLURM_CONF
    result = subprocess.run(
        [str(SLURM_BIN / "scontrol"), "show", "nodes", "--json"],
        env=environment,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    payload = json.loads(result.stdout)
    nodes = []
    for record in payload.get("nodes", []):
        name = str(record.get("name") or "")
        gres = str(record.get("gres") or "")
        if name and "gpu:" in gres:
            nodes.append(record)
    return sorted(nodes, key=lambda record: str(record.get("name")))[:NODE_LIMIT]


def resolve(node: str) -> tuple[str, str | None]:
    try:
        return node, socket.gethostbyname(node)
    except OSError:
        return node, None


def prom_label(value: object) -> str:
    return str(value or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def prometheus_metrics(
    records: list[dict], resolved: int, duration: float, success: int
) -> str:
    expected = len(records)
    values = {
        "nvis_fleet_dcgm_discovery_success": success,
        "nvis_fleet_dcgm_expected_nodes": expected,
        "nvis_fleet_dcgm_resolved_nodes": resolved,
        "nvis_fleet_dcgm_dns_failed_nodes": expected - resolved,
        "nvis_fleet_dcgm_discovery_duration_seconds": duration,
        "nvis_fleet_dcgm_discovery_timestamp_seconds": time.time(),
    }
    lines = []
    for name, value in values.items():
        lines.extend((f"# TYPE {name} gauge", f"{name} {value}"))
    lines.extend((
        "# HELP nvis_slurm_node_info Live Slurm state for every GPU compute node.",
        "# TYPE nvis_slurm_node_info gauge",
        "# HELP nvis_slurm_node_available One when Slurm reports the node IDLE without a blocking flag.",
        "# TYPE nvis_slurm_node_available gauge",
    ))
    blocking = {"DOWN", "DRAIN", "DRAINED", "FAIL", "FAILING", "MAINT", "NOT_RESPONDING", "POWER_DOWN"}
    for record in records:
        node = str(record.get("name") or "")
        state_values = record.get("state") or []
        if isinstance(state_values, str):
            state_values = [state_values]
        states = [str(value).upper() for value in state_values if value]
        state_set = set(states)
        if "DOWN" in state_set:
            state_class = "down"
        elif state_set & {"DRAIN", "DRAINED", "FAIL", "FAILING", "MAINT"}:
            state_class = "drained"
        elif "NOT_RESPONDING" in state_set:
            state_class = "not_responding"
        elif state_set & {"ALLOCATED", "MIXED", "COMPLETING"}:
            state_class = "allocated"
        elif "IDLE" in state_set:
            state_class = "idle"
        else:
            state_class = "other"
        available = int("IDLE" in state_set and not state_set.intersection(blocking))
        datahall, rack, su = topology(node)
        reason = str(record.get("reason") or "")[:256]
        partitions = record.get("partitions") or []
        if isinstance(partitions, str):
            partitions = [partitions]
        labels = {
            "node": node,
            "instance": node,
            "cluster": "IREN_MKZ",
            "datahall": datahall,
            "rack": rack,
            "su": su,
            "state": state_class,
            "states": "+".join(states) or "UNKNOWN",
            "reason": reason or "none",
            "partition": "+".join(str(value) for value in partitions) or "none",
        }
        rendered = ",".join(f'{key}="{prom_label(value)}"' for key, value in labels.items())
        lines.append(f"nvis_slurm_node_info{{{rendered}}} 1")
        lines.append(f'nvis_slurm_node_available{{node="{prom_label(node)}",su="{prom_label(su)}",rack="{prom_label(rack)}"}} {available}')
    return "\n".join(lines) + "\n"


def main() -> int:
    started = time.monotonic()
    try:
        records = read_node_records()
        nodes = [str(record.get("name")) for record in records]
        with concurrent.futures.ThreadPoolExecutor(max_workers=RESOLVE_WORKERS) as pool:
            resolved = list(pool.map(resolve, nodes))
        targets = []
        node_targets = []
        for node, address in resolved:
            if not address:
                continue
            datahall, rack, su = topology(node)
            targets.append({
                "targets": [f"{address}:9400"],
                "labels": {
                    "cluster": "IREN_MKZ",
                    "node": node,
                    "instance": node,
                    "datahall": datahall,
                    "rack": rack,
                    "su": su,
                    "telemetry_scope": "fleet-reliability",
                },
            })
            node_targets.append({
                "targets": [f"{address}:9100"],
                "labels": {
                    "cluster": "IREN_MKZ",
                    "node": node,
                    "instance": node,
                    "datahall": datahall,
                    "rack": rack,
                    "su": su,
                    "telemetry_scope": "fleet-host-health",
                },
            })
        write_if_changed(TARGET_FILE, json.dumps(targets, separators=(",", ":")) + "\n")
        write_if_changed(NODE_TARGET_FILE, json.dumps(node_targets, separators=(",", ":")) + "\n")
        write_atomic(METRICS_FILE, prometheus_metrics(
            records, len(targets), time.monotonic() - started, 1,
        ))
        print(f"fleet DCGM targets: expected={len(nodes)} resolved={len(targets)}")
        return 0
    except Exception as error:
        # Preserve the last known-good target file; only the discovery-health
        # metric changes so an operator sees the stale-control-plane condition.
        write_atomic(METRICS_FILE, prometheus_metrics([], 0, time.monotonic() - started, 0))
        print(f"fleet DCGM discovery failed: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
