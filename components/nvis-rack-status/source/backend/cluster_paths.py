# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Where a cluster keeps its things: one root, and every path derived from it.

A cluster declares one **root** on its record -- ``/home/cmods`` on Nscale NC -- and each of its
on-host paths is that root plus a fixed suffix (``LAYOUT``). A path may still be overridden on the
record for a site that genuinely keeps it elsewhere, and the override wins; but a correctly shaped
cluster needs exactly one value, and anyone looking for a script, a log or a toolchain knows where
it is without reading six settings.

**Why one root.** Each path used to come from its own knob with its own default, several of them
per-instance environment variables. Deployments that grew by successive installs ended up with
scripts under one user's home, logs under another's and a workspace under a third's -- working, but
impossible to find, and an environment variable is one value for the whole instance, which breaks
the moment one instance serves two clusters. The record is per cluster; the environment is not.

**How the paths reach their consumers.** ``exports`` turns the resolved paths into the variables
the backend and the shell scripts already read (``RACK_REMOTE_BASE_PATH``, ``NVIS_LOG_DIR``, ...),
and ``catalog.context.high_overlay`` publishes them. The high overlay beats the environment and the
Settings overrides, so once a cluster names a path -- by root or by override -- no environment
variable can move it. A cluster that names neither leaves the variable to the environment, which is
how a deployment not yet given a root keeps working; the paths screen labels such a value as coming
from the environment, so it is visible as the thing to move onto the record.

**Two exceptions, by nature rather than by history.** Container images are not under the root: the
node image cache is on each node's local disk, and the shared store is P2P's origin, which lives on
the app server's own disk and which no node reads (nodes take images only from the P2P destination,
``node_container_dir``). Both are P2P's settings and are reported here, beside the root, as
``exceptions`` so the one screen still shows where everything is.

Flask-free and catalog-light: it reads a ``Cluster`` it is handed and imports nothing that reads
the store, so ``high_overlay`` can call it on every resolution.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PathSpec:
    """One derived path: its suffix under the root, its override field, and how it is exported."""

    key: str
    label: str
    #: Under the root; the whole layout is ``LAYOUT``'s suffixes.
    suffix: str
    #: The record field that overrides it: ``(section, field)`` on the cluster.
    override: tuple[str, str]
    #: The variables it is published as, for the backend and the scripts.
    env: tuple[str, ...]
    purpose: str


#: The layout every cluster gets from its root. The suffixes are the product's convention, so a
#: script, a log or a toolchain is in the same place relative to the root on every cluster.
LAYOUT: tuple[PathSpec, ...] = (
    PathSpec(
        "scripts", "Rack Status scripts", "nvis-rack-status", ("connection", "remote_base_path"),
        ("RACK_REMOTE_BASE_PATH",),
        "Launchers and batch scripts, deployed by bin/deploy-scripts.sh; the layered script tree is under it.",
    ),
    PathSpec(
        "logs", "Job logs", "nvis/logs", ("connection", "log_dir"),
        ("NVIS_LOG_DIR",),
        "Where jobs write the logs Rack Status reads its verdicts from.",
    ),
    PathSpec(
        "workspace", "Workspace", "workspace", ("connection", "workspace_dir"),
        ("NVIS_WORKSPACE_DIR",),
        "Toolchains built or installed on the cluster: HPC-X, CUDA, host NCCL, nvloom, and the LLMB install (workspace/llmb).",
    ),
    PathSpec(
        "bringup", "Bring-up framework", "bringup", ("evidence", "bringup_home"),
        ("RACK_BRINGUP_HOME",),
        "The bring-up team's tree; its verdicts are each node's Stage 2.",
    ),
    PathSpec(
        "healthcheck", "Health-check markers", "bringup-data/logs", ("evidence", "healthcheck_root"),
        (),
        "Per-node health-check results the bring-up framework writes, one directory per node.",
    ),
    PathSpec(
        "bug_reports", "Reports", "bringup-data/reports", ("connection", "bug_report_dir"),
        ("RACK_BUG_REPORT_REMOTE_DIR",),
        "Bug-report archives, and under it the NVLMapper reports and parser Excel exports.",
    ),
)

BY_KEY: dict[str, PathSpec] = {spec.key: spec for spec in LAYOUT}

#: Published beside the paths, for scripts that want the root itself.
ROOT_ENV = "NVIS_CLUSTER_ROOT"

