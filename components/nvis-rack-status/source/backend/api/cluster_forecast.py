# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""``/api/cluster-forecast``: when validation finishes, and the sampler that makes it answerable.

The dataset is ``cluster_forecast.build_dataset`` over the deployment tracker dataset and the
progress samples in ``results_history``; this file gathers those inputs and hands the result to
one of two renderers -- JSON for the SPA, or the self-contained static page for publishing.

**The sampler lives here because the forecast is the only thing that needs it.** Rack Status
kept no history of progress -- the snapshot is the present only -- so without samples there is
no pace to project. Once an hour, on a background thread, it records each scalable unit's counts
(``cluster_forecast.record_sample``). It is started by the first request this process serves
(``before_app_request``), never at import: tools that import the app to inspect it must not
start threads that reach the cluster.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import cluster_forecast
import host_exec
import rack_status_engine
import results_history
from audit.actions import action
from config_env import _eget, _eget_int
from flask import Blueprint, Response, jsonify, request
from paths import _resolve_log_dir

from api._tracker_inputs import NotReady, tracker_dataset

_logger = logging.getLogger(__name__)

bp = Blueprint("cluster_forecast", __name__)

#: Seconds between samples. An hour resolves a repair batch without filling the table.
DEFAULT_SAMPLE_INTERVAL_SEC = 3600

#: How often the sampler wakes to ask whether a sample is due. Short, so a sample skipped while
#: the bring-up verdicts were still loading is taken minutes later rather than an hour later.
_CHECK_SEC = 300

#: Delay before the first check, so the startup bootstraps have resolved the active cluster.
_FIRST_CHECK_SEC = 120

#: How much history the page draws. The pace itself only looks back ``window_days``.
HISTORY_DAYS = 90

_sampler: threading.Thread | None = None
_sampler_lock = threading.Lock()


def sample_interval_sec() -> int:
    """``RACK_FORECAST_SAMPLE_INTERVAL_SEC``; 0 stops sampling. Floors at five minutes."""
    value = _eget_int("RACK_FORECAST_SAMPLE_INTERVAL_SEC", DEFAULT_SAMPLE_INTERVAL_SEC)
    return 0 if value <= 0 else max(300, value)


def window_days() -> int:
    """``RACK_FORECAST_WINDOW_DAYS``: how far back the pace looks for its baseline."""
    return max(2, _eget_int("RACK_FORECAST_WINDOW_DAYS", cluster_forecast.DEFAULT_WINDOW_DAYS))


def _demo() -> bool:
    return (_eget("RACK_STATUS_DEMO", "") or "").strip().lower() in ("1", "true", "yes")


def _stale_after_sec() -> int:
    """A snapshot older than this is not sampled: three background refreshes, at least 15 min."""
    return max(900, 3 * rack_status_engine.rack_status_background_interval_sec())


def sample_once() -> str:
    """Take a sample if one is due, and say in a sentence what happened.

    Every way of *not* sampling has its own sentence, because the failure this guards against is
    silence: a sampler that skips every hour for a reason nobody sees leaves the page reading
    "not enough history" forever. The last outcome is published on the page (``last_check``).
    """
    interval = sample_interval_sec()
    if interval <= 0 or _demo():
        return "Sampling is off (RACK_FORECAST_SAMPLE_INTERVAL_SEC is 0, or this is demo mode)."
    # The cluster the snapshot belongs to -- only the active cluster's snapshot is ever refreshed,
    # so that is the only cluster there is anything true to record about.
    key = cluster_forecast.cluster_key_of(rack_status_engine.cluster_snapshot_identity())
    if not key:
        return "No cluster identity to file a sample under."
    if not cluster_forecast.sample_due(key, interval):
        return "Not due yet."
    if not host_exec.cluster_reachable():
        return "Skipped: the cluster is unreachable from Rack Status."
    try:
        tracker = tracker_dataset(_resolve_log_dir(None), wait=False)
    except NotReady:
        return "Skipped: the node inventory is still loading."
    meta = tracker.get("meta") or {}
    if meta.get("cluster_key") != key:
        return "Skipped: the active cluster changed while sampling; the next check samples the new one."
    age = meta.get("snapshot_age_sec")
    if age is None or age > _stale_after_sec():
        return (
            "Skipped: the cluster snapshot is stale"
            + (f" ({round(age / 60)} min old)" if age is not None else "")
            + ", so the counts would not be today's."
        )
    # Without the bring-up verdicts every node's Stage 2 reads as not run, and a sample taken
    # then would record a fleet-wide regression that never happened. The next check retries.
    if meta.get("stage2_loading"):
        error = str(meta.get("stage2_error") or "")
        return "Skipped: Stage 2 verdicts are still loading" + (f" ({error})" if error else "") + "."
    rows = cluster_forecast.record_sample(key, tracker)
    return f"Recorded {rows} group(s)."


