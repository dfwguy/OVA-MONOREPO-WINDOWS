#!/usr/bin/env python3
"""Capture component versions and source locations without environment values."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


CONTAINERS = [
    "nvis16k-grafana",
    "nvis16k-prometheus",
    "nvis-victoria-metrics",
    "nvis16k-loki",
    "nvis16k-alloy",
    "nvis-16k-lakewriter",
    "nvis-16k-lake-reconcile",
    "nvis-16k-lake-logs",
    "iren_mkz-validation-exporter",
]

UNITS = [
    "nvis-observability-core.service",
    "nvis-redfish-reachability.service",
    "nvis-ufm-telemetry-exporter.service",
    "nvis-slurm-job-collector.service",
    "nvis-slurm-job-collector.timer",
    "nvis-single-node-metrics.service",
    "nvis-single-node-metrics.timer",
    "nvis-fleet-dcgm-targets.service",
    "nvis-fleet-dcgm-targets.timer",
    "nvis-headnode-attribution-exporter.service",
]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    inspected = json.loads(subprocess.check_output(["docker", "inspect", *CONTAINERS]))
    containers = []
    for item in inspected:
        labels = item.get("Config", {}).get("Labels") or {}
        containers.append({
            "name": item["Name"].lstrip("/"),
            "image": item["Config"]["Image"],
            "command": item["Config"].get("Cmd") or [],
            "environment_keys": sorted(entry.split("=", 1)[0] for entry in item["Config"].get("Env") or []),
            "mounts": [
                {"type": mount["Type"], "source": mount.get("Source", ""), "destination": mount["Destination"], "mode": mount.get("Mode", "")}
                for mount in item.get("Mounts", [])
            ],
            "compose_project": labels.get("com.docker.compose.project", ""),
            "compose_files": labels.get("com.docker.compose.project.config_files", ""),
            "compose_working_directory": labels.get("com.docker.compose.project.working_dir", ""),
        })

    units = []
    for unit in UNITS:
        output = subprocess.check_output([
            "systemctl", "show", unit, "--no-pager",
            "-p", "Id", "-p", "LoadState", "-p", "ActiveState", "-p", "FragmentPath", "-p", "DropInPaths",
        ], text=True)
        values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        units.append(values)

    health = json.loads((root / "grafana-live/grafana-health.json").read_text())
    summary = json.loads((root / "grafana-live/export-summary.json").read_text())
    payload = {
        "grafana": {"version": health.get("version"), "commit": health.get("commit"), **summary},
        "containers": sorted(containers, key=lambda item: item["name"]),
        "systemd_units": units,
        "notes": [
            "Environment variable names are recorded; values are intentionally omitted.",
            "Storage/data mounts are recorded as source-location metadata; runtime data is not included.",
            "Container status, PIDs, timestamps, and logs are intentionally omitted.",
        ],
    }
    path = root / "inventory/component-inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
