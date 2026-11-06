# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The deployment tracker: ``GET /api/deployment-tracker`` and ``GET /api/deployment-tracker/site.html``.

The dataset is ``deployment_tracker.build_dataset``; this file only gathers its inputs -- the
same canonical snapshot ``/api/status`` serves, with the same hierarchy and SU grouping merged
in, and the node stages ``/api/node-stages`` computes from it -- and hands the result to one of
the two renderers: JSON for the SPA, the self-contained static page for publishing.
"""
from __future__ import annotations

import logging

import deployment_tracker
from audit.actions import action
from flask import Blueprint, Response, jsonify, request
from paths import _resolve_log_dir

from api._tracker_inputs import NotReady, tracker_dataset

_logger = logging.getLogger(__name__)

bp = Blueprint("deployment_tracker", __name__)


def _dataset() -> dict:
    log_dir = _resolve_log_dir(request.args.get("log_dir"))
    wait = (request.args.get("wait") or "").strip().lower() in ("1", "true", "yes")
    return tracker_dataset(log_dir, wait=wait)


def _not_ready(e: Exception):
    resp = jsonify({"ok": False, "error": str(e)})
    resp.headers["Retry-After"] = "30"
    return resp, 503


@bp.route("", methods=["GET"])
@action(get="report.tracker:read")
def api_deployment_tracker():
    """The tracker dataset. ``wait=1`` waits for a first snapshot and the bring-up verdicts."""
    try:
        return jsonify({"ok": True, **_dataset()})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except NotReady as e:
        return _not_ready(e)
    except Exception as e:
        _logger.warning("deployment tracker failed", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/site.html", methods=["GET"])
@action(get="report.tracker:read")
def api_deployment_tracker_site():
    """The static tracker page with the current dataset embedded, as one HTML file to publish."""
    try:
        body = deployment_tracker.render_site(_dataset())
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except NotReady as e:
        return _not_ready(e)
    except deployment_tracker.SiteBundleMissing as e:
        return jsonify({"ok": False, "error": str(e)}), 503
    except Exception as e:
        _logger.warning("deployment tracker site failed", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500
    return Response(
        body,
        mimetype="text/html",
        headers={"Content-Disposition": 'attachment; filename="deployment-tracker.html"'},
    )
