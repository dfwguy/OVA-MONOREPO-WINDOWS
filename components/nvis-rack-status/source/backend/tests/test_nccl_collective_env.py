# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""NCCL tuning per collective: the record, the launch, and the job that applies it.

Nscale NC, 2026-10-21/22: the alltoall best (QP4, split data on QPs, adaptive routing, 8 MB buffers)
put in the cluster's multi-rack nccl_env made multi-rack NeMo ~1% slower, so it was rolled back; and
Rack Status's multi-rack NCCL test ran all_reduce only, so there was nothing it could tune. Now the
direct NCCL test runs a list of collectives, and nccl_env.collectives.<name>.<span> reaches only that
collective's run -- not the allreduce run beside it, not NeMo.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import validation_launch

os.environ["RACK_STATUS_DEMO"] = "1"
os.environ["RACK_EXEC_MODE"] = "local"

import pytest
from api import validation_runs
from app import app
from catalog import models

SCRIPTS = Path(__file__).resolve().parents[2] / "bin" / "scripts"
SBATCH = (SCRIPTS / "nccl_allreduce.sbatch").read_text()
A2A = {"NCCL_IB_QPS_PER_CONNECTION": "4", "NCCL_IB_SPLIT_DATA_ON_QPS": "1", "NCCL_BUFFSIZE": "8388608"}
SPAN = {"NCCL_BUFFSIZE": "1048576", "NCCL_IB_QPS_PER_CONNECTION": "1", "NCCL_NET": "SPCX"}


def _cluster(nccl_env):
    return models.Cluster.from_dict({"id": "c1", "name": "C1", "nccl_env": nccl_env})


@pytest.fixture
def active(monkeypatch):
    def _set(nccl_env):
        cluster = _cluster(nccl_env)
        monkeypatch.setattr(validation_runs.catalog_context, "resolve", lambda: (None, cluster, None))
    return _set


# --- the record ----------------------------------------------------------------------------------


class TestTheRecord:
    def test_a_collective_list_round_trips_beside_the_span_lists(self):
        c = _cluster({"multirack": SPAN, "collectives": {"alltoall": {"multirack": A2A}}})
        assert not c.validate()
        d = c.to_dict()["nccl_env"]
        assert d["multirack"] == SPAN
        assert d["collectives"] == {"alltoall": {"node": {}, "rack": {}, "multirack": A2A}}
        assert c.nccl_env.for_collective("alltoall", "multirack") == A2A
        assert c.nccl_env.for_collective("alltoall", "rack") == {}
        assert c.nccl_env.for_collective("all_reduce", "multirack") == {}

    def test_a_collective_with_nothing_stated_is_not_kept(self):
        assert _cluster({"collectives": {"alltoall": {"multirack": {}}}}).nccl_env.collectives == {}

    def test_an_unknown_collective_is_refused(self):
        problems = _cluster({"collectives": {"all2all": {"multirack": A2A}}}).validate()
        assert any("unknown collective 'all2all'" in p for p in problems)

    def test_a_bad_variable_names_its_collective_and_span(self):
        problems = _cluster({"collectives": {"alltoall": {"multirack": {"BAD NAME": "1"}}}}).validate()
        assert any(p.startswith("nccl_env.collectives.alltoall.multirack") for p in problems)

    def test_the_vocab_lists_the_collectives(self):
        app.config["TESTING"] = True
        with app.test_client() as c:
            assert c.get("/api/catalog/vocab").get_json()["nccl_collectives"] == list(models.NCCL_COLLECTIVES)


# --- the launch ----------------------------------------------------------------------------------


class TestChoosingCollectives:
    @pytest.mark.parametrize(("raw", "want"), [
        (None, ["all_reduce"]), ([], ["all_reduce"]), ("", ["all_reduce"]),
        (["alltoall", "all_reduce"], ["alltoall", "all_reduce"]),
        ("all_reduce,alltoall,all_reduce", ["all_reduce", "alltoall"]),
        ("all_reduce alltoall", ["all_reduce", "alltoall"]),
    ])
    def test_the_list_is_the_bodys_else_the_default(self, raw, want):
        body = {} if raw is None else {"collectives": raw}
        assert validation_runs._nccl_collectives_from_body(body, "all_reduce") == want

    def test_the_default_is_used_when_the_body_names_none(self):
        assert validation_runs._nccl_collectives_from_body({}, "all_reduce,alltoall") == ["all_reduce", "alltoall"]

    def test_an_unknown_collective_is_refused(self):
        with app.app_context():
            out = validation_runs._nccl_collectives_from_body({"collectives": ["alltoall", "bcast"]}, "all_reduce")
        assert isinstance(out, tuple) and out[1] == 400
        assert "bcast" in out[0].get_json()["error"]


