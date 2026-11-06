# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Verify certificate, real SPA assets and authentication on the native service."""
import argparse
import http.client
import json
import ssl
import time
from html.parser import HTMLParser


class Assets(HTMLParser):
    """Collect the static resources referenced by the actual served HTML."""

    def __init__(self):
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "link"):
            for name, value in attrs:
                if name in ("src", "href") and value and value.startswith("/") and not value.startswith("//"):
                    self.paths.add(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    context = ssl.create_default_context(cafile=args.certificate)

    def get(path):
        connection = http.client.HTTPSConnection(args.host, args.port, context=context, timeout=5)
        try:
            connection.request("GET", path, headers={"Accept-Encoding": "br"})
            response = connection.getresponse()
            version = connection.sock.version() if connection.sock else "verified"
            return response.status, dict(response.getheaders()), response.read(), version
        finally:
            connection.close()

    deadline = time.monotonic() + args.timeout
    while True:
        try:
            status, headers, body, version = get("/login")
            if status != 200:
                raise RuntimeError("Login returned HTTP " + str(status))
            break
        except (OSError, RuntimeError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)
    encoding = headers.get("Content-Encoding", "")
    if encoding == "br":
        import brotli

        body = brotli.decompress(body)
    elif encoding:
        raise RuntimeError("Unexpected login encoding " + encoding)
    assets = Assets()
    assets.feed(body.decode())
    if not any(path.endswith(".js") for path in assets.paths):
        raise RuntimeError("Served login page references no SPA JavaScript bundle")
    for path in sorted(assets.paths):
        asset_status, asset_headers, _, _ = get(path)
        if asset_status != 200:
            raise RuntimeError("Frontend asset unavailable: " + path)
        if not asset_headers.get("Content-Length"):
            raise RuntimeError("Missing fixed asset Content-Length: " + path)
    unauthenticated_status, _, _, _ = get("/api/status")
    if unauthenticated_status != 401:
        raise RuntimeError("Unauthenticated API must return 401")
    print(json.dumps({"https": "verified", "tls": version, "login_status": status,
                      "assets_checked": len(assets.paths), "unauthenticated_api": unauthenticated_status}))


if __name__ == "__main__":
    main()
