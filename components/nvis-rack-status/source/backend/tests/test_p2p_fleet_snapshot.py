# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The fleet-snapshot producer: which SU a node is filed under, and the document it writes.

The SU is the cluster manager's placement, read from the BCM-derived topology; the hostname's
``-suN`` is only the fallback for a node the topology does not list. Nothing here fans out: the
receipt audit and the object-store probe are replaced, so the cases run anywhere.

Author: Rafael M. Koike
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PRODUCER = Path(__file__).resolve().parents[2] / "deploy" / "p2p" / "scripts" / "fleet-snapshot.py"
_spec = importlib.util.spec_from_file_location("p2p_fleet_snapshot", PRODUCER)
snap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(snap)

IMG = "nvidia+nemo+26.04.01-arm.sqsh"


def _topology(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "topology.tsv"
    path.write_text(text, encoding="utf-8")
    return path


class TestTopology:
    def test_the_su_column_is_read_as_bcm_wrote_it(self, tmp_path):
        path = _topology(tmp_path, "gpu1-su19\t19\tU24\ngpu2\tSU7\tQ5\n")
        assert snap._read_topology(path) == {"gpu1-su19": 19, "gpu2": 7}

    def test_rows_that_do_not_parse_are_skipped_not_fatal(self, tmp_path):
        path = _topology(tmp_path, "\n\tnohost\t1\nshort\nbad\tx\tU1\nok\t3\tU2\n")
        assert snap._read_topology(path) == {"ok": 3}

    def test_no_topology_and_an_unreadable_one_both_mean_hostnames(self, tmp_path, capsys):
        assert snap._read_topology(None) == {}
        assert snap._read_topology(tmp_path / "absent.tsv") == {}
        assert "SUs from hostnames" in capsys.readouterr().err


class TestCoverageSu:
    def test_the_topology_wins_over_the_hostname(self):
        # A node renamed or reused across SUs: BCM's placement is the answer, not the name.
        cov = snap._coverage(["gpu5-su3"], [IMG], {"gpu5-su3": {IMG}}, {"gpu5-su3": 21})
        assert cov["nodes"][0]["su"] == 21
        assert [b["su"] for b in cov["by_su"]] == [21]

    def test_a_node_the_topology_misses_falls_back_to_its_hostname(self):
        cov = snap._coverage(["gpu1-su4", "lonely"], [IMG], {}, {"other": 9})
        assert {n["node"]: n["su"] for n in cov["nodes"]} == {"gpu1-su4": 4, "lonely": 0}

    def test_a_hostname_with_no_su_is_placed_by_the_topology(self):
        cov = snap._coverage(["dgx-07"], [IMG], {"dgx-07": {IMG}}, {"dgx-07": 2})
        node = cov["nodes"][0]
        assert (node["su"], node["state"]) == (2, "complete")
        assert cov["by_su"] == [{"su": 2, "distribution": {"1": 1}, "complete": 1, "syncing": 0,
                                 "incomplete": 0, "unavailable": 0}]

    def test_without_a_topology_the_hostname_still_decides(self):
        cov = snap._coverage(["gpu1-su12"], [IMG], {})
        assert (cov["nodes"][0]["su"], cov["nodes"][0]["state"]) == (12, "unreachable")


def test_the_cli_files_every_roster_node_under_its_bcm_su(tmp_path, monkeypatch):
    containers = tmp_path / "containers"
    containers.mkdir()
    (containers / IMG).write_bytes(b"x" * 8)
    catalog = tmp_path / "images.json"
    catalog.write_text(json.dumps({"images": [{"order": 1, "filename": IMG, "bytes": 8}]}), encoding="utf-8")
    roster = tmp_path / "nc-fleet.nodes"
    roster.write_text("gpu1-su1\ngpu2-su20\nunlisted-su5\n", encoding="utf-8")
    topology = _topology(tmp_path, "gpu1-su1\t1\tU1\ngpu2-su20\t21\tQ3\n")
    out = tmp_path / "out" / "default.json"
    monkeypatch.setattr(snap, "_audit_receipts", lambda roster, _root, _fanout: {n: {IMG} for n in roster})
    monkeypatch.setattr(snap, "_object_store_healthy", lambda _container: True)
    monkeypatch.setattr(sys, "argv", [
        "fleet-snapshot.py", "--catalog", str(catalog), "--roster", str(roster), "--out", str(out),
        "--topology", str(topology), "--container-path", str(containers),
        "--rollout-state-dir", str(tmp_path / "state"),
    ])
    assert snap.main() == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert {n["node"]: n["su"] for n in doc["coverage"]["nodes"]} == {
        "gpu1-su1": 1, "gpu2-su20": 21, "unlisted-su5": 5,
    }
    assert [s["su"] for s in doc["fleet"]] == [1, 5, 21]
    assert doc["coverage"]["required_images"] == [IMG]


def test_the_head_argument_is_gone(monkeypatch, capsys):
    """The fan-out runs from the app server with clush, never through the BCM head; --head is refused."""
    monkeypatch.setattr(sys, "argv", ["fleet-snapshot.py", "--catalog", "c", "--roster", "r", "--out", "o",
                                      "--head", "hn1"])
    with pytest.raises(SystemExit):
        snap.main()
    assert "--head" in capsys.readouterr().err