class TestTheCollectiveEnv:
    def test_only_the_named_collectives_list_for_the_span_is_sent(self, active):
        active({"multirack": SPAN, "collectives": {"alltoall": {"multirack": A2A, "rack": {"X": "1"}},
                                                   "all_gather": {"multirack": {"Y": "1"}}}})
        out = validation_runs._nccl_collective_env(["all_reduce", "alltoall"], {}, scope="multirack")
        assert set(out) == {"NVIS_NCCL_ENV_ALLTOALL", "NVIS_NCCL_ENV_ALLTOALL_KEYS"}
        assert out["NVIS_NCCL_ENV_ALLTOALL_KEYS"] == " ".join(sorted(A2A))

    def test_the_code_reproduces_each_value_exactly(self, active):
        odd = {"NCCL_IB_HCA": "=roce_vf_r1,roce_vf_r2", "X": "a b 'c' $(id)"}
        active({"collectives": {"alltoall": {"multirack": odd}}})
        code = validation_runs._nccl_collective_env(["alltoall"], {}, scope="multirack")["NVIS_NCCL_ENV_ALLTOALL"]
        r = subprocess.run(["bash", "-c", code + '; printf "%s\\n%s\\n" "$NCCL_IB_HCA" "$X"'],
                           capture_output=True, text=True, check=True)
        assert r.stdout.splitlines() == [odd["NCCL_IB_HCA"], odd["X"]]

    def test_a_key_the_dialog_set_is_left_to_the_dialog(self, active):
        active({"collectives": {"alltoall": {"multirack": A2A}}})
        out = validation_runs._nccl_collective_env(
            ["alltoall"], {"env": {"NCCL_BUFFSIZE": "2097152"}}, scope="multirack")
        assert "NCCL_BUFFSIZE" not in out["NVIS_NCCL_ENV_ALLTOALL_KEYS"].split()
        assert "NCCL_BUFFSIZE" not in out["NVIS_NCCL_ENV_ALLTOALL"]

    def test_no_catalog_means_no_collective_env(self, monkeypatch):
        def _boom():
            raise OSError("unreadable")
        monkeypatch.setattr(validation_runs.catalog_context, "resolve", _boom)
        assert validation_runs._nccl_collective_env(["alltoall"], {}, scope="multirack") == {}


class TestTheMultirackNcclTest:
    @pytest.fixture
    def prepare(self, monkeypatch, tmp_path, active):
        hosts = [f"sys1-gso1-p-phy-gpu{i}-su20" for i in (1, 2)] + [f"sys1-gso1-p-phy-gpu{i}-su22" for i in (55, 56)]
        monkeypatch.setattr(validation_runs, "_resolve_log_dir", lambda _raw=None: tmp_path)
        monkeypatch.setattr(validation_runs, "_script_exists", lambda _p: True)
        monkeypatch.setattr(validation_launch, "_multirack_campaign_snapshot", dict)
        monkeypatch.setattr(validation_runs, "_placed_rack_nodes", lambda _racks: (hosts, None))
        monkeypatch.delenv("RACK_LLMB_NCCL_USE_CONTAINER", raising=False)
        active({"multirack": SPAN, "collectives": {"alltoall": {"multirack": A2A}}})

        def _run(body, setting=""):
            monkeypatch.setattr(validation_runs, "_eget",
                                lambda k, d="": setting if k == "RACK_NCCL_XRACK_COLLECTIVES" else d)
            with app.app_context():
                return validation_runs._prepare_run_llmb_nccl({"racks": ["p5-r01", "p5-r02"], **body})
        return _run

    def test_the_job_runs_the_chosen_collectives_each_with_its_own_settings(self, prepare):
        prep, err = prepare({"collectives": ["all_reduce", "alltoall"]})
        assert err is None, err and err[0].get_json()
        cmd = prep["cmd"]
        assert cmd[cmd.index("--collectives") + 1] == "all_reduce,alltoall"
        assert "--collectives all_reduce,alltoall" in prep["display_cmd"]
        env = prep["env_updates"]
        assert env["NCCL_BUFFSIZE"] == "1048576"  # the whole job keeps the span list
        assert env["NVIS_NCCL_ENV_ALLTOALL_KEYS"] == " ".join(sorted(A2A))
        assert "NVIS_NCCL_ENV_ALL_REDUCE" not in env

    def test_the_setting_is_the_default_and_all_reduce_its_fallback(self, prepare):
        prep, _ = prepare({}, setting="all_reduce,alltoall")
        assert prep["cmd"][prep["cmd"].index("--collectives") + 1] == "all_reduce,alltoall"
        prep, _ = prepare({})
        assert prep["cmd"][prep["cmd"].index("--collectives") + 1] == "all_reduce"
        assert not any(k.startswith("NVIS_NCCL_ENV_") for k in prep["env_updates"])

    def test_an_unknown_collective_refuses_the_launch(self, prepare):
        _prep, err = prepare({"collectives": ["alltoall", "bcast"]})
        assert err is not None and err[1] == 400

    def test_nemo_gets_the_span_list_but_never_a_collectives(self, active, monkeypatch, tmp_path):
        active({"multirack": SPAN, "collectives": {"alltoall": {"multirack": A2A}}})
        monkeypatch.setattr(validation_runs, "_resolve_log_dir", lambda _raw=None: tmp_path)
        monkeypatch.setattr(validation_runs, "_script_exists", lambda _p: True)
        monkeypatch.setattr(validation_runs, "_placed_rack_nodes", lambda _r: (["h1-su20", "h2-su22"], None))
        prep, err = validation_runs._prepare_run_nemo_xrack({"racks": ["p5-r01", "p5-r02"]})
        assert err is None and prep is not None
        assert prep["env_updates"]["NCCL_BUFFSIZE"] == "1048576"
        assert not any(k.startswith("NVIS_NCCL_ENV_") for k in prep["env_updates"])