#: The last check's outcome, per process. In memory on purpose: it answers "why is nothing being
#: recorded right now", which a restart answers afresh within one check.
_last_check: dict[str, str] = {}


def _check() -> None:
    try:
        outcome = sample_once()
    except Exception as exc:
        # Keep the thread alive: a sampler that died silently looks like a fleet that stopped
        # moving, which is the one thing the forecast must never claim by accident.
        _logger.exception("cluster forecast sampler failed")
        outcome = f"Failed: {exc}"
    if outcome.startswith(("Recorded", "Skipped", "Failed")):
        _logger.info("cluster forecast: %s", outcome)
    _last_check.clear()
    _last_check.update({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "outcome": outcome})


def _sampler_loop() -> None:
    time.sleep(_FIRST_CHECK_SEC)
    while True:
        _check()
        time.sleep(_CHECK_SEC)


@bp.before_app_request
def _ensure_sampler() -> None:
    global _sampler
    if _sampler is not None and _sampler.is_alive():
        return
    # Not started where it could only ever answer "disabled" (demo mode, or sampling switched
    # off). Asked again on the next request, so switching it on later starts it then.
    if _demo() or sample_interval_sec() <= 0:
        return
    with _sampler_lock:
        if _sampler is not None and _sampler.is_alive():
            return
        _sampler = threading.Thread(target=_sampler_loop, name="cluster-forecast-sampler", daemon=True)
        _sampler.start()


def _dataset() -> dict:
    log_dir = _resolve_log_dir(request.args.get("log_dir"))
    wait = (request.args.get("wait") or "").strip().lower() in ("1", "true", "yes")
    tracker = tracker_dataset(log_dir, wait=wait)
    key = str((tracker.get("meta") or {}).get("cluster_key") or "")
    now = datetime.now(timezone.utc)
    series = results_history.progress_series(key, since=now - timedelta(days=HISTORY_DAYS)) if key else []
    dataset = cluster_forecast.build_dataset(tracker, series, now=now, window_days=window_days())
    dataset["meta"]["sampling"] = {
        "interval_sec": sample_interval_sec(),
        "last_sample_at": results_history.last_progress_at(key, source="sampler") if key else None,
        "last_check": dict(_last_check) or None,
        # Rack Status observes one cluster at a time; say so where it explains a gap.
        "observes": "active cluster only",
    }
    return dataset


def _not_ready(e: Exception):
    resp = jsonify({"ok": False, "error": str(e)})
    resp.headers["Retry-After"] = "30"
    return resp, 503


@bp.route("", methods=["GET"])
@action(get="report.forecast:read")
def api_cluster_forecast():
    """The forecast dataset. ``wait=1`` waits for a first snapshot and the bring-up verdicts."""
    try:
        return jsonify({"ok": True, **_dataset()})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except NotReady as e:
        return _not_ready(e)
    except Exception as e:
        _logger.warning("cluster forecast failed", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/site.html", methods=["GET"])
@action(get="report.forecast:read")
def api_cluster_forecast_site():
    """The static forecast page with the current dataset embedded, as one HTML file to publish."""
    try:
        body = cluster_forecast.render_site(_dataset())
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except NotReady as e:
        return _not_ready(e)
    except cluster_forecast.static_page.SiteBundleMissing as e:
        return jsonify({"ok": False, "error": str(e)}), 503
    except Exception as e:
        _logger.warning("cluster forecast site failed", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500
    return Response(
        body,
        mimetype="text/html",
        headers={"Content-Disposition": 'attachment; filename="cluster-forecast.html"'},
    )
