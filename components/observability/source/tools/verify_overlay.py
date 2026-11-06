#!/usr/bin/env python3
"""Fail-closed checks for the portable live observability overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path


PRIVATE_KEY = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
LITERAL_SECRET = re.compile(
    rb"(?im)^\s*(?:AWS_SECRET_ACCESS_KEY|GF_SECURITY_ADMIN_PASSWORD|PASSWORD|TOKEN|API_KEY)\s*[:=]\s*(?!\$\{|<)[^\s#]{8,}\s*$"
)
URL_USERINFO = re.compile(rb"https?://[^/@\s:]+:[^/@\s]+@")


def api_json(url: str):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--grafana-url", default="http://127.0.0.1:3002")
    parser.add_argument("--skip-live", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    failures = []

    inventory_lines = (root / "grafana-live/dashboard-inventory.tsv").read_text().splitlines()
    rows = [line.split("\t", 4) for line in inventory_lines[1:] if line]
    exported_uids = {row[0] for row in rows}
    dashboard_files = sorted((root / "grafana-live/dashboards").rglob("*.json"))
    parsed_uids = set()
    for path in dashboard_files:
        dashboard = json.loads(path.read_text())
        uid = dashboard.get("uid")
        if not uid or uid in parsed_uids:
            failures.append(f"invalid or duplicate dashboard uid in {path.relative_to(root)}: {uid}")
        parsed_uids.add(uid)
    if exported_uids != parsed_uids:
        failures.append("dashboard inventory/file UID sets differ")

    summary = json.loads((root / "grafana-live/export-summary.json").read_text())
    if len(exported_uids) != summary["dashboard_count"]:
        failures.append("dashboard count differs from export summary")
    if not args.skip_live:
        live = api_json(args.grafana_url.rstrip("/") + "/api/search?limit=5000")
        live_uids = {item["uid"] for item in live if item.get("type") == "dash-db"}
        if live_uids != exported_uids:
            failures.append(f"live/export dashboard UID mismatch: live={len(live_uids)} export={len(exported_uids)}")

    forbidden_paths = []
    content_hits = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        lowered = rel.lower()
        if any(part in lowered for part in ("/secrets/", "lake-active/", "/runtime/")) or path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}:
            forbidden_paths.append(rel)
        data = path.read_bytes()
        if PRIVATE_KEY.search(data) or LITERAL_SECRET.search(data) or URL_USERINFO.search(data):
            content_hits.append(rel)
    if forbidden_paths:
        failures.append("forbidden secret/runtime paths: " + ", ".join(forbidden_paths))
    if content_hits:
        failures.append("credential-pattern content hits: " + ", ".join(content_hits))

    required = [
        "core/docker-compose.yml",
        "core/prometheus/prometheus.yml",
        "core/loki/loki-config.yaml",
        "core/alloy/config.alloy",
        "core/victoriametrics.compose.yml",
        "exporters/slurm-job/job-collector.py",
        "exporters/redfish-reachability/redfish_reachability_exporter.py",
        "exporters/ufm-telemetry/ufm_telemetry_exporter.py",
        "datalake/lakewriter.py",
        "node-agents/systemd/cgroup-exporter.service",
        "node-agents/systemd/dcgm-exporter.service",
        "node-agents/systemd/node_exporter.service",
    ]
    for rel in required:
        if not (root / rel).is_file():
            failures.append(f"missing required portable artifact: {rel}")

    print(json.dumps({
        "dashboard_count": len(exported_uids),
        "dashboard_file_count": len(dashboard_files),
        "folder_count": summary["folder_count"],
        "datasource_count": summary["datasource_count"],
        "contact_point_count": summary["contact_point_count"],
        "file_count": sum(1 for path in root.rglob("*") if path.is_file()),
        "failures": failures,
    }, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