def test_the_setting_is_editable_on_the_settings_page():
    import config_env

    entry = next(e for e in config_env.JOB_ENV_UI_DEFINITIONS if e["key"] == "RACK_NCCL_XRACK_COLLECTIVES")
    assert entry["section"] == "jobs_cluster" and "alltoall" in entry["description"]


# --- the job -------------------------------------------------------------------------------------


def _section(start: str, end: str) -> str:
    i = SBATCH.index(start)
    j = SBATCH.index(end, i)
    return SBATCH[SBATCH.rindex("\n", 0, i) + 1:SBATCH.index("\n", j) + 1]


@pytest.fixture
def job(tmp_path):
    """Run nccl_allreduce.sbatch's collective selection and run loop, mpirun stubbed to report."""
    bindir = tmp_path / "tests"
    bindir.mkdir()
    for name in ("all_reduce", "alltoall", "all_gather"):
        (bindir / f"{name}_perf").write_text("#!/bin/bash\n")
        (bindir / f"{name}_perf").chmod(0o755)
    fake = tmp_path / "bin"
    fake.mkdir()
    # Report each run: the binary, the forwarded names and the NCCL values this process sees.
    (fake / "mpirun").write_text(
        '#!/bin/bash\nfwd=""; bin=""; while [ $# -gt 0 ]; do\n'
        '  [ "$1" = -x ] && fwd="$fwd ${2%%=*}"; case "$1" in *_perf) bin=$(basename "$1") ;; esac; shift\n'
        'done\n'
        'echo "RUN $bin fwd=[$fwd ] Q=${NCCL_IB_QPS_PER_CONNECTION-} B=${NCCL_BUFFSIZE-} '
        'S=${NCCL_IB_SPLIT_DATA_ON_QPS-unset}"\n')
    (fake / "mpirun").chmod(0o755)
    body = (_section("# --- Collectives", "MARK_COLLECTIVES=1; fi")
            + "EXTRA_X=( -x NCCL_BUFFSIZE -x NCCL_IB_QPS_PER_CONNECTION ); "
            + "_seen=' NCCL_SOCKET_IFNAME NCCL_IB_HCA NCCL_DEBUG NCCL_BUFFSIZE NCCL_IB_QPS_PER_CONNECTION '\n"
            + _section("_run_collective() {", 'echo "nccl_allreduce: round ${_round}/${ROUNDS} OK"') + "done\n")

    def _run(env: dict[str, str]):
        full = {"PATH": f"{fake}:{os.environ.get('PATH', '/usr/bin:/bin')}",
                "NCCL_TESTS_BIN": str(bindir / "all_reduce_perf"), "NP": "8", "HF": "/dev/null",
                "GPUS_PER_NODE": "4", "RSH_AGENT": "ssh", "NS_IF": "eth0", "SIZE_MIN": "8", "SIZE_MAX": "1G",
                "TEST_TIMEOUT": "120", "ROUNDS": "1",
                "NCCL_BUFFSIZE": "1048576", "NCCL_IB_QPS_PER_CONNECTION": "1", **env}
        return subprocess.run(["bash", "-c", "set -uo pipefail\n" + body], env=full,
                              capture_output=True, text=True, timeout=60, check=False)
    return _run


