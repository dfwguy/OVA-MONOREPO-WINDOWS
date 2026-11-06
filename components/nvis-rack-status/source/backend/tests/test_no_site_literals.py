# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""No customer's site in the code every customer runs.

One server and one image serve several customers, and ``bin/scripts`` is deployed to every head
node. An audit on 2026-10-28 found another customer's facts in exactly those places: the Nscale TX
BMC addresses of 36 trays inside a Redfish sweep, a Firmus rack roster and ``MEL01`` prefix inside
an NCCL campaign driver, ``nscale_<rack>`` as every site's NVLMapper system name, and the setup
wizard offering ``ink50`` and a Boston head-node IP as the example to type.

The rule (``cluster-paths.mdc``): a site's names, addresses and folders come from its
Project/Cluster record, never from a literal. Comments and docstrings are exempt on purpose --
they record where a lesson was learned, which is the reason the code looks the way it does.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: A customer, site, host or person: names and addresses that belong to one deployment.
SITE = re.compile(
    r"\bink50\b|\bMEL01\b|\bbos01\b|sys1-gso1|\bnscale|NSCALE|\bfirmus\b|\bboston\b"
    r"|\b10\.29\.1|\b10\.40\.1|\b192\.168\.10\.|/home/(cmods|rkoike|cmsupport|harish)\b|/cluster/(llmb|OVA)\b",
    re.IGNORECASE,
)

#: Literals that name a site on purpose, each with the reason it stays.
ALLOWED = {
    # The report kind's id is an API value the SPA and stored reports already carry; its label is
    # neutral. The id names the schema's origin, not the deployment it runs on.
    ("backend/api/reports.py", '"nscale"'),
    ("backend/api/reports.py", '"nscale-report"'),
}

#: Files that are another party's document, vendored verbatim; editing them would fork the contract.
VENDORED = {
    "backend/schemas/node_report_schema.json",  # the customer's own test-result schema, $id and title
}


