# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
"""The reports base resolves through the config ladder, and one setting moves both feeds.

Regression for the Reports page falling back to the hardcoded ``/home/cmsupport/reports``:
``_bug_report_remote_dir`` used to read ``os.environ`` directly, so neither a cluster overlay
nor the Settings screen could point it at a project's own prefix. It now goes through ``_eget``,
and ``_nvlmapper_reports_base`` defaults to it so the Reports page lists both under one tree.
"""
from __future__ import annotations

import paths
import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("RACK_BUG_REPORT_REMOTE_DIR", raising=False)
    monkeypatch.delenv("RACK_NVLMAPPER_REPORTS_BASE", raising=False)


def test_nothing_set_refuses_and_names_the_setting(monkeypatch):
    """No built-in default any more: /home/cmsupport/reports existed on one appliance, so a cluster
    that named nothing wrote its reports where nobody looked. Unset now says what to set."""
    monkeypatch.setattr("catalog.context.resolve", lambda *a, **k: (None, None, None))
    with pytest.raises(paths.ReportsDirNotConfigured, match="Root"):
        paths._bug_report_remote_dir()


def test_it_follows_the_configured_prefix(monkeypatch):
    # The config ladder's process-env rung -- what a deployment or the Settings screen writes.
    monkeypatch.setenv("RACK_BUG_REPORT_REMOTE_DIR", "/home/cmods/bringup-data/reports")
    assert paths._bug_report_remote_dir() == "/home/cmods/bringup-data/reports"


def test_nvlmapper_base_defaults_to_the_bug_report_dir(monkeypatch):
    # One value moves both feeds: set only the bug-report dir, NVLMapper follows.
    # (_nvlmapper_reports_base runs the result through _rpath, so normalise the same way.)
    monkeypatch.setenv("RACK_BUG_REPORT_REMOTE_DIR", "/home/cmods/bringup-data/reports")
    assert paths._nvlmapper_reports_base() == paths._rpath("/home/cmods/bringup-data/reports")


def test_nvlmapper_base_still_honours_its_own_override(monkeypatch):
    monkeypatch.setenv("RACK_BUG_REPORT_REMOTE_DIR", "/home/cmods/bringup-data/reports")
    monkeypatch.setenv("RACK_NVLMAPPER_REPORTS_BASE", "/home/cmods/nvlmapper")
    assert paths._nvlmapper_reports_base() == paths._rpath("/home/cmods/nvlmapper")
