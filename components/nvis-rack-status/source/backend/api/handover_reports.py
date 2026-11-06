# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""``/api/handover-reports``: the multi-rack runs a rack handover is signed off on, and its report.

The dataset is :mod:`handover_report`; this file only routes it. Three reads: the run table, one run
in full, and the report over a chosen set of runs -- as JSON, or as the PDF on the NVIDIA letterhead.
One write: collect a run's per-node bring-up results again.
A PDF is also kept in the report store, so the Reports page lists every handover document issued.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import handover_report
import handover_report_pdf
from audit.actions import action
from flask import Blueprint, Response, jsonify, request

_logger = logging.getLogger(__name__)

bp = Blueprint("handover_reports", __name__)

#: A report is a document about a few runs (an SU is handed over on a handful), not a dump.
MAX_REPORT_RUNS = 20

_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _ids() -> list[str] | None:
    raw = (request.args.get("ids") or "").strip()
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    if not ids or len(ids) > MAX_REPORT_RUNS or not all(_ID.match(x) for x in ids):
        return None
    return list(dict.fromkeys(ids))


@bp.route("/runs", methods=["GET"])
@action(get="report.handover:list")
def api_handover_runs():
    """Multi-rack runs, newest first, with what each measured. ``?rack=``, ``?su=``, ``?limit=``."""
    try:
        limit = max(1, min(int(request.args.get("limit", "500")), 500))
    except (TypeError, ValueError):
        limit = 500
    try:
        body = handover_report.list_runs(
            rack=(request.args.get("rack") or "").strip() or None,
            scalable_unit=(request.args.get("su") or "").strip() or None,
            limit=limit,
        )
    except Exception as e:
        _logger.exception("handover run list failed")
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, **body})


@bp.route("/runs/<activity_id>", methods=["GET"])
@action(get="report.handover:read")
def api_handover_run(activity_id: str):
    """One multi-rack run in full: results, curves, settings and command."""
    if not _ID.match(activity_id or ""):
        return jsonify({"ok": False, "error": "invalid activity id"}), 400
    try:
        detail = handover_report.run_detail(activity_id)
    except Exception as e:
        _logger.exception("handover run detail failed for %s", activity_id)
        return jsonify({"ok": False, "error": str(e)}), 500
    if detail is None:
        return jsonify({"ok": False, "error": "no such multi-rack run"}), 404
    return jsonify({"ok": True, "run": detail})


@bp.route("/runs/<activity_id>/node-facts", methods=["POST"])
@action(post="report.handover:generate")
def api_handover_node_facts(activity_id: str):
    """Collect a run's per-node bring-up results again, in the background."""
    if not _ID.match(activity_id or ""):
        return jsonify({"ok": False, "error": "invalid activity id"}), 400
    state = handover_report.recollect_node_facts(activity_id)
    if state is None:
        return jsonify({"ok": False, "error": "no such multi-rack run"}), 404
    if state == "running":
        return jsonify({"ok": False, "error": "the run is still going; its nodes are read once it finishes"}), 409
    if state == "none":
        return jsonify({"ok": False, "error": "this run recorded no node list"}), 409
    return jsonify({"ok": True, "state": state}), 202


@bp.route("/report", methods=["GET"])
@action(get="report.handover:generate")
def api_handover_report():
    """The handover report over ``?ids=a,b`` (activity ids). ``?format=pdf`` (default) or ``json``."""
    ids = _ids()
    if ids is None:
        return jsonify({"ok": False, "error": f"ids must name 1-{MAX_REPORT_RUNS} activity ids"}), 400
    fmt = (request.args.get("format") or "pdf").strip().lower()
    if fmt not in ("pdf", "json"):
        return jsonify({"ok": False, "error": "format must be pdf or json"}), 400
    try:
        dataset = handover_report.report_dataset(ids)
    except Exception as e:
        _logger.exception("handover report dataset failed")
        return jsonify({"ok": False, "error": str(e)}), 500
    if not dataset["runs"]:
        return jsonify({"ok": False, "error": "none of those runs is a multi-rack run", "missing": ids}), 404
    if fmt == "json":
        return jsonify({"ok": True, "report": dataset})
    if not handover_report_pdf.available():
        return jsonify({"ok": False, "error": "PDF rendering unavailable (reportlab missing)"}), 503
    try:
        body = handover_report_pdf.to_pdf(dataset)
    except Exception as e:
        _logger.exception("handover report PDF failed")
        return jsonify({"ok": False, "error": str(e)}), 500
    filename = _filename(dataset)
    _save(dataset, filename, body)
    return Response(body, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _filename(dataset: dict) -> str:
    cluster = re.sub(r"[^A-Za-z0-9._-]+", "-", str((dataset.get("site") or {}).get("cluster") or "cluster")).strip("-")
    units = "-".join(dataset.get("scalable_units") or []) or "-".join(dataset.get("racks") or [])[:40]
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{cluster}_Handover_{re.sub(r'[^A-Za-z0-9._-]+', '-', units) or 'racks'}_{day}.pdf"


def _save(dataset: dict, filename: str, body: bytes) -> None:
    """Keep the issued document. A storage failure costs the archive copy, never the download."""
    try:
        import report_store

        report_store.save(
            kind="handover",
            fmt="pdf",
            filename=filename.removesuffix(".pdf"),  # the store appends the extension
            data=body,
            meta={
                "cluster": (dataset.get("site") or {}).get("cluster") or "",
                "racks": dataset.get("racks") or [],
                "runs": [r.get("activity_id") for r in dataset.get("runs") or []],
            },
        )
    except Exception:
        _logger.exception("could not keep the handover report in the report store")
