#!/usr/bin/env python3
"""Exercise two restore passes against a stateful mock Grafana API."""

from __future__ import annotations

import json
import subprocess
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    folders = set()
    datasources = set()
    events = []

    def log_message(self, *_):
        return

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def reply(self, status, payload=None):
        body = json.dumps(payload or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/folders/"):
            uid = self.path.rsplit("/", 1)[1]
            self.reply(200 if uid in self.folders else 404, {"uid": uid} if uid in self.folders else {})
        elif self.path.startswith("/api/datasources/uid/"):
            uid = self.path.rsplit("/", 1)[1]
            self.reply(200 if uid in self.datasources else 404, {"uid": uid} if uid in self.datasources else {})
        else:
            self.reply(404)

    def do_POST(self):
        payload = self.read_json()
        if self.path == "/api/folders":
            self.folders.add(payload["uid"])
            self.events.append("folder:POST")
        elif self.path == "/api/datasources":
            self.datasources.add(payload["uid"])
            self.events.append("datasource:POST")
        elif self.path == "/api/dashboards/db":
            assert payload["overwrite"] is True
            assert payload["dashboard"]["uid"]
            self.events.append("dashboard:POST-overwrite")
        else:
            raise AssertionError(self.path)
        self.reply(200)

    def do_PUT(self):
        payload = self.read_json()
        if self.path.startswith("/api/folders/"):
            self.events.append("folder:PUT")
        elif self.path.startswith("/api/datasources/uid/"):
            assert payload["uid"] == self.path.rsplit("/", 1)[1]
            self.events.append("datasource:PUT")
        else:
            raise AssertionError(self.path)
        self.reply(200)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        command = [str(root / "restore/import_grafana.py"), "--url", url]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        first = Counter(Handler.events)
        Handler.events.clear()
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        second = Counter(Handler.events)
    finally:
        server.shutdown()
        thread.join()

    assert first == Counter({"dashboard:POST-overwrite": 106, "datasource:POST": 5, "folder:POST": 3}), first
    assert second == Counter({"dashboard:POST-overwrite": 106, "datasource:PUT": 5, "folder:PUT": 3}), second
    print(json.dumps({"first_pass": dict(first), "second_pass": dict(second), "idempotent_upsert_pass": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
