# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Manager inventory remains usable without Slurm or rack assignments."""
import json
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest
from platforms.base import PlatformProvider
from platforms.bcm import BCMProvider
from platforms.maas import MAASProvider


@pytest.fixture(autouse=True)
def no_live_transport(monkeypatch):
    monkeypatch.setattr(
        "host_exec.run_on_host", Mock(side_effect=AssertionError("unexpected cluster access")),
    )


def test_provider_default_explicitly_reports_unsupported():
    with pytest.raises(RuntimeError, match="unsupported"):
        PlatformProvider.compute_node_inventory(BCMProvider())


def test_bcm_preserves_assigned_and_unassigned_inventory(monkeypatch):
    query = Mock(return_value={"ok": True, "data": [
        {"hostname": "gpu001", "rack_id": "", "bmc_ip": "10.0.0.1"},
        {"hostname": "compute.example.test", "rack_id": "Row A / Rack 2", "bmc_ip": "10.0.0.2"},
        {"hostname": "gpu001", "rack_id": "", "bmc_ip": "10.0.0.1"},
    ]})
    monkeypatch.setattr("bcm_query.nodes", query)
    assert BCMProvider().compute_node_inventory() == [
        {"id": "gpu001", "rack": None, "ip": "10.0.0.1", "status": "unknown", "scheduler_state": ""},
        {"id": "compute.example.test", "rack": "Row A / Rack 2", "ip": "10.0.0.2",
         "status": "unknown", "scheduler_state": ""},
    ]
    query.assert_called_once_with()


@pytest.mark.parametrize("result", [
    {"ok": True, "data": {}},
    {"ok": True},
    {"ok": True, "data": [{"hostname": "gpu001"}, {"hostname": "node;id"}]},
    {"ok": True, "data": [{"hostname": "-option"}]},
    {"ok": True, "data": [None]},
    None,
])
def test_bcm_failures_do_not_become_empty_success(monkeypatch, result):
    monkeypatch.setattr("bcm_query.nodes", lambda: result)
    with pytest.raises(RuntimeError, match="BCM node inventory"):
        BCMProvider().compute_node_inventory()


def test_bcm_successful_empty_inventory_is_allowed(monkeypatch):
    monkeypatch.setattr("bcm_query.nodes", lambda: {"ok": True, "data": []})
    assert BCMProvider().compute_node_inventory() == []


def test_bcm_saved_rack_names_include_empty_and_numeric_racks(monkeypatch):
    monkeypatch.setattr("bcm_query.query", lambda query: {"ok": True, "data": ["F41", "12", "Empty-Rack"]})
    assert BCMProvider().rack_inventory() == ["12", "Empty-Rack", "F41"]


def test_bcm_rack_fallback_requests_headers_even_when_stdout_is_captured(monkeypatch):
    monkeypatch.setattr("bcm_query.query", lambda query: {"ok": False, "error": "old helper"})
    run = Mock(return_value=CompletedProcess([], 0,
        "name (key)          \n--------------------\n"
        "1                   \nF41                 \nF42                 \n", ""))
    monkeypatch.setattr("host_exec.run_on_host", run)
    assert BCMProvider().rack_inventory() == ["1", "F41", "F42"]
    run.assert_called_once_with(["cmsh", "--tty", "--nocolor", "-c", "rack; list -f name"], timeout=120)


def test_bcm_fallback_accepts_a_verified_empty_rack_table(monkeypatch):
    monkeypatch.setattr("bcm_query.query", lambda query: {"ok": False})
    monkeypatch.setattr("host_exec.run_on_host", Mock(return_value=CompletedProcess(
        [], 0, "name (key)          \n--------------------\n", "",
    )))
    assert BCMProvider().rack_inventory() == []


def test_failed_bcm_rack_query_is_not_successful_empty_inventory(monkeypatch):
    monkeypatch.setattr("bcm_query.query", lambda query: {"ok": False})
    monkeypatch.setattr("host_exec.run_on_host", Mock(return_value=CompletedProcess([], 1, "", "BCM offline")))
    with pytest.raises(RuntimeError, match="BCM offline"):
        BCMProvider().rack_inventory()


def test_bcm_does_not_accept_silent_empty_cmsh_output_as_empty_rack_inventory(monkeypatch):
    monkeypatch.setattr("bcm_query.query", lambda query: {"ok": False})
    monkeypatch.setattr("host_exec.run_on_host", Mock(return_value=CompletedProcess([], 0, "", "")))
    with pytest.raises(RuntimeError, match="invalid cmsh rack table"):
        BCMProvider().rack_inventory()


def test_bcm_fallback_preserves_live_beacon_placement_and_blank_assignments(monkeypatch):
    monkeypatch.setattr("bcm_query.nodes", lambda: {"ok": False, "error": "credentials unavailable"})
    run = Mock(return_value=CompletedProcess([], 0,
        "dgx-b300-01\nF41:2\ndgx-b300-02\nF41:36\ndgx-b300-03\nF42:2\n"
        "dgx-b300-04\nF42:36\nk8s-ctrl-01\n\n", ""))
    monkeypatch.setattr("host_exec.run_on_host", run)
    nodes = BCMProvider().compute_node_inventory()
    assert [(n["id"], n["rack"], n.get("rack_unit")) for n in nodes] == [
        ("dgx-b300-01", "F41", "2"), ("dgx-b300-02", "F41", "36"),
        ("dgx-b300-03", "F42", "2"), ("dgx-b300-04", "F42", "36"),
        ("k8s-ctrl-01", None, None),
    ]


