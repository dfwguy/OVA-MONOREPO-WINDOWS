# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The backend serving the real built bundle, exactly as a browser asks for it.

Author: Rafael M. Koike & Cursor Agent ("Ada")

This is the tier that would have caught the unstyled-dashboard bug on the first push instead of the
third demo. The unit tier proves the *mechanism* against a synthetic asset directory; this proves the
**product**: the bundle Vite actually emitted, served by the app, with the headers Chrome actually
sends.

Requires ``static/spa/`` — the pipeline builds it and passes it in as an artifact. Skips locally if
you have not built, which is why the unit tier keeps its own synthetic copy of the chunking check.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("RACK_STATUS_DEMO", "1")
os.environ.setdefault("RACK_WEB_AUTH_DISABLED", "1")

from app import app

SPA = Path(__file__).resolve().parents[3] / "static" / "spa"
BR = {"Accept-Encoding": "br"}

pytestmark = pytest.mark.skipif(
    not (SPA / "index.html").is_file(),
    reason=f"no built frontend at {SPA} — run `npm run build`, or let the CI integration job do it",
)


@pytest.fixture(scope="module")
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _referenced_assets() -> list[str]:
    """Every hashed asset the shell asks for. Parsed from the shell rather than listed from disk:
    the question is whether what the page *requests* resolves, not what happens to be present."""
    html = (SPA / "index.html").read_text()
    return sorted(set(re.findall(r'/assets/[^"\']+\.(?:css|js)', html)))


def _chunked(resp) -> bool:
    return "chunked" in resp.headers.get("Transfer-Encoding", "").lower()


class TestTheShellAndItsAssetsAgree:
    """Vite content-hashes every chunk, so a stale `index.html` asks for files that no longer exist.

    The symptom is a black screen with `GET /login` returning 200 — which is how the dashboard was
    down for an hour on 2026-08-12 while every health check passed. `verify-deploy.sh` catches it
    after a deploy; catching it here means it never reaches one.
    """

    def test_the_shell_is_served(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"<div id=" in resp.get_data() or b"<script" in resp.get_data()

    def test_the_shell_references_assets(self):
        assert _referenced_assets(), "index.html references no hashed assets — the build looks wrong"

    def test_every_referenced_asset_resolves(self, client):
        missing = [a for a in _referenced_assets() if client.get(a).status_code != 200]
        assert not missing, (
            f"{len(missing)} asset(s) referenced by index.html do not resolve: {missing[:5]}. "
            "index.html and assets/ are from different builds — the page renders blank."
        )

    def test_login_serves_the_same_shell(self, client):
        """The login screen *is* the React app, so both must load the same bundle or they disagree
        about which one is current — the reason ``serve_spa_asset`` is shared rather than duplicated.

        Asserted from an **unauthenticated** client, the only one for which the invariant exists: the
        suite's own client is already signed in, so ``/login`` answers 302 and there is no shell to
        compare. ``identity.testing.unauthenticated_client`` is how the auth-gate tests reach the gate
        since the token switch was removed (FR-18).
        """
        # `/` from the suite's signed-in client; unauthenticated it would redirect to /login.
        shell = client.get("/").get_data()

        from identity import testing as identity_testing

        with identity_testing.unauthenticated_client(app) as gated:
            login = gated.get("/login")
        assert login.status_code == 200, (
            "auth.login is on the bypass list, so /login must serve the shell unauthenticated"
        )
        assert login.get_data() == shell


class TestTheRealBundleIsNotSentChunked:
    """The integration half of the unit tier's synthetic check.

    Over TLS a chunked body whose terminator races `close_notify` reads to Chrome as truncated; it
    retries and fails with `ERR_TOO_MANY_RETRIES`, and the largest asset loses first — so the
    dashboard renders unstyled. Asserted on the header because the browser symptom is a race and a
    race is not something to gate on.
    """

    def test_no_referenced_asset_is_chunked(self, client):
        offenders = []
        for path in _referenced_assets():
            resp = client.get(path, headers=BR)
            if resp.status_code != 200:
                continue
            if _chunked(resp) or not resp.headers.get("Content-Length"):
                offenders.append(path)
        assert not offenders, (
            f"{len(offenders)} of {len(_referenced_assets())} assets sent without a Content-Length: "
            f"{offenders[:5]}"
        )

    def test_the_shell_is_not_chunked(self, client):
        resp = client.get("/", headers=BR)
        assert not _chunked(resp)
        assert resp.headers.get("Content-Length")

    def test_the_largest_asset_is_compressed_and_lengthed(self, client):
        """Named explicitly because it is the one that breaks first, and because a suite that only
        touched small assets would pass while the page stayed broken."""
        assets = _referenced_assets()
        largest = max(assets, key=lambda a: (SPA / a.lstrip("/")).stat().st_size)
        resp = client.get(largest, headers=BR)
        assert resp.status_code == 200
        assert resp.headers.get("Content-Encoding") == "br", (
            f"{largest} was not compressed, so this case is not exercising the streaming branch"
        )
        assert not _chunked(resp)
        assert resp.headers.get("Content-Length")

    def test_an_asset_round_trips_byte_for_byte(self, client):
        """Buffering to get a length must not corrupt or truncate the body."""
        css = [a for a in _referenced_assets() if a.endswith(".css")]
        if not css:
            pytest.skip("no CSS asset in this build")
        resp = client.get(css[0], headers={"Accept-Encoding": "identity"})
        assert resp.get_data() == (SPA / css[0].lstrip("/")).read_bytes()


class TestClientRoutesReachTheApp:
    """A deep link must return the shell, not a 404, or a bookmarked dashboard URL breaks."""

    @pytest.mark.parametrize("route", ["/compute/overview", "/analytics", "/settings"])
    def test_a_deep_link_returns_the_shell(self, client, route):
        resp = client.get(route)
        assert resp.status_code == 200
        assert resp.headers.get("Content-Type", "").startswith("text/html")

    def test_an_unknown_api_path_is_a_404_not_the_shell(self, client):
        """The catch-all must not swallow a mistyped API route — that turns a broken call into a
        confusing HTML body the frontend cannot parse."""
        resp = client.get("/api/definitely-not-a-real-endpoint")
        assert resp.status_code == 404
        assert resp.headers.get("Content-Type", "").startswith("application/json")
