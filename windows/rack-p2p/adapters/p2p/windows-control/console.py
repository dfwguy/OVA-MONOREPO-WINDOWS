"""Serve the unchanged Dragonfly console on Windows; forward only its Manager API."""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import threading
from http.cookies import CookieError, SimpleCookie
from pathlib import Path

import requests
import urllib3.exceptions
import win32event
from cheroot.ssl.builtin import BuiltinSSLAdapter
from cheroot.wsgi import Server
from flask import Flask, Response, abort, request, send_from_directory

LOG = logging.getLogger("p2p-console")
HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length", "host",
}


class ManagerTunnel:
    """Reconnect the Windows-initiated loopback forward without moving data-plane traffic."""

    def __init__(self, config: dict):
        self.config = config
        self.stop = threading.Event()
        self.process = None
        self.thread = threading.Thread(target=self._run, name="manager-ssh-forward", daemon=True)

    def _run(self):
        cfg = self.config
        argv = [cfg["ssh_executable"], "-F", cfg["ssh_config"], "-N", "-T",
                "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=20",
                "-o", "ServerAliveCountMax=3", "-L",
                f"127.0.0.1:{cfg['forward_port']}:127.0.0.1:{cfg['manager_remote_port']}",
                cfg["ssh_alias"]]
        delay = 2
        while not self.stop.is_set():
            try:
                self.process = subprocess.Popen(
                    argv, stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                LOG.info("Manager SSH forward process started")
                while not self.stop.wait(1):
                    if self.process.poll() is not None:
                        break
                if self.process.poll() is None:
                    self.process.terminate()
                    self.process.wait(timeout=10)
                else:
                    LOG.warning("Manager SSH forward disconnected; retrying")
            except (OSError, subprocess.SubprocessError):
                LOG.exception("Manager SSH forward failed")
            if self.stop.wait(delay):
                return
            delay = min(delay * 2, 30)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=15)
        if self.process and self.process.poll() is None:
            self.process.kill()


def create_app(config: dict) -> Flask:
    """Keep the source console's same-origin Manager routes and disabled legacy fleet API."""
    static_root = Path(config["static_root"])
    if not (static_root / "index.html").is_file():
        raise ValueError("Matching Dragonfly console assets are missing")
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    manager_url = config["manager_url"].rstrip("/")
    response_limit = int(config.get("response_limit_bytes", 64 * 1024 * 1024))
    if not 1 <= response_limit <= 128 * 1024 * 1024:
        raise ValueError("Manager response limit must be between 1 byte and 128 MiB")

    @app.after_request
    def headers(response):
        response.headers["X-NVIS-Service"] = "NVIS-P2P-Windows-Console"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.route("/nvis-p2p-health")
    def health():
        return proxy("healthy")

    def proxy(path: str):
        outgoing = {
            key: value for key, value in request.headers
            if key.lower() not in HOP_HEADERS | {"cookie"} and not key.lower().startswith("x-forwarded-")
        }
        # Browser cookies cross localhost ports. The Manager needs only its own jwt,
        # never the Rack Status session or another local tool's credentials.
        cookies = SimpleCookie()
        try:
            cookies.load(request.headers.get("Cookie", ""))
        except CookieError:
            cookies.clear()
        if "jwt" in cookies:
            outgoing["Cookie"] = cookies["jwt"].OutputString()
        outgoing.update({"Host": request.host, "X-Forwarded-Host": request.host,
                         "X-Forwarded-Proto": "https", "X-Real-IP": "127.0.0.1",
                         "X-Forwarded-For": "127.0.0.1", "Accept-Encoding": "identity"})
        target = manager_url + "/" + path
        if request.query_string:
            target += "?" + request.query_string.decode("ascii")
        try:
            with requests.request(
                request.method, target, headers=outgoing, data=request.get_data(),
                timeout=(5, 60), allow_redirects=False, stream=True,
            ) as upstream:
                body = upstream.raw.read(response_limit + 1, decode_content=False)
                if len(body) > response_limit:
                    return {"error": "Manager response exceeds the configured control-plane size limit"}, 502
                response = Response(body, status=upstream.status_code)
                for name, value in upstream.headers.items():
                    if name.lower() not in HOP_HEADERS | {"set-cookie"}:
                        response.headers[name] = value
                for cookie in upstream.raw.headers.getlist("Set-Cookie"):
                    if cookie.partition("=")[0].strip() != "jwt":
                        continue
                    if "secure" not in {part.strip().lower() for part in cookie.split(";")}:
                        cookie += "; Secure"
                    response.headers.add("Set-Cookie", cookie)
                response.headers["Cache-Control"] = "no-store"
                return response
        except (requests.RequestException, urllib3.exceptions.HTTPError, OSError):
            return {"error": "example Manager is unavailable; check VPN and P2P core readiness"}, 503

    @app.route("/healthy", methods=["GET", "HEAD"])
    @app.route("/api/<path:path>", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    @app.route("/oapi/<path:path>", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def manager(path=""):
        del path
        return proxy(request.path.lstrip("/"))

    @app.route("/nvis/api/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    @app.route("/nvis/api/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def legacy_disabled(path):
        del path
        return {
            "message": "The fleet controls on this page are unavailable for example. "
                       "P2P peers and image distribution are managed by the deployment workflow. "
                       "Use deployment inventory/status tooling for current progress. "
                       "Manager cluster and scheduler pages remain available.",
            "code": "FLEET_NOT_COMMISSIONED",
        }, 403

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def assets(path):
        if path in {"api", "oapi", "nvis/api"} or path.startswith(("api/", "oapi/", "nvis/api/")):
            return {"message": "Unknown API endpoint", "code": "API_NOT_FOUND"}, 404
        candidate = static_root / path
        if path and candidate.is_file():
            response = send_from_directory(static_root, path)
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if path.startswith("static/") else "no-store"
            return response
        if path.startswith(("static/", "fonts/", "favicon/")):
            abort(404)
        return send_from_directory(static_root, "index.html", max_age=0)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if config["bind"] != "127.0.0.1" or config["manager_url"] != "http://127.0.0.1:14304":
        raise ValueError("This deployment uses only explicit loopback listeners and the SSH forward")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import ssl
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(config["tls_cert"], config["tls_key"])
    server = Server((config["bind"], int(config["port"])), create_app(config), numthreads=16)
    adapter = BuiltinSSLAdapter(config["tls_cert"], config["tls_key"])
    adapter.context = context
    server.ssl_adapter = adapter
    tunnel = ManagerTunnel(config)

    def stop_requested():
        event = win32event.CreateEvent(None, True, False, "Local\\NVISP2PConsoleStop")
        try:
            win32event.WaitForSingleObject(event, win32event.INFINITE)
            server.stop()
        finally:
            event.Close()

    threading.Thread(target=stop_requested, daemon=True, name="p2p-service-stop").start()
    tunnel.thread.start()
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()
    finally:
        tunnel.close()
        server.stop()


if __name__ == "__main__":
    main()
