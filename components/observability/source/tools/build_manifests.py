#!/usr/bin/env python3
"""Build source mapping, file inventory, and SHA-256 manifest."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_for(rel: str, dashboard_uid_by_file: dict[str, str]) -> tuple[str, str]:
    if rel in dashboard_uid_by_file:
        uid = dashboard_uid_by_file[rel]
        return f"Grafana API GET /api/dashboards/uid/{uid}", "id cleared; UID preserved"
    api_sources = {
        "grafana-live/folders.json": "Grafana API GET /api/search + /api/folders",
        "grafana-live/dashboard-search-index.json": "Grafana API GET /api/search?limit=5000",
        "grafana-live/datasources.sanitized.json": "Grafana API GET /api/datasources",
        "grafana-live/contact-points.sanitized.json": "Grafana API GET /api/v1/provisioning/contact-points",
        "grafana-live/alert-rules.json": "Grafana API GET /api/v1/provisioning/alert-rules",
        "grafana-live/notification-policies.sanitized.json": "Grafana API GET /api/v1/provisioning/policies",
        "grafana-live/mute-timings.json": "Grafana API GET /api/v1/provisioning/mute-timings",
        "grafana-live/grafana-health.json": "Grafana API GET /api/health",
    }
    if rel in api_sources:
        note = "secret-bearing setting values redacted" if "sanitized" in rel else "read-only API export"
        return api_sources[rel], note
    if rel.startswith("core/systemd/"):
        return "/etc/systemd/system/" + rel.rsplit("/", 1)[1], "exact active unit"
    if rel == "core/victoriametrics.compose.yml":
        return "docker inspect nvis-victoria-metrics + active compose overrides", "portable reconstruction; no volume data"
    if rel.startswith("core/") and rel not in {"core/core.env.example"}:
        return "/opt/observability/iren_mkz/deploy/16k-core/" + rel[len("core/"):], "active bind-mounted source"
    if rel.startswith("exporters/redfish-reachability/"):
        return "/usr/local/lib/nvis-redfish-reachability and /etc/systemd/system", "live targets and credentials excluded"
    if rel.startswith("exporters/"):
        name = rel.rsplit("/", 1)[1]
        if name.endswith((".service", ".timer")):
            return "/etc/systemd/system/" + name, "exact active unit"
        return "/opt/observability/iren_mkz/exporters/", "active exporter source"
    if rel.startswith("datalake/"):
        return "/cluster/OVA/hlakshminara/opt/iren_mkz-16k-services/datalake/" + rel[len("datalake/"):], "source/config only; lake runtime excluded"
    if rel.startswith("node-agents/"):
        return "ssh://example50-dh02-a01-11 live unit/config readback", "representative idle-node snapshot"
    if rel.startswith("inventory/grafana-db") or rel == "inventory/grafana-api-db-reconciliation.json":
        return "/cluster/observability/iren_mkz/grafana/grafana.db?mode=ro", "counts/UID digests only; database excluded"
    return "portable overlay generated artifact", "no live secret/runtime data"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    dashboard_uid_by_file = {}
    for line in (root / "grafana-live/dashboard-inventory.tsv").read_text().splitlines()[1:]:
        uid, _, _, _, relative = line.split("\t", 4)
        dashboard_uid_by_file["grafana-live/" + relative] = uid

    excluded = {"MANIFEST.sha256", "FILE_INVENTORY.tsv", "SOURCE_MAP.tsv"}
    initial = sorted(path for path in root.rglob("*") if path.is_file() and path.relative_to(root).as_posix() not in excluded)
    source_lines = ["package_path\tsource_location\tnote"]
    for path in initial:
        rel = path.relative_to(root).as_posix()
        source, note = source_for(rel, dashboard_uid_by_file)
        source_lines.append(f"{rel}\t{source}\t{note}")
    (root / "SOURCE_MAP.tsv").write_text("\n".join(source_lines) + "\n")

    paths = sorted(path for path in root.rglob("*") if path.is_file() and path.name not in {"MANIFEST.sha256", "FILE_INVENTORY.tsv"})
    inventory_lines = ["path\tbytes\tmode\tsha256"]
    for path in paths:
        rel = path.relative_to(root).as_posix()
        inventory_lines.append(f"{rel}\t{path.stat().st_size}\t{path.stat().st_mode & 0o777:04o}\t{sha(path)}")
    (root / "FILE_INVENTORY.tsv").write_text("\n".join(inventory_lines) + "\n")

    manifest_paths = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "MANIFEST.sha256")
    manifest_lines = [f"{sha(path)}  {path.relative_to(root).as_posix()}" for path in manifest_paths]
    (root / "MANIFEST.sha256").write_text("\n".join(manifest_lines) + "\n")
    print(json.dumps({
        "manifest_payload_files": len(manifest_paths),
        "payload_bytes": sum(path.stat().st_size for path in manifest_paths),
        "manifest_sha256": sha(root / "MANIFEST.sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