def _shell_code(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(re.sub(r"\s#\s.*$", "", line))
    return lines


def _ts_code(text: str) -> list[str]:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return [re.sub(r"\s//\s.*$", "", line) for line in text.splitlines() if not line.lstrip().startswith("//")]


def _python_strings(text: str) -> list[str]:
    """Every string constant that is not a docstring or a bare string statement."""
    tree = ast.parse(text)
    docs = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }
    return [
        repr(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
    ]


def _hits(rel: str, chunks: list[str]) -> list[str]:
    out = []
    for chunk in chunks:
        for match in SITE.finditer(chunk):
            if any(rel == f and lit.strip('"') in chunk for f, lit in ALLOWED):
                continue
            out.append(f"{rel}: {match.group(0)!r} in {chunk.strip()[:120]}")
    return out


def _scan(paths, reader) -> list[str]:
    offenders = []
    for path in paths:
        rel = path.relative_to(REPO).as_posix()
        if rel in VENDORED:
            continue
        offenders.extend(_hits(rel, reader(path.read_text(encoding="utf-8"))))
    return offenders


def _is_test(path: Path) -> bool:
    return ".test." in path.name or "__fixtures__" in path.parts or "tests" in path.parts


def test_the_scripts_every_head_node_receives_name_no_site():
    scripts = REPO / "bin" / "scripts"
    shell = [p for p in scripts.rglob("*") if p.is_file() and p.suffix in (".sh", ".sbatch", ".inc")]
    python = [p for p in scripts.rglob("*.py") if p.is_file()]
    data = [p for p in scripts.rglob("*") if p.is_file() and p.suffix in (".json", ".toml", ".yaml", ".yml")]
    offenders = _scan(shell, _shell_code) + _scan(python, _python_strings) + _scan(data, str.splitlines)
    assert not offenders, "\n".join(offenders)


def test_the_ui_every_customer_sees_names_no_site():
    src = REPO / "frontend" / "src"
    files = [
        p for p in src.rglob("*")
        if p.is_file() and p.suffix in (".ts", ".tsx") and not _is_test(p) and "kaizen" not in p.parts
    ]
    offenders = _scan(files, _ts_code)
    assert not offenders, "\n".join(offenders)


def test_backend_string_literals_name_no_site():
    files = [p for p in (REPO / "backend").rglob("*.py") if not _is_test(p)]
    offenders = _scan(files, _python_strings)
    offenders += _scan([p for p in (REPO / "backend").rglob("*.json") if not _is_test(p)], str.splitlines)
    assert not offenders, "\n".join(offenders)


def test_the_guard_sees_a_literal_and_ignores_a_comment():
    """The scanners must find what they exist to find -- a guard that cannot fail proves nothing."""
    assert _hits("x.sh", _shell_code('pref="MEL01-${hc}"\n# on MEL01 this was literal\n'))
    assert not _hits("x.sh", _shell_code("# on MEL01 this was literal\n"))
    assert _hits("x.py", _python_strings('X = "/home/cmods/bringup"\n'))
    assert not _hits("x.py", _python_strings('"""Learned on Nscale NC."""\nX = 1\n'))
    assert _hits("x.tsx", _ts_code('<TextInput placeholder="ink50-dh01-h15-15" />\n'))
    assert not _hits("x.tsx", _ts_code("// ink50 was the old example\n/* and MEL01 */\n"))


# --- the scripts that lost their literals take the values from the caller or the record ---------

SCRIPTS = REPO / "bin" / "scripts"


def _load_sweep():
    import importlib.util

    spec = importlib.util.spec_from_file_location("sweep", SCRIPTS / "redfish_power_smoothing_sweep.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_power_smoothing_sweep_reads_its_trays_from_a_file(tmp_path):
    sweep = _load_sweep()
    csv_path = tmp_path / "bmcs.csv"
    csv_path.write_text("node,ip\ndc1-r01-15,10.0.0.15\ndc1-r01-16,10.0.0.16\nnoip-r09-01,\n", encoding="utf-8")
    assert sweep.read_targets(str(csv_path)) == {"dc1-r01-15": "10.0.0.15", "dc1-r01-16": "10.0.0.16"}


def test_the_sweep_spreads_controls_one_per_rack_and_never_picks_a_suspect():
    sweep = _load_sweep()
    candidates = {"dc1-r01-15": "a", "dc1-r01-16": "b", "dc1-r02-01": "c", "dc1-r03-01": "d", "dc1-r04-01": "e"}
    picks = sweep.spread_controls(candidates, exclude={"dc1-r01-15"}, want=3)
    assert picks == {"dc1-r01-16": "b", "dc1-r02-01": "c", "dc1-r03-01": "d"}


def _campaign(*args, **env):
    import subprocess

    base = {"PATH": "/usr/bin:/bin", "LLMB_INSTALL": "/nonexistent/llmb"}
    return subprocess.run(
        ["bash", str(SCRIPTS / "nccl_campaign.sh"), *args],
        env={**base, **env}, capture_output=True, text=True, timeout=30, check=False,
    )


def test_the_nccl_campaign_has_no_rack_pool_of_its_own():
    proc = _campaign()
    assert proc.returncode == 2
    assert "no racks" in proc.stderr


def test_the_nccl_campaign_takes_its_site_prefix_from_the_cluster():
    proc = _campaign("HC07-RK0103")
    assert proc.returncode != 0
    assert "Site prefix" in proc.stderr


def test_nvlmapper_names_the_system_after_the_active_cluster():
    """Run the script's own ``system_name`` in a child interpreter, under each cluster name."""
    import subprocess
    import sys

    text = (SCRIPTS / "run_nvlmapper.sh").read_text(encoding="utf-8")
    source = re.search(r"^def system_name\(.*?(?=^\S)", text, flags=re.MULTILINE | re.DOTALL).group(0)
    program = f"import os, re\n{source}\nprint(system_name('r07'))"

    def named(cluster: str) -> str:
        return subprocess.run(
            [sys.executable, "-c", program], env={"RACK_CLUSTER_NAME": cluster},
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()

    assert named("Acme West 2") == "acme_west_2_r07"
    assert named("") == "r07"
