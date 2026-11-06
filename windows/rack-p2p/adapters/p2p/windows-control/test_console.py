"""Exercise the console's Manager boundary without contacting example."""
import importlib.util
import json
import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

SPEC = importlib.util.spec_from_file_location("p2p_windows_console", Path(__file__).with_name("console.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Manager(BaseHTTPRequestHandler):
    calls: ClassVar[list] = []

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self._reply()

    def do_POST(self):
        self._reply()

    def _reply(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.calls.append((self.command, self.path, self.headers, body))
        response = b"x" * 100 if self.path == "/api/large" else json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "jwt=test-only; Path=/")
        self.send_header("Set-Cookie", "csrf=test-only; Path=/")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


class ConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = tempfile.TemporaryDirectory()
        Path(cls.assets.name, 'index.html').write_text('<!doctype html><title>Test SPA</title>')
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Manager)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.assets.cleanup()

    def setUp(self):
        self.app = MODULE.create_app({
            "static_root": self.assets.name,
            "manager_url": f"http://127.0.0.1:{self.server.server_port}",
        })
        self.client = self.app.test_client()

    def test_static_spa_works_without_manager(self):
        for path, status in (("/", 200), ("/signin", 200), ("/static/not-a-real-asset.js", 404)):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, status)

    def test_api_auth_body_query_and_cookies_preserved(self):
        self.client.set_cookie("jwt", "manager-test-only")
        self.client.set_cookie("nvis_access", "rack-test-only")
        response = self.client.post("/api/v1/users/signin?remember=true", json={"name": "test-only"},
                                    base_url="https://localhost:4301",
                                    headers={"X-Forwarded-For": "untrusted"})
        method, path, headers, body = Manager.calls[-1]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/api/v1/users/signin?remember=true")
        self.assertEqual(json.loads(body), {"name": "test-only"})
        self.assertEqual(headers["X-Forwarded-For"], "127.0.0.1")
        self.assertEqual(headers["X-Forwarded-Proto"], "https")
        self.assertEqual(headers["Cookie"], "jwt=manager-test-only")
        cookies = response.headers.getlist("Set-Cookie")
        self.assertEqual(len(cookies), 1)
        self.assertTrue(all("Secure" in cookie for cookie in cookies))
        self.assertTrue(all("HttpOnly" not in cookie for cookie in cookies))
        self.assertEqual(response.json, {"ok": True})

    def test_legacy_actions_remain_unavailable(self):
        for method, path in (("GET", "/nvis/api/status"), ("GET", "/nvis/api/settings"),
                             ("POST", "/nvis/api/operations"), ("POST", "/nvis/api/provision")):
            response = self.client.open(path, method=method)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json["code"], "FLEET_NOT_COMMISSIONED")
            self.assertIn("deployment inventory/status tooling", response.json["message"])
            self.assertEqual(response.mimetype, "application/json")

    def test_api_roots_never_return_spa_html(self):
        for path in ("/api", "/oapi"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json["code"], "API_NOT_FOUND")

    def test_origin_health_tracks_manager(self):
        self.assertEqual(self.client.get("/nvis-p2p-health").status_code, 200)
        broken = MODULE.create_app({"static_root": self.assets.name,
                                   "manager_url": "http://127.0.0.1:1"}).test_client()
        self.assertEqual(broken.get("/healthy").status_code, 503)

    def test_metadata_response_is_bounded(self):
        small = MODULE.create_app({"static_root": self.assets.name,
                                  "manager_url": f"http://127.0.0.1:{self.server.server_port}",
                                  "response_limit_bytes": 32}).test_client()
        self.assertEqual(small.get("/api/large").status_code, 502)


if __name__ == "__main__":
    unittest.main()
