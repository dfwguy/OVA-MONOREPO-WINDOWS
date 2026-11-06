# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""One root per cluster: the layout, the overrides, how it reaches every consumer, and the images."""
from __future__ import annotations

import subprocess

import cluster_paths as cp
import pytest
from catalog import context, models


def _cluster(connection=None, evidence=None, **kw):
    return models.Cluster.from_dict({
        "id": "c", "name": "C", "connection": connection or {}, "evidence": evidence or {}, **kw,
    })


ROOTED = {"root": "/home/cmods/"}


# ---------------------------------------------------------------- the layout


def test_every_path_derives_from_the_root():
    paths = {r.key: (r.path, r.source) for r in cp.resolve(_cluster(ROOTED))}
    assert paths == {
        "scripts": ("/home/cmods/nvis-rack-status", "root"),
        "logs": ("/home/cmods/nvis/logs", "root"),
        "workspace": ("/home/cmods/workspace", "root"),
        "bringup": ("/home/cmods/bringup", "root"),
        "healthcheck": ("/home/cmods/bringup-data/logs", "root"),
        "bug_reports": ("/home/cmods/bringup-data/reports", "root"),
    }


def test_an_override_wins_for_its_own_path_only():
    c = _cluster({**ROOTED, "remote_base_path": "/home/rkoike/nvis-rack-status", "bug_report_dir": "/srv/reports/"},
                 {"bringup_home": "/opt/bringup"})
    paths = {r.key: (r.path, r.source) for r in cp.resolve(c)}
    assert paths["scripts"] == ("/home/rkoike/nvis-rack-status", "override")
    assert paths["bug_reports"] == ("/srv/reports", "override")
    assert paths["bringup"] == ("/opt/bringup", "override")
    assert paths["logs"] == ("/home/cmods/nvis/logs", "root")


def test_a_cluster_with_neither_leaves_its_paths_to_the_environment():
    assert all(r.source == "unset" and r.path == "" for r in cp.resolve(_cluster()))
    assert cp.exports(_cluster()) == {}


def test_exports_publish_the_record_and_the_folders_the_app_may_read():
    c = _cluster({**ROOTED, "log_dir": "/scratch/logs"})
    out = cp.exports(c)
    assert out["RACK_REMOTE_BASE_PATH"] == "/home/cmods/nvis-rack-status"
    assert out["NVIS_LOG_DIR"] == "/scratch/logs"
    assert out["NVIS_WORKSPACE_DIR"] == "/home/cmods/workspace"
    assert out["RACK_BUG_REPORT_REMOTE_DIR"] == "/home/cmods/bringup-data/reports"
    assert out["RACK_BRINGUP_HOME"] == "/home/cmods/bringup"
    assert out["NVIS_CLUSTER_ROOT"] == "/home/cmods"
    # The root, plus the one overridden path that lives outside it.
    assert out["RACK_STATUS_ALLOWED_PREFIXES"] == "/home/cmods,/scratch/logs"


def test_the_root_is_validated_like_every_data_dir():
    assert any("root" in p for p in _cluster({"root": "home/cmods"}).validate())
    assert any("bug_report_dir" in p for p in _cluster({"bug_report_dir": "relative"}).validate())
    assert _cluster(ROOTED).validate() == []


def test_the_record_beats_the_instance_environment(monkeypatch):
    """The point of the root: once a cluster names a path, no instance-wide variable can move it."""
    c = _cluster({**ROOTED})
    monkeypatch.setenv("RACK_REMOTE_BASE_PATH", "/home/someone-else/nvis-rack-status")
    overlay = context.high_overlay(cluster=c)
    assert overlay["RACK_REMOTE_BASE_PATH"] == "/home/cmods/nvis-rack-status"
    assert overlay["RACK_STATUS_ALLOWED_PREFIXES"] == "/home/cmods"
    # A cluster with no root publishes nothing, and the environment still answers for it.
    assert "RACK_REMOTE_BASE_PATH" not in context.high_overlay(cluster=_cluster())


def test_the_summary_names_a_value_only_the_environment_gives():
    data = cp.summary(_cluster(), "/cluster/containers", "/opt/containers",
                      {"NVIS_WORKSPACE_DIR": "/home/cmods/workspace"})
    rows = {r["key"]: r for r in data["paths"]}
    assert rows["workspace"]["source"] == "environment" and rows["workspace"]["path"] == "/home/cmods/workspace"
    assert rows["logs"]["source"] == "unset"
    assert [e["key"] for e in data["exceptions"]] == ["images_origin", "images_node"]
    assert data["exceptions"][1]["path"] == "/opt/containers"


# ---------------------------------------------------------------- consumers


@pytest.fixture
def active(monkeypatch):
    def use(cluster):
        monkeypatch.setattr("catalog.context.resolve", lambda *a, **k: (None, cluster, None))
        return cluster
    return use


