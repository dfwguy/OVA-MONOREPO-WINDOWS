# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""handover_report: a multi-rack run folded into what a rack handover is signed off on."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("RACK_EXEC_MODE", "local")

import handover_report as hr
import validation_activities as va

NCCL_LOG = "/logs/nccl-mpi_U8+Q7_1001.out"
NEMO_LOG = "/logs/root-NEMO-U8+Q7-32N-1002.txt"
GIB = 1024**3


def _series(peak: float) -> list[dict]:
    sizes = [GIB // 4, GIB // 2, GIB, 2 * GIB, 4 * GIB]
    return [{"size_bytes": s, "bus_bw_gbps": round(peak * (i + 1) / len(sizes), 2)} for i, s in enumerate(sizes)]


NCCL_SCAN = {
    "path": NCCL_LOG,
    "ok": True,
    "bytes": 38648,
    "nccl": {
        "peak_busbw_gbps": {"ar": 790.0, "aa": 180.2},
        "series_by_collective": {"all_reduce": _series(790.0), "alltoall": _series(180.2)},
    },
    "nemo": {"samples": 0, "step_series": []},
    "geometry": {"nccl_nodes": "32", "nccl_np": "128"},
    "statements": [
        "nvis_fabric: link=roce rate=200G rails=4 NCCL_IB_HCA=roce_vf_r NCCL_IB_ADDR_FAMILY=AF_INET6",
        "nccl_allreduce: forwarding extra env to all ranks: NCCL_BUFFSIZE NCCL_NET",
        "nccl_allreduce: nodes=32 np=128 gpus/node=4 sizes=8..16G rounds=1 collectives=all_reduce alltoall",
        "nccl_allreduce: NCCL version=2.30.7 lib=/ws/nccl-2.30.7/nccl/build/lib",
        "nccl_allreduce: alltoall: its own NCCL settings: NCCL_BUFFSIZE=8388608 NCCL_IB_QPS_PER_CONNECTION=4",
    ],
    "llm_params": {},
}

NEMO_SCAN = {
    "path": NEMO_LOG,
    "ok": True,
    "bytes": 15885109,
    "nccl": {"peak_busbw_gbps": {"ag": 291.0}, "series_by_collective": {"all_gather": _series(291.0)}},
    "nemo": {
        "samples": 50,
        "step_time_s": 4.22,
        "tflops_per_gpu": 1955.1,
        "mfu_percent": 39.1,
        "declared_max_steps": 50,
        "finished": True,
        "step_series": [95.5] + [4.2] * 49,
    },
    "geometry": {"num_gpus": "128", "gpus_per_node": "4", "global_batch": "432"},
    "statements": [
        "INFO: LLM params model=nemotronh size=56b dtype=fp8_cs gbs=432 max_steps=50",
        "INFO: model_args=[--model_family_name nemotronh] extra_args=[-tp 2 -gb 432]",
    ],
    "llm_params": {"model": "nemotronh", "size": "56b", "dtype": "fp8_cs", "gbs": "432", "max_steps": "50"},
}

SCANS = {NCCL_LOG: NCCL_SCAN, NEMO_LOG: NEMO_SCAN}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(va, "ACTIVITIES_FILE", tmp_path / "validation_activities.json")
    monkeypatch.setattr(va, "LEGACY_JOBS_FILE", tmp_path / "multirack_jobs.json")
    monkeypatch.setattr(va, "ACTIVITY_ARCHIVE_DB", tmp_path / "validation_activities.sqlite3")
    monkeypatch.setattr(va, "_archive_sync_signature", None)
    monkeypatch.setattr(hr, "_logscan_record", lambda p: SCANS.get(p))
    monkeypatch.setattr(hr, "_logscan_batch", lambda paths, on_progress=None: {p: SCANS[p] for p in paths if p in SCANS})
    monkeypatch.setattr(
        hr,
        "site_context",
        lambda: {
            "project": "Nscale",
            "cluster": "NscaleTX-NC",
            "platform": "GB300 NVL72",
            "gpu_model": "GB300",
            "rack_su": {"U8": "SU20", "Q7": "SU22"},
        },
    )
    # Hydration asks Slurm; here the registry rows are already what a hydrated run looks like.
    monkeypatch.setattr(hr, "refresh_activities_lazy", lambda rows: set())
    # The backfill runs inline here so a test sees its result.
    monkeypatch.setattr(hr, "ensure_backfill", lambda: hr.run_backfill() and False)
    # Node facts probe the fleet; a test that wants them collects them itself.
    started.clear()
    monkeypatch.setattr(hr, "ensure_node_facts", lambda aid: started.append(aid) or True)
    monkeypatch.setattr(hr.native_status, "placed_node_facts", lambda hosts: {})


started: list[str] = []


def _run(tool: str, log: str, *, done: bool = True, env: dict | None = None, nodes: list[str] | None = None) -> str:
    aid = va.record_activity(
        tool,
        scope="multirack",
        racks=["U8", "Q7"],
        command_display=f"./{tool}.sh --racks U8,Q7",
        launch_env=env,
        nodes=nodes,
    )
    task = {"task_id": "t1", "scheduler_ref": "1001", "stdout_path": log,
            "work_phase": "done" if done else "running", "phase": "done" if done else "running"}
    va.update_activity(aid, tasks=[task], phase="done")
    rec = va.get_activity(aid)
    rec["work_phase"] = "done" if done else "running"

    def _mut(rows):
        rows[aid]["work_phase"] = rec["work_phase"]

    va._with_store(_mut)
    return aid


def test_summarize_scan_reads_peak_and_the_2gb_criterion():
    s = hr.summarize_scan(NCCL_SCAN)
    assert s["collectives"]["alltoall"] == {
        "busbw_peak_gbps": 180.2,
        "busbw_2g_gbps": pytest.approx(180.2 * 4 / 5, abs=0.01),
        "max_size_bytes": 4 * GIB,
    }
    assert (s["nodes"], s["gpus"], s["llm"]) == (32, 128, None)


def test_the_2gb_row_is_found_when_nccl_tests_rounded_the_size():
    """On 144 ranks the all-to-all "2 GB" row is 2,147,483,520 bytes: a multiple of the ranks."""
    rows = [{"size_bytes": 1073741760, "bus_bw_gbps": 120.0}, {"size_bytes": 2147483520, "bus_bw_gbps": 140.6}]
    assert hr._size_at(rows, hr.CRITERION_BYTES) == 140.6
    assert hr._size_at([{"size_bytes": 3 * GIB, "bus_bw_gbps": 1.0}], hr.CRITERION_BYTES) is None


def test_run_type_comes_from_what_the_logs_contain():
    """A cross-rack NeMo job sweeps NCCL before it trains: it is both, whatever its tool name."""
    assert hr.run_type(hr.summarize_scan(NCCL_SCAN)) == "nccl"
    assert hr.run_type(hr.summarize_scan(NEMO_SCAN)) == "both"
    assert hr.run_type({"collectives": {}, "llm": {"model": "x"}}) == "llm"
    assert hr.run_type(None) == "none"


def test_list_folds_finished_runs_and_leaves_running_ones_alone():
    done = _run("llmb-nccl", NCCL_LOG)
    running = _run("nemo-xrack", NEMO_LOG, done=False)
    # The first list answers at once and starts the backfill; the numbers are there on the next.
    first = {r["activity_id"]: r for r in hr.list_runs()["runs"]}
    assert first[done]["summary_state"] == "pending"
    rows = {r["activity_id"]: r for r in hr.list_runs()["runs"]}
    assert rows[done]["summary_state"] == "ready"
    assert rows[done]["collectives"]["all_reduce"]["busbw_peak_gbps"] == 790.0
    assert rows[done]["gpus"] == 128
    assert rows[done]["scalable_units"] == ["SU20", "SU22"]
    assert rows[running]["summary_state"] == "running"
    assert va.get_activity(running).get("results_summary") is None


def test_a_stored_summary_is_not_refolded_until_its_version_changes(monkeypatch):
    aid = _run("llmb-nccl", NCCL_LOG)
    assert hr.run_backfill() == 1
    assert hr.run_backfill() == 0
    monkeypatch.setattr(hr, "SUMMARY_VERSION", hr.SUMMARY_VERSION + 1)
    assert hr.run_backfill() == 1
    assert va.get_activity(aid)["results_summary"]["version"] == hr.SUMMARY_VERSION


def test_a_run_whose_log_the_scanner_never_answered_for_stays_pending(monkeypatch):
    monkeypatch.setattr(hr, "_logscan_batch", lambda paths, on_progress=None: {})
    aid = _run("llmb-nccl", NCCL_LOG)
    assert hr.run_backfill() == 0
    assert va.get_activity(aid).get("results_summary") is None


def test_list_filters_by_scalable_unit():
    _run("llmb-nccl", NCCL_LOG)
    assert len(hr.list_runs(scalable_unit="SU20")["runs"]) == 1
    assert hr.list_runs(scalable_unit="SU23")["runs"] == []


def test_detail_carries_curves_steps_settings_and_command():
    aid = _run("nemo-xrack", NEMO_LOG, env={"NCCL_NET": "IB", "HF_TOKEN": "hf_supersecretvalue"})
    d = hr.run_detail(aid)
    assert d["run_type"] == "both"
    assert d["llm"]["model"] == "nemotronh" and d["llm"]["tflops_per_gpu"] == 1955.1
    assert [p["size_bytes"] for p in d["nccl_curves"]["all_gather"]][-1] == 4 * GIB
    assert d["llm_steps"][1] == {"step": 2, "step_time_s": 4.2, "steps_per_s": pytest.approx(1 / 4.2, rel=1e-4)}
    assert d["settings"]["launch_env"]["NCCL_NET"] == "IB"
    assert d["settings"]["launch_env"]["HF_TOKEN"] == "[REDACTED]"
    assert d["settings"]["stated"]["extra_args"] == "-tp 2 -gb 432"
    assert d["command"]["launcher"] == "./nemo-xrack.sh --racks U8,Q7"
    assert d["site"]["cluster"] == "NscaleTX-NC"
    assert d["rack_su"] == {"U8": "SU20", "Q7": "SU22"}


def test_stated_settings_separate_global_per_collective_and_scale():
    s = hr.stated_settings(NCCL_SCAN["statements"])
    assert s["env"]["NCCL_IB_HCA"] == "roce_vf_r"
    assert s["per_collective"] == {"alltoall": {"NCCL_BUFFSIZE": "8388608", "NCCL_IB_QPS_PER_CONNECTION": "4"}}
    assert s["forwarded"] == ["NCCL_BUFFSIZE", "NCCL_NET"]
    assert (s["nccl_version"], s["sizes"], s["rounds"]) == ("2.30.7", "8..16G", 1)
    assert s["collectives"] == ["all_reduce", "alltoall"]


def test_long_step_series_are_thinned_for_the_chart():
    pts = hr._thin([4.0] * 2010, limit=500)
    assert len(pts) <= 501 and pts[-1]["step"] == 2010


def test_detail_of_an_unknown_or_single_rack_run_is_none():
    assert hr.run_detail("nope") is None
    aid = va.record_activity("nvloom", rack="U8")
    assert hr.run_detail(aid) is None


def test_report_names_missing_runs_instead_of_dropping_them():
    aid = _run("llmb-nccl", NCCL_LOG)
    ds = hr.report_dataset([aid, "gone"])
    assert [r["activity_id"] for r in ds["runs"]] == [aid]
    assert ds["missing"] == ["gone"]
    assert ds["racks"] == ["Q7", "U8"]


# --- the PDF ---------------------------------------------------------------------------------------


def test_the_pdf_carries_the_site_runs_and_charts(tmp_path):
    import handover_report_pdf

    if not handover_report_pdf.available():
        pytest.skip("reportlab not installed")
    aid = _run("nemo-xrack", NEMO_LOG, env={"NCCL_NET": "IB"})
    pdf = handover_report_pdf.to_pdf(hr.report_dataset([aid]))
    assert pdf.startswith(b"%PDF") and len(pdf) > 10_000
    # The text layer: reportlab writes subset fonts, so check the document's own metadata title.
    assert b"Rack Handover Report" in pdf


def test_sizes_rounded_by_nccl_tests_print_as_the_size_they_stand_for():
    import handover_report_pdf as p

    assert p._size(17179869180) == "16 GB"
    assert p._size(2 * GIB) == "2 GB"
    assert p._size(1536 * 1024**2) == "1.5 GB"
    assert p._size(None) == "—"


# --- the routes ------------------------------------------------------------------------------------


def _client():
    import app as app_module

    return app_module.app.test_client()


def test_run_routes_list_and_detail():
    aid = _run("llmb-nccl", NCCL_LOG)
    hr.run_backfill()
    r = _client().get("/api/handover-reports/runs?su=SU20")
    if r.status_code in (401, 403):
        pytest.skip("route requires a session in this app configuration")
    body = r.get_json()
    assert r.status_code == 200 and body["ok"]
    assert [x["activity_id"] for x in body["runs"]] == [aid]
    d = _client().get(f"/api/handover-reports/runs/{aid}").get_json()
    assert d["run"]["nccl_curves"]["alltoall"][-1]["size_bytes"] == 4 * GIB
    assert _client().get("/api/handover-reports/runs/nope").status_code == 404


def test_report_route_serves_a_pdf_and_keeps_a_copy(monkeypatch):
    import handover_report_pdf
    import report_store

    if not handover_report_pdf.available():
        pytest.skip("reportlab not installed")
    saved = []
    monkeypatch.setattr(report_store, "save", lambda **kw: saved.append(kw) or {"id": "x"})
    aid = _run("llmb-nccl", NCCL_LOG)
    r = _client().get(f"/api/handover-reports/report?ids={aid}")
    if r.status_code in (401, 403):
        pytest.skip("route requires a session in this app configuration")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    assert "NscaleTX-NC_Handover_SU20-SU22_" in r.headers["Content-Disposition"]
    assert saved and saved[0]["kind"] == "handover" and saved[0]["meta"]["runs"] == [aid]
    assert not saved[0]["filename"].endswith(".pdf")


def test_report_route_refuses_bad_ids_and_unknown_runs():
    c = _client()
    r = c.get("/api/handover-reports/report?ids=")
    if r.status_code in (401, 403):
        pytest.skip("route requires a session in this app configuration")
    assert r.status_code == 400
    assert c.get("/api/handover-reports/report?ids=a%20b").status_code == 400
    assert c.get("/api/handover-reports/report?ids=gone").status_code == 404
    aid = _run("llmb-nccl", NCCL_LOG)
    assert c.get(f"/api/handover-reports/report?ids={aid}&format=xml").status_code == 400
    j = c.get(f"/api/handover-reports/report?ids={aid}&format=json").get_json()
    assert j["report"]["runs"][0]["activity_id"] == aid


def test_scalable_units_and_racks_sort_naturally():
    assert sorted(["SU10", "SU2", "SU1"], key=hr.natural_key) == ["SU1", "SU2", "SU10"]
    assert sorted(["U10", "U2", "Q7"], key=hr.natural_key) == ["Q7", "U2", "U10"]


def test_a_run_hydrated_on_read_is_read_again(monkeypatch):
    """A run that just ended gets its log path from hydration; the detail must use the new record."""
    aid = _run("llmb-nccl", NCCL_LOG)

    def _hydrate(rows):
        def _mut(stored):
            stored[aid]["tasks"][0]["stdout_path"] = NCCL_LOG
        va._with_store(_mut)
        return {aid}

    def _blank(stored):
        stored[aid]["tasks"][0]["stdout_path"] = ""
    va._with_store(_blank)
    monkeypatch.setattr(hr, "refresh_activities_lazy", _hydrate)
    d = hr.run_detail(aid)
    assert d["logs"][0]["path"] == NCCL_LOG
    assert d["collectives"]["all_reduce"]["busbw_peak_gbps"] == 790.0


# --- the NCCL program itself -----------------------------------------------------------------------

STATED_COMMAND_LINES = [
    "nccl_allreduce: nodes=2 np=8 gpus/node=4 sizes=8..16G rounds=1 collectives=alltoall",
    "nccl_allreduce: bin=/ws/nccl-tests/build/all_reduce_perf per-collective timeout=120s (nccl-tests -T)",
    "nccl_allreduce: orted launch agent: ssh -o StrictHostKeyChecking=no",
    "nccl_allreduce: alltoall: env: NCCL_NET=IB UCX_TLS=tcp NCCL_BUFFSIZE=8388608",
    "nccl_allreduce: alltoall: LD_LIBRARY_PATH=/ws/nccl/lib:/hpcx/ompi/lib",
    ("nccl_allreduce: alltoall: command: mpirun -np 8 --hostfile hosts -x NCCL_NET -x UCX_TLS "
     "/ws/nccl-tests/build/alltoall_perf -b 8 -e 16G -f 2 -g 1 -T 120"),
]


def test_stated_settings_read_the_exact_command_and_its_parts():
    s = hr.stated_settings(STATED_COMMAND_LINES)
    assert s["commands"]["alltoall"].startswith("mpirun -np 8 --hostfile hosts")
    assert s["collective_env"]["alltoall"] == {"NCCL_NET": "IB", "UCX_TLS": "tcp", "NCCL_BUFFSIZE": "8388608"}
    assert s["ld_library_path"] == "/ws/nccl/lib:/hpcx/ompi/lib"
    assert (s["bin"], s["test_timeout"]) == ("/ws/nccl-tests/build/all_reduce_perf", 120)
    assert s["rsh_agent"] == "ssh -o StrictHostKeyChecking=no"
    assert (s["np"], s["gpus_per_node"]) == (8, 4)
    # The command line is the command, not a pile of environment assignments.
    assert "NCCL_NET" not in s["env"]


def test_a_job_that_printed_its_command_is_quoted_exactly():
    cmds = hr.nccl_commands(hr.stated_settings(STATED_COMMAND_LINES), {"NCCL_NET": "Socket"})
    assert cmds == [{
        "collective": "alltoall",
        "source": "stated",
        "env": {"NCCL_NET": "IB", "UCX_TLS": "tcp", "NCCL_BUFFSIZE": "8388608"},
        "ld_library_path": "/ws/nccl/lib:/hpcx/ompi/lib",
        "command": STATED_COMMAND_LINES[-1].split("command: ", 1)[1],
    }]


def test_an_older_job_has_its_command_rebuilt_from_what_it_printed():
    lines = [*NCCL_SCAN["statements"],
             "nccl_allreduce: bin=/ws/nccl-tests/build/all_reduce_perf per-collective timeout=90s (nccl-tests -T)",
             "nccl_allreduce: NCCL_IB_HCA=roce_vf_r NCCL_SOCKET_IFNAME=bond0 (MPI bootstrap: ob1/tcp over bond0)",
             "nccl_allreduce: orted launch agent: ssh -o BatchMode=yes"]
    cmds = {c["collective"]: c for c in hr.nccl_commands(hr.stated_settings(lines), {"NCCL_NET": "IB"})}
    assert set(cmds) == {"all_reduce", "alltoall"}
    a2a = cmds["alltoall"]
    assert a2a["source"] == "reconstructed"
    assert a2a["command"].startswith("mpirun -np 128 --hostfile hosts --map-by ppr:4:node")
    assert "--mca plm_rsh_agent 'ssh -o BatchMode=yes'" in a2a["command"]
    assert "-x NCCL_SOCKET_IFNAME=bond0 -x NCCL_IB_HCA=roce_vf_r" in a2a["command"]
    assert a2a["command"].endswith("/ws/nccl-tests/build/alltoall_perf -b 8 -e 16G -f 2 -g 1 -T 90")
    assert "/all_reduce_perf " in cmds["all_reduce"]["command"]
    # Forwarded values the launch recorded are filled in, the rest left for the reader; the
    # collective's own settings win.
    assert a2a["env"] == {"NCCL_BUFFSIZE": "8388608", "NCCL_NET": "IB", "NCCL_IB_QPS_PER_CONNECTION": "4"}
    assert cmds["all_reduce"]["env"] == {"NCCL_BUFFSIZE": "", "NCCL_NET": "IB"}


def test_no_command_is_invented_without_the_binary_and_scale():
    assert hr.nccl_commands(hr.stated_settings(NCCL_SCAN["statements"]), {}) == []


# --- the nodes a run held --------------------------------------------------------------------------


def test_run_nodes_prefer_the_roster_then_the_launch_node_list():
    assert hr.run_nodes({"nodes": ["gpu2-su20", "gpu1-su20"]}) == ["gpu2-su20", "gpu1-su20"]
    rec = {"command_display": "./run-llmb-nccl.sh --nodelist 'gpu1-su20,gpu2-su20,bad;rm' U2"}
    assert hr.run_nodes(rec) == ["gpu1-su20", "gpu2-su20"]
    assert hr.run_nodes({"command_display": "./run.sh U2"}) == []


def _nodes_run(nodes: list[str]) -> str:
    return _run("llmb-nccl", NCCL_LOG, nodes=nodes)


def test_node_facts_are_collected_once_and_kept_with_the_run(monkeypatch):
    import bringup

    aid = _nodes_run(["gpu1-su20", "gpu2-su20"])
    monkeypatch.setattr(bringup, "is_enabled", lambda: True)
    monkeypatch.setattr(bringup, "run_daily_report", lambda: "csv")
    monkeypatch.setattr(bringup, "parse_daily_report_csv", lambda text: (
        ["allreduce", "alltoall", "allreduce-nonvlink", "alltoall-nonvlink"],
        {"gpu1-su20": {"cells": {"allreduce": "219.6", "alltoall": "190.9",
                                 "allreduce-nonvlink": "46.1", "alltoall-nonvlink": "NOT_RUN"}}},
    ))

    facts = hr.collect_node_facts(aid)
    assert facts["nodes"]["gpu1-su20"]["bringup"]["alltoall-nonvlink"] == "NOT_RUN"
    # A node bring-up never tested has no cells, rather than a row of blanks.
    assert facts["nodes"]["gpu2-su20"] == {"bringup": {}}

    monkeypatch.setattr(hr.native_status, "placed_node_facts",
                        lambda hosts: {"gpu1-su20": {"rack": "U2", "ip": "10.0.0.1"}})
    d = hr.run_detail(aid)
    assert started == []  # kept: not collected again
    assert d["node_facts"]["state"] == "ready"
    assert d["nodes"] == 32  # the count survives beside the rows
    assert [n["host"] for n in d["node_rows"]] == ["gpu1-su20", "gpu2-su20"]
    assert d["node_rows"][0] == {"host": "gpu1-su20", "rack": "U2", "ip": "10.0.0.1",
                                 "bringup": facts["nodes"]["gpu1-su20"]["bringup"]}


def test_a_finished_run_without_facts_starts_collecting_them_and_a_running_one_waits():
    aid = _nodes_run(["gpu1-su20"])
    d = hr.run_detail(aid)
    assert d["node_facts"]["state"] == "collecting" and started == [aid]
    assert d["node_rows"][0]["bringup"] == {}

    started.clear()
    running = _run("llmb-nccl", NCCL_LOG, done=False, nodes=["gpu1-su20"])
    assert hr.run_detail(running)["node_facts"]["state"] == "not_collected" and started == []


def test_bringup_outage_costs_its_columns_not_the_facts(monkeypatch):
    import bringup

    monkeypatch.setattr(bringup, "is_enabled", lambda: True)

    def _boom():
        raise RuntimeError("report_benchmarks.sh timed out")

    monkeypatch.setattr(bringup, "run_daily_report", _boom)
    metrics, error = hr._bringup_metrics(["gpu1-su20"])
    assert metrics == {} and "timed out" in error


def test_the_pdf_draws_the_band_charts_nodes_and_commands():
    import handover_report_pdf as p

    if not p.available():
        pytest.skip("reportlab not installed")
    from reportlab.lib import colors

    curves = {"alltoall": [{"size_bytes": s * GIB, "busbw_gbps": 80.0 + s} for s in (1, 2, 4, 8, 16)]}
    drawing = p._band_chart(curves, "alltoall", 170, colors)
    plotted = [x for x, _ in drawing.contents[0].data[0]]
    assert plotted == [31.0, 32.0, 33.0, 34.0]  # 2 GB to 16 GB only
    assert p._band_chart(curves, "all_gather", 170, colors) is None

    block = p._command_block({
        "collective": "alltoall", "source": "stated", "env": {"UCX_TLS": ""}, "ld_library_path": "",
        "command": "mpirun -np 8 --mca plm_rsh_agent 'ssh -o StrictHostKeyChecking=no -o BatchMode=yes' "
                   + " ".join(f"-x VAR_{i}" for i in range(20)) + " alltoall_perf -b 2G -e 16G",
    })
    lines = block.splitlines()
    assert lines[:2] == ["# All-to-all (stated)", "export UCX_TLS=<not recorded>"]
    assert all(len(line) <= 94 for line in lines), block
    # The quoted agent is never broken across a continuation.
    assert any("'ssh -o StrictHostKeyChecking=no -o BatchMode=yes'" in line for line in lines)

    assert p._short_nodelist("./run.sh --nodelist a,b,c U2") == "./run.sh --nodelist <3 nodes, see Nodes> U2"
    assert p.PRODUCT == "NVIS Rack Status"


def test_the_pdf_renders_a_run_with_nodes_and_commands(monkeypatch):
    import handover_report_pdf as p

    if not p.available():
        pytest.skip("reportlab not installed")
    scan = {**NCCL_SCAN, "statements": [*NCCL_SCAN["statements"], *STATED_COMMAND_LINES[1:]]}
    monkeypatch.setattr(hr, "_logscan_record", lambda path: scan)
    aid = _nodes_run([f"gpu{i}-su20" for i in range(1, 41)])
    va.update_activity(aid, node_facts={"version": hr.NODE_FACTS_VERSION, "collected_at": "2026-10-24T22:00:00+00:00",
                                        "nodes": {}, "bringup_error": ""})
    ds = hr.report_dataset([aid])
    assert len(ds["runs"][0]["node_rows"]) == 40
    # Every collective of a current job states its command; this log mixes in an older header.
    assert {c["collective"]: c["source"] for c in ds["runs"][0]["nccl_commands"]} == {
        "all_reduce": "reconstructed", "alltoall": "stated"}
    assert p.to_pdf(ds).startswith(b"%PDF")


def test_node_facts_can_be_collected_again_for_a_finished_run():
    aid = _nodes_run(["gpu1-su20"])
    assert hr.recollect_node_facts(aid) == "collecting" and started == [aid]
    running = _run("llmb-nccl", NCCL_LOG, done=False, nodes=["gpu1-su20"])
    assert hr.recollect_node_facts(running) == "running"
    assert hr.recollect_node_facts(_run("llmb-nccl", NCCL_LOG)) == "none"
    assert hr.recollect_node_facts("gone") is None
    assert started == [aid]


def test_node_facts_route_starts_a_collection_and_refuses_what_it_cannot():
    c = _client()
    aid = _nodes_run(["gpu1-su20"])
    r = c.post(f"/api/handover-reports/runs/{aid}/node-facts")
    if r.status_code in (401, 403):
        pytest.skip("route requires a session in this app configuration")
    assert r.status_code == 202 and r.get_json() == {"ok": True, "state": "collecting"}
    running = _run("llmb-nccl", NCCL_LOG, done=False, nodes=["gpu1-su20"])
    assert c.post(f"/api/handover-reports/runs/{running}/node-facts").status_code == 409
    assert c.post("/api/handover-reports/runs/gone/node-facts").status_code == 404


# --- all-to-all against its ceiling ----------------------------------------------------------------


def _rows(per_rack: dict[str, int], nic: dict[str, str] | None = None) -> list[dict]:
    rows = []
    for rack, n in per_rack.items():
        for i in range(n):
            host = f"gpu{i}-{rack}"
            rate = (nic or {}).get(host, "95.5")
            rows.append({"host": host, "rack": rack, "ip": "", "bringup": {"alltoall-nonvlink": rate}})
    return rows


def _a2a_run(gpus: int, nodes: int, at_2g: float = 81.1, peak: float = 80.2) -> dict:
    return {"gpus": gpus, "nodes": nodes, "run_type": "nccl",
            "collectives": {"alltoall": {"busbw_2g_gbps": at_2g, "busbw_peak_gbps": peak, "max_size_bytes": 16 * GIB}}}


def test_the_ceiling_is_the_off_rack_share_through_the_measured_nic():
    # 512 GPUs, 8 racks of 16 nodes x 4 GPUs: 448 of every GPU's 511 peers are off its rack.
    rows = _rows({f"U{i}": 16 for i in range(1, 9)}, {"gpu3-U2": "83.9", "gpu0-U1": "NOT_RUN"})
    c = hr.alltoall_ceiling(_a2a_run(512, 128), rows, {"U1": "SU20", "U2": "SU20", "U8": "SU23"})
    assert c["nic_gbps"] == 95.5 and c["nic_nodes"] == 127  # the NOT_RUN node is not a measurement
    assert (c["nic_min_gbps"], c["nic_min_host"]) == (83.9, "gpu3-U2")
    assert c["gpus_per_rack"] == 64
    assert c["ceiling_gbps"] == round(95.5 * 511 / 448, 1) == 108.9
    assert (c["pct_2g"], c["pct_peak"]) == (round(100 * 81.1 / (95.5 * 511 / 448), 1), round(100 * 80.2 / (95.5 * 511 / 448), 1))
    assert c["su_racks"] == {"SU20": 2, "SU23": 1}


def test_the_ceiling_falls_as_the_run_grows():
    two = hr.alltoall_ceiling(_a2a_run(128, 32), _rows({"A": 16, "B": 16}), {})
    sixteen = hr.alltoall_ceiling(_a2a_run(1024, 256), _rows({f"R{i}": 16 for i in range(16)}), {})
    assert two["ceiling_gbps"] == 189.5 and sixteen["ceiling_gbps"] == 101.8


def test_the_smallest_rack_bounds_the_ceiling():
    # Its GPUs send the largest share off-rack, so they finish last.
    c = hr.alltoall_ceiling(_a2a_run(120, 30), _rows({"A": 16, "B": 14}), {})
    assert c["gpus_per_rack"] == 56 and c["ceiling_gbps"] == round(95.5 * 119 / 64, 1)


def test_no_ceiling_without_a_nic_measurement_or_off_rack_traffic():
    assert hr.alltoall_ceiling(_a2a_run(128, 32), _rows({"A": 16, "B": 16}, {f"gpu{i}-{r}": "NOT_RUN"
                               for r in "AB" for i in range(16)}), {}) is None
    assert hr.alltoall_ceiling(_a2a_run(64, 16), _rows({"A": 16}), {}) is None
    assert hr.alltoall_ceiling({"gpus": 128, "nodes": 32, "collectives": {}}, _rows({"A": 16, "B": 16}), {}) is None


def test_the_detail_and_the_pdf_carry_the_ceiling(monkeypatch):
    import handover_report_pdf as p

    aid = _nodes_run([f"gpu{i}-su20" for i in range(8)])
    monkeypatch.setattr(hr.native_status, "placed_node_facts",
                        lambda hosts: {h: {"rack": "U2" if int(h[3]) < 4 else "U3", "ip": ""} for h in hosts})
    va.update_activity(aid, node_facts={"version": hr.NODE_FACTS_VERSION, "collected_at": "t", "bringup_error": "",
                                        "nodes": {f"gpu{i}-su20": {"bringup": {"alltoall-nonvlink": "95.5"}}
                                                  for i in range(8)}})
    ds = hr.report_dataset([aid])
    c = ds["runs"][0]["alltoall_ceiling"]
    # 32 nodes x 4 GPUs per the scan; the roster puts 4 of its nodes in each rack.
    assert c["gpus_per_rack"] == 16 and c["ceiling_gbps"] == round(95.5 * 127 / 112, 1)
    if p.available():
        assert p.to_pdf(ds).startswith(b"%PDF")
        assert p._ceiling_pairs(c, 128)[0][1] == f"{c['ceiling_gbps']} GB/s = 95.5 x (128 - 1) / (128 - 16)"


def test_long_exports_wrap_so_the_shell_rejoins_them_exactly():
    import subprocess

    import handover_report_pdf as p

    ld = ":".join(f"/home/cmods/workspace/component-{i}/build/lib" for i in range(6))
    plugin = "/home/cmods/workspace/hpcx-v2.25.1-gcc-doca_ofed-ubuntu24.04-cuda13-aarch64/nccl_spectrum-x_plugin/lib/libnccl-net-spcx.so"
    block = p._command_block({"collective": "all_reduce", "source": "stated", "ld_library_path": ld,
                              "env": {"NCCL_NET_PLUGIN": plugin, "UCX_TLS": "\\^tcp"}, "command": "true"})
    assert all(len(line) <= 97 for line in block.splitlines()), block
    script = block + '\nprintf "%s\\n%s\\n%s\\n" "$LD_LIBRARY_PATH" "$NCCL_NET_PLUGIN" "$UCX_TLS"'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.splitlines()
    assert out == [ld, plugin, "^tcp"]


def test_an_llm_jobs_nccl_preflight_is_not_held_to_the_ceiling():
    """A NeMo job sweeps NCCL with the training settings first; that is not the acceptance test."""
    rows = _rows({f"U{i}": 16 for i in range(1, 9)})
    nccl = hr.alltoall_ceiling({**_a2a_run(512, 128), "run_type": "nccl"}, rows, {})
    assert nccl is not None
    assert hr.alltoall_ceiling({**_a2a_run(512, 128), "run_type": "both"}, rows, {}) is None


def test_the_summary_leaves_an_llm_jobs_preflight_out_of_the_nccl_columns():
    import handover_report_pdf as p

    if not p.available():
        pytest.skip("reportlab not installed")
    assert p.RUN_TYPES["both"] == "LLM" and "preflight" in p.PREFLIGHT_NOTE


# --- the floor plan --------------------------------------------------------------------------------

UNITS = [{"id": "su20", "label": "SU20", "racks": ["U3", "U2", "U10"]},
         {"id": "su23", "label": "SU23", "racks": ["V19"]},
         {"id": "su24", "label": "SU24", "racks": ["W1"]}]
PLACED = {"U2": ["gpu2-su20", "gpu1-su20"], "U3": ["gpu3-su20"], "U10": [], "V19": ["gpu9-su23"], "W1": ["gpu1-su24"]}


def test_the_floor_plan_draws_every_unit_the_run_touched_whole(monkeypatch):
    monkeypatch.setattr(hr.native_status, "placed_rack_members",
                        lambda rack: sorted(PLACED.get(rack, []), key=hr.natural_key))
    plan = hr.floor_plan(["U2", "V19"], ["gpu1-su20", "GPU9-SU23"], UNITS)
    assert [u["su"] for u in plan] == ["SU20", "SU23"]  # SU24 holds none of the run's racks
    su20 = plan[0]["racks"]
    assert [r["rack"] for r in su20] == ["U2", "U3", "U10"]  # floor order, naturally sorted
    assert [r["in_run"] for r in su20] == [True, False, False]
    assert su20[0]["nodes"] == [{"host": "gpu1-su20", "used": True}, {"host": "gpu2-su20", "used": False}]
    assert su20[1]["nodes"] == [{"host": "gpu3-su20", "used": False}]
    assert su20[2]["nodes"] == []  # a rack with nothing placed draws empty
    assert plan[1]["racks"][0]["nodes"] == [{"host": "gpu9-su23", "used": True}]


def test_no_floor_plan_without_scalable_units_or_inventory(monkeypatch):
    monkeypatch.setattr(hr.native_status, "placed_rack_members", lambda rack: None)
    assert hr.floor_plan(["U2"], ["gpu1-su20"], []) == []
    assert hr.floor_plan(["U2"], ["gpu1-su20"], UNITS)[0]["racks"][0]["nodes"] == []


def test_the_pdf_draws_the_floor_plan_in_the_nodes_section(monkeypatch):
    import handover_report_pdf as p

    if not p.available():
        pytest.skip("reportlab not installed")
    from reportlab.lib import colors

    monkeypatch.setattr(hr.native_status, "placed_rack_members",
                        lambda rack: sorted(PLACED.get(rack, []), key=hr.natural_key))
    plan = hr.floor_plan(["U2", "V19"], ["gpu1-su20", "gpu9-su23"], UNITS)
    drawings = p._floor_plan(plan[0], 468, colors)
    fills = [getattr(shape, "fillColor", None) for d in drawings for shape in d.contents]
    assert fills.count(colors.HexColor(p.FLOOR_USED)) == 1 and fills.count(colors.HexColor(p.FLOOR_IDLE)) == 2
    many = {"su": "SU1", "racks": [{"rack": f"A{i}", "in_run": False, "nodes": []} for i in range(10)]}
    assert len(p._floor_plan(many, 468, colors)) == 2  # ten racks wrap onto a second line
    aid = _nodes_run(["gpu1-su20"])
    monkeypatch.setattr(hr, "site_context", lambda: {"project": "P", "cluster": "C", "platform": "", "gpu_model": "",
                                                    "rack_su": {"U8": "SU20"}, "units": [{"id": "su20", "label": "SU20",
                                                                                         "racks": ["U8", "U2"]}]})
    ds = hr.report_dataset([aid])
    assert ds["runs"][0]["floor_plan"][0]["su"] == "SU20"
    assert "units" not in ds["runs"][0]["site"] and "units" not in ds["site"]
    assert p.to_pdf(ds).startswith(b"%PDF")


# --- the run's own times -----------------------------------------------------------------------------


def test_a_finished_runs_times_are_its_jobs_filled_in_on_first_read(monkeypatch):
    aid = _run("llmb-nccl", NCCL_LOG)
    filled = []

    def record(activity_id):
        filled.append(activity_id)
        va.add_or_update_task(activity_id, ordinal=1, label="validation", task_id="t1",
                              started_at="2026-10-26T14:02:44+00:00", ended_at="2026-10-26T14:05:55+00:00")
        return True

    monkeypatch.setattr(hr, "record_job_times", record)
    d = hr.run_detail(aid)
    assert filled == [aid]
    assert (d["job_started_at"], d["job_ended_at"]) == ("2026-10-26T14:02:44+00:00", "2026-10-26T14:05:55+00:00")
    hr.run_detail(aid)
    assert filled == [aid]  # recorded once, not asked again


def test_the_pdf_dates_a_run_by_its_job(monkeypatch):
    import handover_report_pdf as p

    if not p.available():
        pytest.skip("reportlab not installed")
    monkeypatch.setattr(hr, "record_job_times", lambda aid: False)
    aid = _run("llmb-nccl", NCCL_LOG)
    va.add_or_update_task(aid, ordinal=1, label="validation", task_id="t1",
                          started_at="2026-10-26T14:02:44+00:00", ended_at="2026-10-26T14:05:55+00:00")
    ds = hr.report_dataset([aid])
    assert ds["runs"][0]["job_ended_at"] == "2026-10-26T14:05:55+00:00"
    assert p.to_pdf(ds).startswith(b"%PDF")
