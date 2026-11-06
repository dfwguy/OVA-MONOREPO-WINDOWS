# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""``/api/cluster-paths``: where the active cluster keeps its things, and whether they are there.

The paths are ``cluster_paths``'s: one root on the cluster record and the layout derived from it.
This module serves them two ways -- the layout itself, so the cluster editor can show "= <root>/..."
beside each field without retyping the suffixes in TypeScript, and the active cluster's resolved
set, checked on the execution host for whether each folder exists and is writable. That is the one
screen the cluster-home design asked for: "where does this cluster keep its things?" has one answer.
"""
from __future__ import annotations

import logging
import shlex

import cluster_paths
import host_exec
from audit.actions import action
from config_env import _eget
from flask import Blueprint, jsonify, request

_logger = logging.getLogger(__name__)

bp = Blueprint("cluster_paths", __name__)


@bp.route("/layout", methods=["GET"])
@action(get="catalog:read")
def api_cluster_path_layout():
    """The layout every cluster derives from its root: key, label, suffix, override field, purpose."""
    return jsonify({
        "ok": True,
        "layout": [
            {"key": s.key, "label": s.label, "suffix": s.suffix, "field": ".".join(s.override),
             "env": list(s.env), "purpose": s.purpose}
            for s in cluster_paths.LAYOUT
        ],
    })


def _check(paths: list[str]) -> dict[str, dict[str, bool]]:
    """``{path: {exists, writable}}`` for each folder, in one round trip to the execution host."""
    if not paths:
        return {}
    script = "; ".join(
        f"p={shlex.quote(p)}; e=0; w=0; [ -d \"$p\" ] && e=1; [ -w \"$p\" ] && w=1; echo \"$e$w $p\""
        for p in paths
    )
    out: dict[str, dict[str, bool]] = {}
    proc = host_exec.run_on_host(["sh", "-c", script], timeout=30)
    for line in (proc.stdout or "").splitlines():
        flags, _, path = line.partition(" ")
        if len(flags) == 2 and path:
            out[path] = {"exists": flags[0] == "1", "writable": flags[1] == "1"}
    return out


@bp.route("", methods=["GET"])
@action(get="catalog:read")
def api_cluster_paths():
    """The active cluster's root, every path derived from it, and the image exceptions.

    ``check=1`` also asks the execution host whether each folder exists and is writable. A path
    the record leaves unset is reported with the value the environment gives it, as
    ``environment``: the thing to move onto the record.
    """
    from catalog import context as catalog_context
    from catalog import models

    _project, cluster, _platform = catalog_context.resolve()
    if cluster is None:
        return jsonify({"ok": False, "error": "no active cluster"}), 409
    shared, node = models.node_image_dirs(cluster, catalog_context.p2p_settings_for(cluster))
    env_value = {name: (_eget(name) or "").strip() for spec in cluster_paths.LAYOUT for name in spec.env}
    data = cluster_paths.summary(cluster, shared, node, env_value)
    data["cluster"] = {"id": cluster.id, "name": cluster.name}
    if (request.args.get("check") or "").strip() in ("1", "true", "yes"):
        try:
            found = _check([row["path"] for row in data["paths"] if row["path"]])
        except Exception as e:  # noqa: BLE001 - say why the check could not run; the paths still stand
            data["check_error"] = str(e)
        else:
            for row in data["paths"]:
                if row["path"]:
                    row.update(found.get(row["path"], {"exists": False, "writable": False}))
            data["checked_on"] = "execution host"
    return jsonify({"ok": True, **data})
