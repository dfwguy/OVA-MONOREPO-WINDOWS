# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The MPI daemons of a multi-node NCCL run log in as the job's user, whatever its ssh config says.

nccl_allreduce.sbatch launches orted over ssh. On Nscale NC (job 136390, 270 nodes) the submitter's
NFS-shared ~/.ssh/config carried a P2P block -- ``Host sys1-*-su*`` / ``User nvis-p2p`` / a service
IdentityFile -- so every daemon tried to log in as the service account and was refused. The agent now
ignores that file; ``NVIS_MPI_RSH_AGENT`` still overrides it.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

SBATCH = Path(__file__).resolve().parents[2] / "bin" / "scripts" / "nccl_allreduce.sbatch"
NC_P2P_BLOCK = "Host sys1-*-su*\n  User nvis-p2p\n  IdentityFile ~/.ssh/id_nvis_p2p_node\n"


def _default_agent() -> list[str]:
    m = re.search(r'^RSH_AGENT="\$\{NVIS_MPI_RSH_AGENT:-([^}]*)\}"$', SBATCH.read_text(), re.MULTILINE)
    assert m, "nccl_allreduce.sbatch must define RSH_AGENT with an NVIS_MPI_RSH_AGENT override"
    return shlex.split(m.group(1))


def test_mpirun_uses_the_agent_and_the_agent_skips_the_user_config():
    text = SBATCH.read_text()
    assert '--mca plm_rsh_agent "${RSH_AGENT}"' in text
    agent = _default_agent()
    assert agent[0] == "ssh"
    assert agent[agent.index("-F") + 1] == "/dev/null"
    assert "BatchMode=yes" in agent


@pytest.mark.skipif(shutil.which("ssh") is None, reason="needs an ssh client to resolve the config")
def test_a_remapping_user_config_does_not_reach_the_daemon_login(tmp_path):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "config").write_text(NC_P2P_BLOCK)
    env = {**os.environ, "HOME": str(home)}
    me = subprocess.run(["id", "-un"], capture_output=True, text=True, check=True).stdout.strip()

    def resolved(cmd: list[str]) -> dict[str, list[str]]:
        out = subprocess.run([*cmd, "-G", "sys1-gso1-p-phy-gpu1-su19"], capture_output=True, text=True,
                             env=env, check=True).stdout
        conf: dict[str, list[str]] = {}
        for line in out.splitlines():
            key, _, value = line.partition(" ")
            conf.setdefault(key, []).append(value)
        return conf

    # Plain ssh, the old agent: the P2P block wins and the daemon logs in as the service account.
    assert resolved(["ssh", "-F", str(home / ".ssh" / "config")])["user"] == ["nvis-p2p"]
    # The agent the sbatch now uses: the job's own user, and no service key forced on it.
    conf = resolved(_default_agent())
    assert conf["user"] == [me]
    assert not any("id_nvis_p2p_node" in f for f in conf.get("identityfile", []))


def _bash4() -> str | None:
    """A bash new enough for the sbatch (``${c^^}``, ``printf -v``); macOS's /bin/bash is 3.2."""
    for cand in (shutil.which("bash"), "/opt/homebrew/bin/bash", "/usr/local/bin/bash"):
        if cand and Path(cand).exists():
            out = subprocess.run([cand, "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True, check=False)
            if out.stdout.strip().isdigit() and int(out.stdout.strip()) >= 4:
                return cand
    return None


def _run_collective_source() -> str:
    text = SBATCH.read_text()
    start = text.index("_run_collective() {")
    end = text.index("\n}\n", start) + 3
    return text[start:end]


@pytest.mark.skipif(_bash4() is None, reason="needs bash >= 4, as the compute nodes have")
def test_each_collective_states_its_exact_command_and_forwarded_values(tmp_path):
    """A handover hands the program to people outside Rack Status: the job states it as it ran."""
    stub = tmp_path / "mpirun"
    stub.write_text("#!/bin/sh\necho STUB-RAN\n")
    stub.chmod(0o755)
    script = "\n".join([
        "set -u",
        f"export PATH={tmp_path}:$PATH",
        "NP=8 HF=/tmp/nccl_hf.XYZ GPUS_PER_NODE=4 RSH_AGENT='ssh -F /dev/null'",
        "NS_IF=enP22s22f0np0 NCCL_IB_HCA=roce_vf_r SIZE_MIN=8 SIZE_MAX=16G TEST_TIMEOUT=120",
        "export LD_LIBRARY_PATH=/ws/nccl/lib NCCL_NET=IB UCX_TLS=tcp",
        "EXTRA_X=(-x NCCL_NET -x UCX_TLS) _seen=' NCCL_SOCKET_IFNAME NCCL_IB_HCA NCCL_DEBUG NCCL_NET UCX_TLS '",
        "declare -A COLL_BIN=([alltoall]=/ws/nccl-tests/build/alltoall_perf)",
        "NVIS_NCCL_ENV_ALLTOALL='export NCCL_IB_QPS_PER_CONNECTION=4; export NCCL_BUFFSIZE=8388608'",
        "NVIS_NCCL_ENV_ALLTOALL_KEYS='NCCL_BUFFSIZE NCCL_IB_QPS_PER_CONNECTION'",
        _run_collective_source(),
        "_run_collective alltoall",
    ])
    out = subprocess.run([_bash4(), "-c", script], capture_output=True, text=True, check=True).stdout
    prefix = "nccl_allreduce: alltoall: "
    lines = dict(ln[len(prefix):].partition(": ")[::2] for ln in out.splitlines() if ln.startswith(prefix))
    command = lines["command"]
    assert command.startswith("mpirun -np 8 --hostfile hosts --map-by ppr:4:node")
    assert "/tmp/nccl_hf" not in command
    assert command.endswith("/ws/nccl-tests/build/alltoall_perf -b 8 -e 16G -f 2 -g 1 -T 120")
    assert "-x NCCL_BUFFSIZE" in command and "-x NCCL_IB_QPS_PER_CONNECTION" in command
    env = dict(kv.split("=", 1) for kv in lines["env"].split())
    assert env == {"NCCL_NET": "IB", "UCX_TLS": "tcp", "NCCL_BUFFSIZE": "8388608", "NCCL_IB_QPS_PER_CONNECTION": "4"}
    assert "nccl_allreduce: alltoall: LD_LIBRARY_PATH=/ws/nccl/lib" in out
    assert "STUB-RAN" in out
