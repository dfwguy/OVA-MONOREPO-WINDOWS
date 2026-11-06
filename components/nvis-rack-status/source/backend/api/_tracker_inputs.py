# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The deployment tracker dataset, gathered from the live snapshot -- for every report built on it.

Three callers need the same answer: the tracker's routes, the cluster forecast's routes, and the
forecast's hourly sampler, which runs with no request at all. So the gathering lives here, once,
rather than in a route: the canonical snapshot ``/api/status`` serves, with the same hierarchy and
SU grouping merged in, and the node stages ``/api/node-stages`` computes from it, handed to
``deployment_tracker.build_dataset``. Underscore-prefixed, so the API loader does not register it.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import cluster_forecast
import deployment_tracker
import node_stages
from rack_status_engine import get_cluster_snapshot

from api.dashboard import (
    _ensure_rack_status_background_thread,
    _merge_naming_into_status_payload,
    _merge_project_name_into_status_payload,
    _start_cmsh_rack_list_warm_thread,
)

_logger = logging.getLogger(__name__)


class NotReady(Exception):
    """The node inventory has not loaded yet; the caller should retry."""


def active_cluster_name() -> str:
    """The active cluster's display name, for titles; empty on a bare deployment."""
    try:
        from catalog import context as catalog_context

        _project, cluster, _platform = catalog_context.resolve()
    except Exception:  # a label; the dataset is complete without it
        _logger.warning("tracker inputs: active cluster unavailable", exc_info=True)
        return ""
    return (cluster.name or "") if cluster is not None else ""


def tracker_dataset(log_dir: Path, *, wait: bool = False) -> dict:
    """The tracker dataset for ``log_dir`` (a resolved log directory)."""
    # The same warm-up /api/status does: after a restart nothing else may have asked yet.
    _start_cmsh_rack_list_warm_thread()
    _ensure_rack_status_background_thread()
    snapshot = get_cluster_snapshot(log_dir, wait=wait)
    payload = dict(snapshot.payload or {})
    inventory = payload.get("nodes")
    if not isinstance(inventory, list):
        raise NotReady("node inventory is still loading; retry shortly")
    _merge_project_name_into_status_payload(payload)
    _merge_naming_into_status_payload(payload)
    pairs = [
        (str(n.get("id") or ""), str(n.get("rack") or ""))
        for n in inventory
        if isinstance(n, dict) and n.get("id")
    ]
    node_logs = payload.get("node_stage_logs")
    stages = node_stages.node_stages(
        pairs, node_logs if isinstance(node_logs, dict) else {}, wait_for_bringup=wait
    )
    dataset = deployment_tracker.build_dataset(payload, stages, cluster_name=active_cluster_name())
    # Which cluster this snapshot was collected for, and how old it is. Whoever keeps a history of
    # the dataset files it under this key rather than re-resolving the active cluster, which may
    # have changed since; and judges freshness from this age rather than assuming it.
    dataset["meta"]["cluster_key"] = cluster_forecast.cluster_key_of(str(snapshot.cluster_id or ""))
    dataset["meta"]["snapshot_age_sec"] = (
        round(time.time() - snapshot.last_success_at) if snapshot.last_success_at else None
    )
    return dataset
