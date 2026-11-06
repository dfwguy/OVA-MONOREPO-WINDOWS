# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""A run's times are its scheduler job's, not its launcher's.

Nscale NC, 2026-10-26: the official handover report for a 3-minute, 996-GPU NCCL job said it
started and finished at 14:02 -- the activity's ``finished_at`` is when the launcher returned,
seconds after ``sbatch``. The registry now records each task's Slurm start and end.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("RACK_EXEC_MODE", "local")

import activity_hydration as ah
import validation_activities as va


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(va, "ACTIVITIES_FILE", tmp_path / "validation_activities.json")
    monkeypatch.setattr(va, "LEGACY_JOBS_FILE", tmp_path / "multirack_jobs.json")
    monkeypatch.setattr(va, "ACTIVITY_ARCHIVE_DB", tmp_path / "validation_activities.sqlite3")
    monkeypatch.setattr(va, "_archive_sync_signature", None)


def _activity(work_phase: str = "done") -> str:
    aid = va.record_activity("llmb-nccl", scope="multirack", racks=["U2", "V19"])
    va.add_or_update_task(aid, ordinal=1, label="nccl", task_id="t1", scheduler_ref="222500",
                          work_phase=work_phase)
    return aid


def test_slurm_times_carry_their_offset_into_utc():
    assert ah._slurm_time_utc("2026-10-26T10:02:44-0400") == "2026-10-26T14:02:44+00:00"
    assert ah._slurm_time_utc("Unknown") is None and ah._slurm_time_utc("") is None


def test_the_sacct_query_asks_for_a_format_with_the_offset(monkeypatch):
    seen = []

    def run(cmd, **_k):
        seen.append(cmd)
        return SimpleNamespace(stdout="222500|2026-10-26T10:02:44-0400|2026-10-26T10:05:55-0400\n")

    monkeypatch.setattr(ah.host_exec, "run_slurm_on_host", run)
    assert ah._query_job_times("222500") == ("2026-10-26T14:02:44+00:00", "2026-10-26T14:05:55+00:00")
    assert seen[0].startswith("export SLURM_TIME_FORMAT=") and "-o JobID,Start,End" in seen[0]
    assert ah._query_job_times("not-a-job") == (None, None)


def test_a_finished_task_gets_its_job_times_once(monkeypatch):
    asked = []
    monkeypatch.setattr(ah, "_query_job_times",
                        lambda ref: asked.append(ref) or ("2026-10-26T14:02:44+00:00", "2026-10-26T14:05:55+00:00"))
    aid = _activity()
    assert ah.record_job_times(aid) is True
    task = va.get_activity(aid)["tasks"][0]
    assert (task["started_at"], task["ended_at"]) == ("2026-10-26T14:02:44+00:00", "2026-10-26T14:05:55+00:00")
    assert ah.record_job_times(aid) is False and asked == ["222500"]  # kept: never asked again


def test_a_running_task_or_a_job_accounting_forgot_records_nothing(monkeypatch):
    monkeypatch.setattr(ah, "_query_job_times", lambda ref: ("2026-10-26T14:02:44+00:00", None))
    assert ah.record_job_times(_activity()) is False
    asked = []
    monkeypatch.setattr(ah, "_query_job_times", lambda ref: asked.append(ref) or ("a", "b"))
    assert ah.record_job_times(_activity(work_phase="running")) is False and asked == []
    assert ah.record_job_times("gone") is False
