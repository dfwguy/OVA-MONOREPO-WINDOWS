# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""A multi-rack NCCL launch tells the launcher where the run's log goes.

``run_nccl_mpi.sh`` runs on the cluster and writes its Slurm ``--output`` under ``RACK_JOB_LOG_DIR``,
falling back to its own cwd. The single-rack path always set it; the multi-rack one did not, so on
Beacon (BCM + Slurm, translate) the log landed beside the script and neither the parser nor the
activity found it. Nothing about that is specific to a manager, scheduler or mapping mode.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("RACK_STATUS_DEMO", "1")
os.environ.setdefault("RACK_EXEC_MODE", "local")

import app as app_module
import config_env
import pytest
import validation_launch
from api import validation_runs

MANAGERS = ("bcm", "maas")
SCHEDULERS = ("slurm", "pythoncm", "local")


@pytest.fixture
def direct(monkeypatch):
    """A direct-mode cluster: rack ids ride to the launcher, which expands them itself."""
    monkeypatch.setattr(config_env, "rack_mapping_mode", lambda: "direct")
    monkeypatch.setattr(validation_launch, "_multirack_campaign_snapshot", lambda: {"ok": True, "active": False})
    monkeypatch.setattr(validation_runs, "_script_exists", lambda _path: True)
    monkeypatch.setattr(validation_runs, "_normalize_rack_id", lambda rack: rack)


def _prepare(monkeypatch, log_dir: Path, body: dict):
    monkeypatch.setattr(validation_runs, "_resolve_log_dir", lambda _raw=None: log_dir)
    with app_module.app.app_context():
        return validation_runs._prepare_run_llmb_nccl({"racks": ["F41", "F42"], "dry_run": True, **body})


@pytest.mark.parametrize("manager", MANAGERS)
@pytest.mark.parametrize("scheduler", SCHEDULERS)
def test_every_cluster_gets_the_resolved_log_dir(direct, monkeypatch, manager, scheduler):
    values = {"RACK_PLATFORM": manager, "RACK_SCHEDULER": scheduler}
    real = config_env._eget
    monkeypatch.setattr(config_env, "_eget", lambda key, default=None: values.get(key) or real(key, default))
    log_dir = Path("/remote/beacon validation/logs")

    prepared, err = _prepare(monkeypatch, log_dir, {})

    assert err is None
    assert prepared["env_updates"]["RACK_JOB_LOG_DIR"] == str(log_dir)
    assert prepared["log_dir"] == log_dir


def test_an_explicit_per_run_log_dir_wins(direct, monkeypatch, tmp_path):
    prepared, err = _prepare(monkeypatch, tmp_path, {
        "env": {"RACK_JOB_LOG_DIR": "/operator/custom logs", "NCCL_DEBUG": "INFO"},
    })

    assert err is None
    assert prepared["env_updates"]["RACK_JOB_LOG_DIR"] == "/operator/custom logs"
    assert prepared["env_updates"]["NCCL_DEBUG"] == "INFO"


def test_the_collective_env_still_rides_beside_it(direct, monkeypatch, tmp_path):
    """The log dir is added to main's env, not substituted for it."""
    prepared, err = _prepare(monkeypatch, tmp_path, {"collectives": ["alltoall"]})

    assert err is None
    env = prepared["env_updates"]
    assert env["RACK_JOB_LOG_DIR"] == str(tmp_path)
    expected = validation_runs._nccl_collective_env(
        ["alltoall"], {"collectives": ["alltoall"]},
        scope=validation_runs.nccl_env_scope(2, 0),
    )
    assert expected.items() <= env.items()