class TestTheJob:
    def test_each_collective_gets_its_own_settings_and_they_do_not_leak(self, job):
        code = "; ".join(f"export {k}={shlex.quote(v)}" for k, v in sorted(A2A.items()))
        r = job({"NVIS_NCCL_COLLECTIVES": "alltoall all_reduce", "NVIS_NCCL_ENV_ALLTOALL": code,
                 "NVIS_NCCL_ENV_ALLTOALL_KEYS": " ".join(sorted(A2A))})
        runs = [line for line in r.stdout.splitlines() if line.startswith("RUN ")]
        assert runs[0].startswith("RUN alltoall_perf") and "Q=4 B=8388608 S=1" in runs[0], r.stdout + r.stderr
        # Already forwarded by name keeps its one -x; the new key is added for this run only.
        assert " NCCL_IB_SPLIT_DATA_ON_QPS " in runs[0] and runs[0].count("NCCL_BUFFSIZE") == 1
        assert runs[1].startswith("RUN all_reduce_perf") and "Q=1 B=1048576 S=unset" in runs[1]
        assert "NCCL_IB_SPLIT_DATA_ON_QPS" not in runs[1]

    def test_a_job_of_several_collectives_is_bracketed_for_the_parsers(self, job):
        out = job({"NVIS_NCCL_COLLECTIVES": "all_reduce alltoall"}).stdout
        assert "# Collective test starting: all_reduce_perf" in out
        assert out.index("# Collective test concluded: all_reduce_perf") < out.index(
            "# Collective test starting: alltoall_perf")

    def test_a_one_collective_job_keeps_its_old_unmarked_log(self, job):
        r = job({})
        assert "RUN all_reduce_perf" in r.stdout and "Collective test" not in r.stdout

    def test_a_build_that_brackets_its_own_sweeps_gets_no_second_markers(self, job, tmp_path):
        # nccl-tests 2.21.1 (Nscale NC job 219296) prints them itself; two of each was the result.
        (tmp_path / "tests" / "all_reduce_perf").write_text('#!/bin/bash\n# "# Collective test starting: %s"\n')
        out = job({"NVIS_NCCL_COLLECTIVES": "all_reduce alltoall"}).stdout
        assert "Collective test" not in out and out.count("RUN ") == 2

    @pytest.mark.parametrize(("colls", "msg"), [("bcast", "unknown collective 'bcast'"),
                                                ("reduce_scatter", "reduce_scatter_perf not found")])
    def test_a_collective_it_cannot_run_fails_before_mpirun(self, job, colls, msg):
        r = job({"NVIS_NCCL_COLLECTIVES": f"all_reduce {colls}"})
        assert r.returncode == 2 and msg in r.stdout and "RUN " not in r.stdout


class TestTheHostNetPlugin:
    """The cluster's NCCL_NET=SPCX reached the host job with no plugin loaded (NC job 219295)."""

    @pytest.fixture
    def section(self, tmp_path):
        hpcx = tmp_path / "hpcx-v2.25.1-cuda13"
        (hpcx / "nccl_spectrum-x_plugin" / "lib").mkdir(parents=True)
        (hpcx / "nccl_spectrum-x_plugin" / "lib" / "libnccl-net-spcx.so").write_text("")
        body = _section("# --- NCCL network plugin, from the host's own HPC-X", "esac")

        def _run(env):
            return subprocess.run(["bash", "-c", "set -uo pipefail\n" + body + 'echo "P=${NCCL_NET_PLUGIN-unset}"'],
                                  env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HPCX_DIR": str(hpcx), **env},
                                  capture_output=True, text=True, timeout=30, check=False)
        return _run, hpcx

    def test_the_clusters_plugin_is_found_under_the_host_hpcx(self, section):
        run, hpcx = section
        r = run({"NVIS_FABRIC_NET_PLUGIN": "/opt/hpcx/nccl_spectrum-x_plugin/lib/libnccl-net-spcx.so",
                 "NCCL_NET": "SPCX"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"P={hpcx}/nccl_spectrum-x_plugin/lib/libnccl-net-spcx.so" in r.stdout

    def test_a_stated_plugin_wins(self, section):
        run, _ = section
        r = run({"NVIS_FABRIC_NET_PLUGIN": "/opt/hpcx/nccl_spectrum-x_plugin/lib/libnccl-net-spcx.so",
                 "NCCL_NET_PLUGIN": "/x/mine.so"})
        assert "P=/x/mine.so" in r.stdout

    def test_a_named_net_with_no_plugin_fails_before_mpirun_saying_what_to_set(self, section):
        run, _ = section
        r = run({"NCCL_NET": "SPCX"})
        assert r.returncode == 2 and "fabric.net_plugin" in r.stdout

    @pytest.mark.parametrize("net", ["", "IB", "Socket"])
    def test_the_built_in_nets_need_no_plugin(self, section, net):
        run, _ = section
        r = run({"NCCL_NET": net} if net else {})
        assert r.returncode == 0 and "P=unset" in r.stdout
