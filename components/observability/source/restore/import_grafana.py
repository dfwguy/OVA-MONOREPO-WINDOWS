#!/usr/bin/env python3
"""Restore sanitized Grafana folders, data sources, and dashboards."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def request(base: str, token: str, method: str, endpoint: str, payload=None, allow_not_found: bool = False):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base.rstrip("/") + endpoint, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        if allow_not_found and error.code == 404:
            return error.code, None
        if method == "POST" and error.code == 409:
            return error.code, {"message": body}
        raise RuntimeError(f"Grafana {method} {endpoint} failed: HTTP {error.code}: {body[:400]}") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:3000")
    parser.add_argument("--export-root", type=Path, default=Path(__file__).resolve().parents[1] / "grafana-live")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-datasources", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("GRAFANA_API_TOKEN", "")

    folders = json.loads((args.export_root / "folders.json").read_text())
    inventory = (args.export_root / "dashboard-inventory.tsv").read_text().splitlines()[1:]
    datasources = json.loads((args.export_root / "datasources.sanitized.json").read_text())

    print(json.dumps({"dashboards": len(inventory), "datasources": len(datasources), "folders": len(folders)}, sort_keys=True))
    if args.dry_run:
        return 0

    for folder in folders:
        payload = {"uid": folder["uid"], "title": folder["title"]}
        status, _ = request(args.url, token, "GET", f"/api/folders/{folder['uid']}", allow_not_found=True)
        if status == 404:
            status, _ = request(args.url, token, "POST", "/api/folders", payload)
        else:
            status, _ = request(args.url, token, "PUT", f"/api/folders/{folder['uid']}", {"title": folder["title"], "overwrite": True})
        print(f"folder {folder['uid']}: HTTP {status}")

    if not args.skip_datasources:
        for datasource in datasources:
            portable = {key: datasource[key] for key in (
                "name", "type", "uid", "access", "url", "basicAuth", "isDefault", "jsonData"
            ) if key in datasource}
            status, _ = request(args.url, token, "GET", f"/api/datasources/uid/{datasource['uid']}", allow_not_found=True)
            if status == 404:
                status, _ = request(args.url, token, "POST", "/api/datasources", portable)
            else:
                status, _ = request(args.url, token, "PUT", f"/api/datasources/uid/{datasource['uid']}", portable)
            print(f"datasource {datasource['uid']}: HTTP {status}")

    for row in inventory:
        uid, title, folder_uid, _, relative = row.split("\t", 4)
        dashboard = json.loads((args.export_root / relative).read_text())
        payload = {"dashboard": dashboard, "folderUid": folder_uid, "overwrite": True, "message": "portable live snapshot restore"}
        status, _ = request(args.url, token, "POST", "/api/dashboards/db", payload)
        print(f"dashboard {uid} {title}: HTTP {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
