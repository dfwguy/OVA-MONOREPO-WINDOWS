#!/usr/bin/env python3
"""Export the live Grafana API surface without exporting secret values."""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path


SENSITIVE_KEY = re.compile(r"password|passwd|secret|token|credential|api.?key|authorization", re.I)


def get_json(base: str, path: str):
    request = urllib.request.Request(base.rstrip("/") + "/" + path.lstrip("/"))
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, json.load(response)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned or "root"


def placeholder(key_path: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "_", key_path).strip("_").upper()
    return "${GRAFANA_SECRET_" + (name or "VALUE") + "}"


def sanitize_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return urllib.parse.urlunsplit((parsed.scheme, hostname + port, parsed.path, "", ""))


def sanitize(value, key_path: str = "value", redact_all_strings: bool = False):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            path = f"{key_path}_{key}"
            if SENSITIVE_KEY.search(str(key)):
                if isinstance(item, bool):
                    result[key] = item
                elif item in (None, "", [], {}):
                    result[key] = item
                else:
                    result[key] = placeholder(path)
            else:
                result[key] = sanitize(item, path, redact_all_strings)
        return result
    if isinstance(value, list):
        return [sanitize(item, f"{key_path}_{index}", redact_all_strings) for index, item in enumerate(value)]
    if redact_all_strings and isinstance(value, str) and value:
        return placeholder(key_path)
    if isinstance(value, str) and re.match(r"^https?://", value):
        return sanitize_url(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:3002")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    statuses = {}

    status, health = get_json(args.url, "/api/health")
    statuses["health"] = status
    write_json(output / "grafana-health.json", health)

    status, search = get_json(args.url, "/api/search?limit=5000")
    statuses["search"] = status
    folders = [entry for entry in search if entry.get("type") == "dash-folder"]
    dashboards = [entry for entry in search if entry.get("type") == "dash-db"]
    write_json(output / "folders.json", folders)
    write_json(output / "dashboard-search-index.json", dashboards)

    inventory_rows = ["uid\ttitle\tfolder_uid\tfolder_title\tfile"]
    seen = set()
    for entry in sorted(dashboards, key=lambda row: (row.get("folderTitle", ""), row.get("title", ""), row.get("uid", ""))):
        uid = entry["uid"]
        if uid in seen:
            raise RuntimeError(f"duplicate live dashboard UID: {uid}")
        seen.add(uid)
        status, payload = get_json(args.url, f"/api/dashboards/uid/{urllib.parse.quote(uid, safe='')}")
        statuses[f"dashboard:{uid}"] = status
        dashboard = payload["dashboard"]
        dashboard["id"] = None
        folder_title = entry.get("folderTitle") or "General"
        rel = Path("dashboards") / slug(folder_title) / f"{slug(uid)}.json"
        write_json(output / rel, dashboard)
        inventory_rows.append("\t".join([
            uid,
            str(entry.get("title", "")).replace("\t", " ").replace("\n", " "),
            str(entry.get("folderUid", "")),
            folder_title.replace("\t", " ").replace("\n", " "),
            rel.as_posix(),
        ]))
    (output / "dashboard-inventory.tsv").write_text("\n".join(inventory_rows) + "\n")

    status, datasources = get_json(args.url, "/api/datasources")
    statuses["datasources"] = status
    portable_datasources = []
    for source in datasources:
        clean = sanitize(source)
        for key in ("id", "orgId", "version"):
            clean.pop(key, None)
        clean.pop("password", None)
        clean.pop("user", None)
        portable_datasources.append(clean)
    write_json(output / "datasources.sanitized.json", portable_datasources)

    endpoints = {
        "contact-points.sanitized.json": "/api/v1/provisioning/contact-points",
        "alert-rules.json": "/api/v1/provisioning/alert-rules",
        "notification-policies.sanitized.json": "/api/v1/provisioning/policies",
        "mute-timings.json": "/api/v1/provisioning/mute-timings",
    }
    for filename, endpoint in endpoints.items():
        status, payload = get_json(args.url, endpoint)
        statuses[filename] = status
        if "contact-points" in filename:
            cleaned = []
            for item in payload:
                item = dict(item)
                item["settings"] = sanitize(item.get("settings", {}), "contact_settings", redact_all_strings=True)
                cleaned.append(item)
        else:
            cleaned = sanitize(payload)
        write_json(output / filename, cleaned)

    write_json(output / "api-status.json", statuses)
    summary = {
        "dashboard_count": len(dashboards),
        "dashboard_uid_unique_count": len(seen),
        "folder_count": len(folders),
        "datasource_count": len(datasources),
        "contact_point_count": len(json.loads((output / "contact-points.sanitized.json").read_text())),
        "alert_rule_count": len(json.loads((output / "alert-rules.json").read_text())),
        "mute_timing_count": len(json.loads((output / "mute-timings.json").read_text())),
    }
    write_json(output / "export-summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