def test_bcm_incomplete_fallback_output_does_not_shift_node_assignments(monkeypatch):
    monkeypatch.setattr("bcm_query.nodes", lambda: {"ok": False})
    monkeypatch.setattr("host_exec.run_on_host", Mock(return_value=CompletedProcess([], 0, "dgx-b300-01\n", "")))
    with pytest.raises(RuntimeError, match="incomplete cmsh"):
        BCMProvider().compute_node_inventory()


def test_bcm_query_and_cmsh_failure_are_reported(monkeypatch):
    monkeypatch.setattr("bcm_query.nodes", lambda: {"ok": False})
    monkeypatch.setattr("host_exec.run_on_host", Mock(return_value=CompletedProcess([], 1, "", "BCM offline")))
    with pytest.raises(RuntimeError, match="BCM node inventory failed: BCM offline"):
        BCMProvider().compute_node_inventory()


@pytest.mark.parametrize("scheduler", ["slurm", "pythoncm", "local"])
def test_bcm_falls_back_to_cmsh_whatever_the_scheduler(monkeypatch, scheduler):
    """The pythoncm helper may lack credentials on any BCM site; cmsh answers the same question."""
    monkeypatch.setenv("RACK_SCHEDULER", scheduler)
    monkeypatch.setattr("bcm_query.nodes", lambda: {"ok": False, "error": "credentials unavailable"})
    monkeypatch.setattr("host_exec.run_on_host", Mock(return_value=CompletedProcess([], 0, "gpu001\nQ5:11\n", "")))
    assert [(n["id"], n["rack"], n.get("rack_unit")) for n in BCMProvider().compute_node_inventory()] == [
        ("gpu001", "Q5", "11"),
    ]


def test_malformed_bcm_rack_query_does_not_turn_dict_keys_into_racks(monkeypatch):
    monkeypatch.setattr("bcm_query.query", lambda query: {"ok": True, "data": {"rack": "F41"}})
    with pytest.raises(RuntimeError, match="list of rack names"):
        BCMProvider().rack_inventory()


def test_bcm_preserves_physical_rack_unit(monkeypatch):
    monkeypatch.setattr("bcm_query.nodes", lambda: {"ok": True, "data": [
        {"hostname": "dgx-b300-01", "rack_id": "F41", "rack_unit": " 2 "},
    ]})
    node = BCMProvider().compute_node_inventory()[0]
    assert (node["rack"], node["rack_unit"]) == ("F41", "2")


def test_bcm_reports_the_rack_unit_whichever_scheduler_runs(monkeypatch):
    """The unit is BCM's placement fact; Nscale NC is BCM with pythoncm, and its rack page needs it."""
    import config_env

    values = {"RACK_PLATFORM": "bcm", "RACK_SCHEDULER": "pythoncm"}
    monkeypatch.setattr(config_env, "_eget", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr("bcm_query.nodes", lambda: {"ok": True, "data": [
        {"hostname": "gpu001", "rack_id": "U19", "rack_unit": "2"},
    ]})
    assert BCMProvider().compute_node_inventory() == [
        {"id": "gpu001", "rack": "U19", "status": "unknown", "ip": "", "scheduler_state": "",
         "rack_unit": "2"},
    ]


def test_maas_uses_machine_hostnames_without_fabricating_racks_or_health(monkeypatch):
    machine = {"hostname": "maas-gpu-1", "status": 6, "status_name": "Deployed",
               "ip_addresses": ["10.0.0.9"], "tag_names": ["rack-a"]}
    run = Mock(return_value=CompletedProcess([], 0, json.dumps([machine, machine]), ""))
    monkeypatch.setattr("host_exec.run_on_host", run)
    provider = MAASProvider()
    assert provider.compute_node_inventory() == [
        {"id": "maas-gpu-1", "rack": None, "ip": "", "status": "unknown", "scheduler_state": ""},
    ]
    run.assert_called_once_with(provider.device_status_cmd(), timeout=120)


@pytest.mark.parametrize(("returncode", "stdout", "error"), [
    (1, "[]", "exit 1"),
    (0, "not JSON", "invalid JSON"),
    (0, "{}", "list of devices"),
    (0, '[{"hostname":"gpu 01"}]', "invalid hostname"),
    (0, '[{"system_id":"uuid-only"}]', "invalid hostname"),
])
def test_maas_failures_are_explicit(monkeypatch, returncode, stdout, error):
    monkeypatch.setattr(
        "host_exec.run_on_host", Mock(return_value=CompletedProcess([], returncode, stdout, "")),
    )
    with pytest.raises(RuntimeError, match=error):
        MAASProvider().compute_node_inventory()


def test_maas_successful_empty_inventory_is_allowed(monkeypatch):
    monkeypatch.setattr(
        "host_exec.run_on_host", Mock(return_value=CompletedProcess([], 0, "[]", "")),
    )
    assert MAASProvider().compute_node_inventory() == []
