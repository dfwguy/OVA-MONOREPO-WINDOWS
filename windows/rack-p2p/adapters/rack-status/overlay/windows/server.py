# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Native Windows HTTPS serving, using the existing CLI, startup gate and TLS policy.

Cheroot keeps the application's native threaded locking and subprocess semantics.
The gateway exposes its real TLS socket to the existing simple-websocket middleware;
only an explicitly handled upgrade may suppress ordinary HTTP finalization.
"""

from __future__ import annotations

import logging
import os
import threading

from cheroot.server import HTTPConnection
from cheroot.ssl.builtin import BuiltinSSLAdapter
from cheroot.wsgi import Gateway_10, Server

LOGGER = logging.getLogger(__name__)


class WebSocketConnection(HTTPConnection):
    """Keep transport shutdown with the component that owns an upgraded socket."""

    def _close_kernel_socket(self):
        # simple-websocket owns the real TLS socket after an accepted upgrade.
        # Its reader closes that socket. A second SSLSocket.shutdown on Windows
        # raises WSAENOTSOCK (10038), which Cheroot treats as a fatal server error.
        # HTTPConnection.close still closes its reader and socket references;
        # only the redundant transport shutdown is omitted for an accepted WS.
        if getattr(self, "nvis_websocket_owned", False):
            return
        super()._close_kernel_socket()


class WebSocketGateway(Gateway_10):
    """Expose Cheroot's socket without changing app authentication or routing."""

    def get_environ(self):
        environ = super().get_environ()
        environ["werkzeug.socket"] = self.req.conn.socket
        environ["nvis.raw_socket_server"] = True
        return environ

    def respond(self):
        # Match Cheroot's Gateway.respond while allowing the authenticated terminal
        # middleware to own the 101 bytes and socket lifetime. Never infer ownership
        # from a caller-supplied Upgrade header: refused upgrades are ordinary HTTP.
        response = self.req.server.wsgi_app(self.env, self.start_response)
        try:
            if self.env.get("nvis.websocket_handled"):
                self.req.conn.nvis_websocket_owned = True
                self.req.sent_headers = True
                self.req.close_connection = True
                return
            for chunk in filter(None, response):
                if not isinstance(chunk, bytes):
                    raise TypeError("WSGI applications must yield bytes")
                self.write(chunk)
        finally:
            self.req.ensure_headers_sent()
            if hasattr(response, "close"):
                response.close()


def _watch_stop_event(server: Server, event_name: str) -> None:
    """Let the service wrapper request graceful shutdown without killing Python."""
    import win32event

    event = win32event.CreateEvent(None, True, False, event_name)
    try:
        win32event.WaitForSingleObject(event, win32event.INFINITE)
        LOGGER.info("Windows service requested graceful shutdown")
        server.stop()
    finally:
        event.Close()


def serve(*, host: str, port: int, bootstrap: bool = True) -> int:
    """Serve one process with native worker threads and the shared security gates."""
    import config_launch
    import startup_gate
    from tls_server import build_ssl_context, describe

    config_launch.load()
    startup_gate.prepare(bootstrap=bootstrap)
    cert, key = startup_gate.ensure_tls()
    context = build_ssl_context(cert, key)
    from app import app

    workers = int(os.environ.get("GUNICORN_THREADS") or "24")
    if not 4 <= workers <= 128:
        raise ValueError("Windows HTTP worker thread count must be between 4 and 128")
    server = Server((host, port), app, numthreads=workers, server_name="localhost")
    server.ConnectionClass = WebSocketConnection
    server.gateway = WebSocketGateway
    adapter = BuiltinSSLAdapter(cert, key)
    adapter.context = context
    server.ssl_adapter = adapter
    server.timeout = 600
    server.shutdown_timeout = 30
    stop_event = os.environ.get("NVIS_WINDOWS_STOP_EVENT", "").strip()
    if stop_event:
        threading.Thread(
            target=_watch_stop_event,
            args=(server, stop_event),
            name="rack-status-service-stop",
            daemon=True,
        ).start()
    LOGGER.warning("Native Windows HTTPS on %s:%s; %s; one process, %s threads", host, port, describe(context), workers)
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()
    finally:
        server.stop()
    return 0
