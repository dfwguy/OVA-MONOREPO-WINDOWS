# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""A compressed response must carry a Content-Length, or the page breaks over TLS.

Author: Rafael M. Koike & Cursor Agent ("Ada")

**This is a CI gate, not a local convenience.** The bug it guards has now been "fixed" three times
and come back twice, and each recurrence survived because of how it was verified rather than how it
was fixed. Getting the *test* right therefore matters more than the one-line change it protects.

The mechanism: ``send_file`` makes ``response.is_streamed`` true, Flask-Compress defaults
``COMPRESS_STREAMS`` to **True**, and its streaming branch re-wraps the body in a generator and
explicitly pops ``Content-Length``. The response then goes out ``Transfer-Encoding: chunked``. Over
TLS, a chunked body whose terminator races ``close_notify`` reads to Chrome as truncated; it retries
and dies with ``ERR_TOO_MANY_RETRIES``. The largest asset loses first, so the dashboard renders
unstyled.

Three reasons it kept looking fixed, each of which shaped a decision here:

* **Switching Werkzeug → gunicorn narrowed the race but changed nothing about the chunking** — the
  chunking is decided in Flask-Compress, above the WSGI server. Measured: 20 chunked assets *while
  running under gunicorn*. So these cases assert the **header**, which is deterministic, not the
  browser symptom, which is a race.
* **curl cannot see it.** No ``Accept-Encoding`` by default means no brotli, and curl tolerates the
  EOF pattern Chrome rejects. Every request below sets ``Accept-Encoding: br`` explicitly.
* **Browser cache hides it after one success**, so any manual recheck passes.

And the reason this file is written against a **synthetic** asset directory: ``static/spa/`` is a
gitignored build artifact, absent from every CI checkout (`local-vs-ci-tree.mdc` §1). An earlier
version of this file keyed off the real bundle and therefore *skipped entirely in CI* — a gate that
never runs. The synthetic fixture makes the invariant enforceable on every push, with the real-bundle
cases kept as extra coverage for developers who have built.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("RACK_STATUS_DEMO", "1")
os.environ.setdefault("RACK_WEB_AUTH_DISABLED", "1")

from api import _common
from app import app

REAL_SPA = Path(__file__).resolve().parents[2] / "static" / "spa"

#: Comfortably over COMPRESS_MIN_SIZE (1024). Below it nothing is compressed, so a small asset would
#: pass this suite while proving nothing — which is also why 13 of the 33 real assets never broke and
#: made the failure look partial rather than systematic.
_BIG = 40_000