def test_bringup_runs_only_where_the_cluster_says_so(active, monkeypatch):
    import bringup

    monkeypatch.delenv("RACK_BRINGUP_HOME", raising=False)
    monkeypatch.delenv("RACK_BRINGUP_DISABLED", raising=False)
    # A root derives a location for every cluster, so the location alone means nothing.
    active(_cluster(ROOTED))
    assert bringup.bringup_home() == "/home/cmods/bringup" and bringup.is_enabled() is False
    active(_cluster(ROOTED, {"bringup_enabled": True}))
    assert bringup.is_enabled() is True
    # A record that names the home explicitly predates the switch and counts as running it.
    active(_cluster({}, {"bringup_home": "/home/cmods/bringup"}))
    assert bringup.is_enabled() is True


def test_the_health_check_feed_is_bringups_output(active):
    import healthcheck_evidence

    active(_cluster(ROOTED))
    assert healthcheck_evidence.log_root() == ""
    active(_cluster(ROOTED, {"bringup_enabled": True}))
    assert healthcheck_evidence.log_root() == "/home/cmods/bringup-data/logs"
    active(_cluster(ROOTED, {"healthcheck_root": "/srv/health/"}))
    assert healthcheck_evidence.log_root() == "/srv/health"


def test_a_cluster_with_no_reports_folder_is_refused_by_name(monkeypatch):
    import paths

    monkeypatch.delenv("RACK_BUG_REPORT_REMOTE_DIR", raising=False)
    monkeypatch.setattr("catalog.context.resolve", lambda *a, **k: (None, None, None))
    with pytest.raises(paths.ReportsDirNotConfigured, match="Root"):
        paths._bug_report_remote_dir()
    monkeypatch.setenv("RACK_BUG_REPORT_REMOTE_DIR", "/srv/reports")
    assert paths._bug_report_remote_dir() == "/srv/reports"


# ---------------------------------------------------------------- images: only the node cache on P2P


def _preset(image_store="shared"):
    import validation_presets as vp

    return vp.Preset(id="t", label="T", description="", kind="nccl", scopes=("rack",), image_store=image_store)


def test_a_p2p_cluster_runs_images_only_from_the_node_cache(monkeypatch):
    import validation_presets as vp

    monkeypatch.setattr(vp, "node_images_p2p_managed", lambda: True)
    monkeypatch.delenv("RACK_VALIDATION_CONTAINER_ROOT", raising=False)
    assert vp.normalize_options({}, _preset())["storage"] == "local"
    # Even a preset with no image: the launcher refuses nfs on such a cluster, so never send it --
    # and a caller that still asks for nfs (the dialog's old default) gets local, not a refusal.
    assert vp.normalize_options({}, _preset(image_store=None))["storage"] == "local"
    assert vp.normalize_options({"storage": "nfs"}, _preset(image_store=None))["storage"] == "local"
    assert _preset(image_store=None).public()["defaults"]["storage"] == "local"
    with pytest.raises(ValueError, match="only from their own cache"):
        vp.normalize_options({"storage": "nfs"}, _preset())


def test_a_launch_that_reads_an_unnamed_origin_is_refused(monkeypatch):
    import validation_presets as vp

    monkeypatch.setattr(vp, "node_images_p2p_managed", lambda: False)
    monkeypatch.delenv("RACK_VALIDATION_CONTAINER_ROOT", raising=False)
    with pytest.raises(ValueError, match="Shared image store"):
        vp.normalize_options({"storage": "nfs"}, _preset())
    monkeypatch.setenv("RACK_VALIDATION_CONTAINER_ROOT", "/cluster/containers")
    assert vp.normalize_options({"storage": "nfs"}, _preset())["storage"] == "nfs"


def test_no_origin_named_means_the_node_copy_is_the_source(monkeypatch):
    import validation_presets as vp

    monkeypatch.delenv("RACK_VALIDATION_CONTAINER_ROOT", raising=False)
    monkeypatch.setenv("NVIS_NODE_CONTAINER_DIR", "/opt/containers")
    assert vp.shared_container_root() == "" and vp.llmb_image_root() == ""


# ---------------------------------------------------------------- the route


def test_the_route_serves_the_layout_and_the_checked_paths(active, monkeypatch):
    import app as app_module
    from api import cluster_paths as route

    active(_cluster({**ROOTED, "log_dir": "/scratch/logs"}))
    seen = []

    def run(cmd, **_k):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "11 /home/cmods/nvis-rack-status\n00 /scratch/logs\n10 /home/cmods/workspace\n", "")

    monkeypatch.setattr(route.host_exec, "run_on_host", run)
    client = app_module.app.test_client()
    layout = client.get("/api/cluster-paths/layout")
    if layout.status_code in (401, 403):
        pytest.skip("route requires a session in this app configuration")
    assert [e["key"] for e in layout.get_json()["layout"]] == [s.key for s in cp.LAYOUT]

    body = client.get("/api/cluster-paths?check=1").get_json()
    rows = {r["key"]: r for r in body["paths"]}
    assert body["root"] == "/home/cmods" and body["checked_on"] == "execution host"
    assert (rows["scripts"]["exists"], rows["scripts"]["writable"]) == (True, True)
    assert rows["logs"]["source"] == "override" and rows["logs"]["exists"] is False
    assert (rows["workspace"]["exists"], rows["workspace"]["writable"]) == (True, False)
    assert len(seen) == 1  # one round trip for every folder
