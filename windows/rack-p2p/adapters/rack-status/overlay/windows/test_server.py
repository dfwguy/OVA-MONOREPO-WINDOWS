# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Real Windows TLS and WebSocket regression for the native server gateway."""
import http.client
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import suppress
from pathlib import Path

from cheroot.ssl.builtin import BuiltinSSLAdapter
from cheroot.wsgi import Server
from simple_websocket import Client, ConnectionClosed
from simple_websocket import Server as WebSocket

from windows.server import WebSocketConnection, WebSocketGateway

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _application(environ, start_response):
    if environ["PATH_INFO"] == "/ws":
        if environ.get("HTTP_AUTHORIZATION") != "Bearer adapter-test":
            start_response("403 Forbidden", [("Content-Length", "0")])
            return []
        if environ.get("HTTP_ORIGIN") != "https://localhost":
            start_response("403 Forbidden", [("Content-Length", "0")])
            return []
        websocket = WebSocket(environ)
        environ["nvis.websocket_handled"] = True
        try:
            message = websocket.receive(timeout=3)
            websocket.send(message)
        finally:
            with suppress(ConnectionClosed):
                websocket.close()
        return []
    start_response("200 OK", [("Content-Length", "2")])
    return [b"ok"]


class NativeServerTest(unittest.TestCase):
    """Exercise the real socket, certificate verification and upgrade lifetime."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="rack-windows-tls-")
        destination = Path(cls.directory.name)
        subprocess.run(
            [sys.executable, str(ROOT / "bin" / "gen-tls-cert.py"),
             "--out-dir", str(destination)],
            check=True, capture_output=True,
        )
        certificate = destination / "server.crt"
        private_key = destination / "server.key"
        from tls_server import build_ssl_context

        cls.server = Server(("127.0.0.1", 0), _application, numthreads=4)
        cls.server.ConnectionClass = WebSocketConnection
        cls.server.gateway = WebSocketGateway
        adapter = BuiltinSSLAdapter(str(certificate), str(private_key))
        adapter.context = build_ssl_context(str(certificate), str(private_key))
        cls.server.ssl_adapter = adapter
        cls.server.prepare()
        cls.port = cls.server.socket.getsockname()[1]
        cls.thread = threading.Thread(target=cls.server.serve, daemon=True)
        cls.thread.start()
        cls.context = ssl.create_default_context(cafile=str(certificate))

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.thread.join(timeout=10)
        cls.directory.cleanup()

    def test_https_and_authenticated_websocket(self):
        for _ in range(3):
            websocket = Client.connect(
                f"wss://localhost:{self.port}/ws",
                headers={"Authorization": "Bearer adapter-test",
                         "Origin": "https://localhost"},
                ssl_context=self.context,
            )
            websocket.send("native-tls-websocket")
            self.assertEqual(websocket.receive(timeout=3), "native-tls-websocket")
            websocket.close()
            connection = http.client.HTTPSConnection(
                "127.0.0.1", self.port, context=self.context, timeout=3,
            )
            connection.request("GET", "/health")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"ok")
            connection.close()
        # Socket cleanup is asynchronous. An immediate 200 can arrive before a
        # worker's fatal duplicate shutdown reaches Cheroot's serving loop.
        self.assertIsNone(self.server.interrupt)
        self.assertTrue(self.thread.is_alive())

    def test_service_survives_delayed_websocket_cleanup(self):
        self.test_https_and_authenticated_websocket()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            self.assertIsNone(self.server.interrupt)
            self.assertTrue(self.thread.is_alive())
            connection = http.client.HTTPSConnection(
                "127.0.0.1", self.port, context=self.context, timeout=3,
            )
            connection.request("GET", "/health")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"ok")
            connection.close()
            time.sleep(1)

    def test_refused_upgrade_remains_http(self):
        for headers in ({}, {"Authorization": "Bearer adapter-test",
                             "Origin": "https://untrusted.invalid"}):
            connection = http.client.HTTPSConnection(
                "127.0.0.1", self.port, context=self.context, timeout=3,
            )
            connection.request("GET", "/ws", headers={
                "Upgrade": "websocket", "Connection": "Upgrade", **headers,
            })
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            self.assertEqual(response.read(), b"")
            connection.close()


if __name__ == "__main__":
    unittest.main()