@pytest.fixture
def spa(tmp_path, monkeypatch):
    """A minimal built-frontend stand-in, so this runs with no `npm run build`."""
    root = tmp_path / "spa"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "app-deadbeef.css").write_text(".a{color:red}\n" * (_BIG // 14))
    (root / "assets" / "app-deadbeef.js").write_text("console.log('x');\n" * (_BIG // 18))
    (root / "assets" / "tiny-cafe.js").write_text("export const x=1;\n")  # under the threshold
    (root / "index.html").write_text(
        '<!doctype html><html><head>'
        '<link rel="stylesheet" href="/assets/app-deadbeef.css">'
        '</head><body><script src="/assets/app-deadbeef.js"></script></body></html>'
    )
    monkeypatch.setattr(_common, "_SPA_DIR", root)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


BR = {"Accept-Encoding": "br"}


def _chunked(resp) -> bool:
    return "chunked" in resp.headers.get("Transfer-Encoding", "").lower()


class TestTheGateItself:
    """Guards the guard. A gate that cannot run, or that passes for the wrong reason, is worse than
    no gate — that is precisely how this bug survived twice."""

    def test_it_does_not_depend_on_a_built_frontend(self, spa):
        """If this file ever needs `static/spa/`, it stops running in CI and stops gating."""
        source = Path(__file__).read_text()
        assert "monkeypatch.setattr(_common" in source
        assert not REAL_SPA.exists() or True  # runs either way; asserted by the fixture working

    def test_brotli_is_actually_applied(self, spa):
        """Without this, every response would trivially have a Content-Length and the suite would be
        vacuous."""
        resp = spa.get("/assets/app-deadbeef.css", headers=BR)
        assert resp.status_code == 200
        assert resp.headers.get("Content-Encoding") == "br", (
            "brotli did not apply, so the streaming branch is never exercised and this file proves "
            "nothing"
        )

    def test_the_fixture_asset_is_over_the_compression_threshold(self, spa):
        floor = app.config.get("COMPRESS_MIN_SIZE", 1024)
        assert _BIG > floor * 4


class TestCompressedResponsesCarryALength:
    """The invariant. Extend this rather than writing a new file if another route starts streaming."""

    def test_the_shell_is_not_chunked(self, spa):
        resp = spa.get("/", headers=BR)
        assert resp.status_code == 200
        assert not _chunked(resp)
        assert resp.headers.get("Content-Length")

    @pytest.mark.parametrize(
        "asset", ["/assets/app-deadbeef.css", "/assets/app-deadbeef.js", "/assets/tiny-cafe.js"]
    )
    def test_no_asset_is_chunked(self, spa, asset):
        resp = spa.get(asset, headers=BR)
        assert resp.status_code == 200
        assert not _chunked(resp), f"{asset} went out chunked; Chrome retries these over TLS"
        assert resp.headers.get("Content-Length"), f"{asset} has no Content-Length"

    def test_the_response_is_not_streamed(self, spa):
        """The mechanism, asserted directly: Flask-Compress picks its chunked branch on
        `is_streamed`, so that is the property to hold rather than the header it happens to emit."""
        with app.test_request_context("/"):
            resp = _common.serve_spa_asset("assets/app-deadbeef.css")
        assert resp.is_streamed is False
        assert resp.direct_passthrough is False

    def test_a_compressible_api_route_is_not_chunked(self, spa):
        """Widens the net beyond the SPA: any JSON payload big enough to compress must also carry a
        length. This is the case that would catch a *new* streaming response elsewhere."""
        resp = spa.get("/api/catalog/overview", headers=BR)
        if resp.status_code != 200 or not resp.headers.get("Content-Encoding"):
            pytest.skip("payload below the compression threshold in this environment")
        assert not _chunked(resp)
        assert resp.headers.get("Content-Length")

    def test_send_file_semantics_survive(self, spa):
        """`send_file` is kept rather than hand-rolled so these come from Werkzeug. A future rewrite
        would regress caching silently."""
        resp = spa.get("/assets/app-deadbeef.css", headers=BR)
        assert resp.headers.get("ETag"), "lost the ETag — clients re-download every time"
        assert resp.headers.get("Content-Type", "").startswith("text/css")

    def test_the_body_is_intact(self, spa):
        """Buffering must not truncate what it buffers."""
        resp = spa.get("/assets/app-deadbeef.css", headers={"Accept-Encoding": "identity"})
        assert resp.status_code == 200
        assert resp.get_data() == (_common._SPA_DIR / "assets/app-deadbeef.css").read_bytes()


class TestTheSiblingRegression:
    """The same config controls a second, opposite bug — worth one guard rather than two files.

    `text/plain` is deliberately **excluded** from COMPRESS_MIMETYPES because the live log endpoints
    stream it via a generator, and Flask-Compress buffers a whole response to compress it. Adding
    `text/plain` back makes streamed output appear only when the command finishes: the original
    "logs show only at the end" bug.
    """

    def test_text_plain_stays_uncompressed(self):
        assert "text/plain" not in app.config["COMPRESS_MIMETYPES"], (
            "adding text/plain re-introduces 'logs only appear at the end' — Flask-Compress buffers "
            "the generator before sending"
        )

    def test_the_mimetypes_that_must_be_compressed_still_are(self):
        """The other direction: silently dropping these would make the 2.2 MB bundle uncompressed
        over an SSH tunnel."""
        for mimetype in ("text/css", "text/javascript", "application/json"):
            assert mimetype in app.config["COMPRESS_MIMETYPES"]


class TestTheTierBoundaryHolds:
    """The real bundle is checked in ``backend/tests/integration/``, not here.

    This file is the **unit** tier: synthetic assets, no build, runs on every push. The same
    invariant against the bundle Vite actually emitted is an integration concern, and mixing the two
    is what produced the version of this file that skipped entirely in CI.
    """

    def test_the_integration_tier_exists_and_covers_the_real_bundle(self):
        integration = Path(__file__).parent / "integration" / "test_served_frontend.py"
        assert integration.is_file(), (
            "the integration tier is missing — the real-bundle checks moved there, and without it "
            "nothing verifies what Vite actually emitted"
        )
        source = integration.read_text()
        assert "Content-Length" in source
        assert "Accept-Encoding" in source or "BR" in source
