#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
# Author: Rafael M. Koike & Cursor Agent ("Ada")
"""redfish_power_smoothing_sweep — survey NVIDIA Power Smoothing state + GPU power setpoints over Redfish.

Read-only. Probes every tray in ``--suspects`` (the trays under investigation) and, optionally, a
spread of healthy controls from ``--controls`` -- at most ``--control-count``, one per rack -- and
reports per GPU: PowerSmoothing Enabled / supported / remaining-lifetime / TMPWatts, and
EnvironmentMetrics PowerLimitWatts SetPoint + persistency.

Both files are CSV with ``node,ip`` columns (the BMC address of each tray); nothing about a site is
built in. A tray's rack is its hostname without the last ``-`` field, which is how controls spread.

Env: BMC_USER, BMC_PASSWORD. Run it from a host that routes to the BMC network.

    BMC_USER=... BMC_PASSWORD=... redfish_power_smoothing_sweep.py --suspects capped.csv --controls all-bmcs.csv
"""

import argparse
import base64
import csv
import json
import os
import ssl
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CTX = ssl._create_unverified_context()


def _auth() -> str:
    return base64.b64encode(f"{os.environ['BMC_USER']}:{os.environ['BMC_PASSWORD']}".encode()).decode()


def read_targets(path: str) -> dict[str, str]:
    """``{node: bmc_ip}`` from a ``node,ip`` CSV, skipping rows missing either."""
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["node"].strip(): r["ip"].strip() for r in csv.DictReader(fh) if (r.get("node") or "").strip() and (r.get("ip") or "").strip()}


def spread_controls(candidates: dict[str, str], exclude: set[str], want: int) -> dict[str, str]:
    """At most *want* controls, one per rack, skipping the suspects -- not six neighbours."""
    picks: dict[str, str] = {}
    seen: set[str] = set()
    for node, ip in sorted(candidates.items()):
        rack = node.rsplit("-", 1)[0]
        if node in exclude or rack in seen:
            continue
        seen.add(rack)
        picks[node] = ip
        if len(picks) >= want:
            break
    return picks


def get(bmc, path, timeout=25):
    req = urllib.request.Request(
        f"https://{bmc}{path}",
        headers={"Authorization": f"Basic {_auth()}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
            return json.load(r)
    except Exception as exc:  # noqa: BLE001 - any transport/parse failure is just an unreachable BMC
        return {"__error__": str(exc)}


def probe(item, gpus):
    name, bmc = item
    row = {"node": name, "bmc": bmc, "ps": [], "life": [], "tmp": [],
           "sp": [], "persist": [], "supported": [], "error": None}
    for gpu in gpus:
        ps = get(bmc, f"/redfish/v1/Systems/HGX_Baseboard_0/Processors/{gpu}/Oem/Nvidia/PowerSmoothing")
        if "__error__" in ps:
            row["error"] = ps["__error__"][:70]
            return row
        row["ps"].append(ps.get("Enabled"))
        row["supported"].append(ps.get("PowerSmoothingSupported"))
        row["life"].append(ps.get("RemainingLifetimeCircuitryPercent"))
        row["tmp"].append(ps.get("TMPWatts"))

        em = get(bmc, f"/redfish/v1/Systems/HGX_Baseboard_0/Processors/{gpu}/EnvironmentMetrics")
        if "__error__" in em:
            row["error"] = em["__error__"][:70]
            return row
        row["sp"].append((em.get("PowerLimitWatts") or {}).get("SetPoint"))
        row["persist"].append(((em.get("Oem") or {}).get("Nvidia") or {}).get("PowerLimitPersistency"))
    return row


def fmt(vals):
    return "[" + ",".join("-" if v is None else
                          ("T" if v is True else "F" if v is False else
                           str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
                          for v in vals) + "]"


def render(rows, title):
    print(f"\n{'=' * 104}\n{title}\n{'=' * 104}")
    width = max([9] + [len(r["node"]) for r in rows])
    print(f"{'node':<{width}} {'bmc':<14} {'SetPoint per GPU':<24} {'PS-Enabled':<11} "
          f"{'Persist':<10} {'Life%':<20} {'TMPWatts'}")
    print("-" * 104)
    for r in sorted(rows, key=lambda x: x["node"]):
        if r["error"]:
            print(f"{r['node']:<{width}} {r['bmc']:<14} ERROR: {r['error']}")
            continue
        print(f"{r['node']:<{width}} {r['bmc']:<14} {fmt(r['sp']):<24} {fmt(r['ps']):<11} "
              f"{fmt(r['persist']):<10} {fmt(r['life']):<20} {fmt(r['tmp'])}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--suspects", required=True, help="node,ip CSV of the trays under investigation")
    ap.add_argument("--controls", default="", help="node,ip CSV to pick healthy controls from")
    ap.add_argument("--control-count", type=int, default=6, help="controls to probe, one per rack (default 6)")
    ap.add_argument("--gpus", type=int, default=4, help="GPUs per tray on the HGX baseboard (default 4)")
    args = ap.parse_args(argv)
    gpus = tuple(f"GPU_{i}" for i in range(args.gpus))

    suspects = read_targets(args.suspects)
    if not suspects:
        ap.error(f"{args.suspects}: no node,ip rows")
    picks = spread_controls(read_targets(args.controls), set(suspects), args.control_count) if args.controls else {}

    with ThreadPoolExecutor(max_workers=12) as pool:
        capped_rows = list(pool.map(lambda item: probe(item, gpus), suspects.items()))
        healthy_rows = list(pool.map(lambda item: probe(item, gpus), picks.items())) if picks else []

    order = ",".join(f"g{i}" for i in range(args.gpus))
    render(capped_rows, f"SUSPECT TRAYS ({len(capped_rows)})  —  legend: T=true F=false, order {order}")
    if healthy_rows:
        render(healthy_rows, f"HEALTHY CONTROL TRAYS ({len(healthy_rows)})")

    ok = [r for r in capped_rows if not r["error"]]
    err = [r for r in capped_rows if r["error"]]
    print(f"\n{'=' * 104}\nSUMMARY\n{'=' * 104}")
    print(f"suspects probed OK: {len(ok)}/{len(capped_rows)}   unreachable: {len(err)}")
    if ok:
        any_ps = [r["node"] for r in ok if any(r["ps"])]
        print(f"trays with PowerSmoothing Enabled=true on ANY GPU: {len(any_ps)} {any_ps}")
        life = {v for r in ok for v in r["life"]}
        print(f"distinct RemainingLifetimeCircuitryPercent values: {sorted(life, key=str)}")
        pat = {}
        for r in ok:
            pat.setdefault(tuple(r["sp"]), []).append(r["node"])
        for k, v in sorted(pat.items(), key=lambda x: -len(x[1])):
            print(f"SetPoint pattern {list(k)}: {len(v)} trays")
        pp = {}
        for r in ok:
            pp.setdefault(tuple(r["persist"]), []).append(r["node"])
        for k, v in sorted(pp.items(), key=lambda x: -len(x[1])):
            print(f"PowerLimitPersistency pattern {list(k)}: {len(v)} trays")
    for r in healthy_rows:
        if not r["error"]:
            print(f"control {r['node']}: SetPoint={r['sp']} PS={r['ps']} "
                  f"persist={r['persist']} life={r['life']} TMPWatts={r['tmp']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