#: The folders the app may read files from, derived from the root (``paths._allowed_roots``).
ALLOWED_PREFIXES_ENV = "RACK_STATUS_ALLOWED_PREFIXES"


def _field(cluster: Any, section: str, name: str) -> str:
    holder = getattr(cluster, section, None)
    return str(getattr(holder, name, "") or "").strip().rstrip("/")


def root(cluster: Any) -> str:
    """The cluster's root, or "" when it has not been given one."""
    return _field(cluster, "connection", "root")


@dataclass(frozen=True)
class ResolvedPath:
    key: str
    label: str
    path: str
    #: ``override`` (its own record field), ``root`` (derived) or ``unset`` (neither on the record).
    source: str
    env: tuple[str, ...]
    purpose: str
    #: The record field that overrides it, as ``section.field``.
    field: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "path": self.path, "source": self.source,
            "env": list(self.env), "purpose": self.purpose, "field": self.field,
        }


def resolve(cluster: Any) -> list[ResolvedPath]:
    """Every path in ``LAYOUT`` for *cluster*: its override, else the root plus its suffix."""
    base = root(cluster)
    out = []
    for spec in LAYOUT:
        override = _field(cluster, *spec.override)
        if override:
            path, source = override, "override"
        elif base:
            path, source = f"{base}/{spec.suffix}", "root"
        else:
            path, source = "", "unset"
        out.append(ResolvedPath(spec.key, spec.label, path, source, spec.env, spec.purpose, ".".join(spec.override)))
    return out


def path(cluster: Any, key: str) -> str:
    """One path for *cluster* (``""`` when the record names neither a root nor an override)."""
    for resolved in resolve(cluster):
        if resolved.key == key:
            return resolved.path
    raise KeyError(key)


def allowed_prefixes(cluster: Any) -> list[str]:
    """The folders the app may read from: the root, and any overridden path outside it."""
    base = root(cluster)
    prefixes = [base] if base else []
    for resolved in resolve(cluster):
        if resolved.source != "override":
            continue
        inside = base and (resolved.path == base or resolved.path.startswith(base + "/"))
        if not inside and resolved.key in ("logs", "healthcheck", "bug_reports", "bringup"):
            prefixes.append(resolved.path)
    return list(dict.fromkeys(prefixes))


def exports(cluster: Any) -> dict[str, str]:
    """The variables the record decides, for ``high_overlay``. A path the record leaves unset is
    absent, so the environment still answers for a cluster not yet given a root."""
    out: dict[str, str] = {}
    for resolved in resolve(cluster):
        if resolved.path:
            for name in resolved.env:
                out[name] = resolved.path
    base = root(cluster)
    if base:
        out[ROOT_ENV] = base
    prefixes = allowed_prefixes(cluster)
    if prefixes:
        out[ALLOWED_PREFIXES_ENV] = ",".join(prefixes)
    return out


def exceptions(shared: str, node: str) -> list[dict[str, Any]]:
    """The two image paths outside the root, as the paths screen lists them beside it.

    *shared* and *node* are ``catalog.models.node_image_dirs`` for the cluster, which already
    resolves them from the cluster and its P2P settings.
    """
    return [
        {
            "key": "images_origin", "label": "Image origin (P2P)", "path": shared,
            "source": "p2p" if shared else "unset", "env": ["RACK_VALIDATION_CONTAINER_ROOT"],
            "purpose": "P2P's origin store on the app server. No node reads it: nodes take images only from the node cache.",
            "field": "connection.shared_container_dir",
        },
        {
            "key": "images_node", "label": "Node image cache (P2P destination)", "path": node,
            "source": "p2p" if node else "unset", "env": ["NVIS_NODE_CONTAINER_DIR"],
            "purpose": "Each node's local copy, where P2P delivers images and every job runs them from.",
            "field": "connection.node_container_dir",
        },
    ]


def summary(cluster: Any, shared: str, node: str, env_value: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The paths screen's dataset: the root, every derived path, and the image exceptions.

    *env_value* is how the environment would answer each variable, for paths the record leaves
    unset; a value from there is reported as ``environment`` so it can be moved onto the record.
    """
    env_value = env_value or {}
    rows = []
    for resolved in resolve(cluster):
        row = resolved.to_dict()
        if resolved.source == "unset":
            from_env = next((env_value.get(n, "") for n in resolved.env if env_value.get(n)), "")
            if from_env:
                row.update(path=from_env, source="environment")
        rows.append(row)
    return {"root": root(cluster), "paths": rows, "exceptions": exceptions(shared, node)}
