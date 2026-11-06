# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""NVIDIA Base Command Manager (BCM) 11.x platform provider.

Translates the rack-status action vocabulary into the CLI tools available on
a BCM head node: ``cmsh``, ``pdsh``, ``sinfo``/``squeue``/``sacct``/``scontrol``
(behind ``module load slurm``), and operational shell scripts.
"""
from __future__ import annotations

import os
import re

import bcm_query
import config_env
import host_exec

from platforms.base import PlatformProvider, _compute_node_records


class BCMProvider(PlatformProvider):
    kind = "bcm"

    # -- Cluster manager (cmsh) ---------------------------------------------

    def rack_inventory(self) -> list[str]:
        """Saved rack objects, independent of hostname or dashboard naming templates.

        Older deployed helpers lack the racks query; cmsh's name-only list is the
        fallback, so upgrading the app does not require upgrading the head first.
        """
        result = bcm_query.query("racks")
        if isinstance(result, dict) and result.get("ok") is True:
            names = result.get("data")
        else:
            cmsh = config_env._eget("RACK_CMSH", "cmsh") or "cmsh"
            proc = host_exec.run_on_host(
                [cmsh, "--tty", "--nocolor", "-c", "rack; list -f name"], timeout=120,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"BCM rack inventory failed: {proc.stderr.strip() or 'cmsh query unsuccessful'}")
            lines = (proc.stdout or "").splitlines()
            # Rack mode does not implement device mode's foreach: it silently emits
            # nothing. The one-column list has a header and separator, not device names.
            # cmsh normally omits headers when stdout is captured. --tty keeps the
            # table verifiable (including zero racks); --nocolor keeps it plain text.
            if len(lines) < 2 or not re.fullmatch(r"name\s+\(key\)\s*", lines[0], re.IGNORECASE):
                raise RuntimeError("BCM rack inventory failed: invalid cmsh rack table")
            if not re.fullmatch(r"-+\s*", lines[1]):
                raise RuntimeError("BCM rack inventory failed: missing cmsh table separator")
            names = lines[2:]
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise RuntimeError("BCM rack inventory must contain a list of rack names")
        # The one-column reader excludes headers and member hostnames from rack names.
        return sorted({name.strip() for name in names if name.strip()}, key=str.casefold)

    def compute_node_inventory(self) -> list[dict[str, str | None]]:
        result = bcm_query.nodes()
        if isinstance(result, dict) and result.get("ok") is not True:
            # The pythoncm helper needs credentials a BCM site may not have issued us; cmsh on
            # the head answers the same placement question for any scheduler that runs there.
            return self._cmsh_node_inventory()
        if not isinstance(result, dict) or result.get("ok") is not True:
            reason = result.get("error") if isinstance(result, dict) else "invalid response"
            raise RuntimeError(f"BCM node inventory failed: {reason or 'query unsuccessful'}")
        return _compute_node_records(
            result.get("data"), provider="BCM", rack_field="rack_id", ip_field="bmc_ip",
            rack_unit_field="rack_unit", status_field="status",
        )

    def _cmsh_node_inventory(self) -> list[dict[str, str | None]]:
        """Read placement without pythoncm credentials or a matching deployed helper."""
        cmsh = config_env._eget("RACK_CMSH", "cmsh") or "cmsh"
        proc = host_exec.run_on_host(
            [cmsh, "-c", "device; foreach -t physicalnode (get hostname; get rack)"], timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"BCM node inventory failed: {proc.stderr.strip() or 'cmsh query unsuccessful'}")
        lines = (proc.stdout or "").splitlines()
        if len(lines) % 2:
            raise RuntimeError("BCM node inventory failed: incomplete cmsh hostname/rack pairs")
        records = []
        for index in range(0, len(lines), 2):
            rack, _, unit = lines[index + 1].strip().rpartition(":")
            if not rack:
                rack, unit = lines[index + 1].strip(), ""
            records.append({"hostname": lines[index].strip(), "rack_id": rack, "rack_unit": unit})
        return _compute_node_records(
            records, provider="BCM", rack_field="rack_id", rack_unit_field="rack_unit",
        )

    def list_racks_cmd(self) -> list[str]:
        cmsh = (os.environ.get("RACK_CMSH") or "cmsh").strip() or "cmsh"
        return [cmsh, "-c", "rack; list"]

    def device_status_cmd(self) -> list[str]:
        cmsh = (os.environ.get("RACK_CMSH") or "cmsh").strip() or "cmsh"
        return [cmsh, "-c", "ds"]

    def physical_rf0_cmd(self) -> list[str]:
        cmsh = (os.environ.get("RACK_CMSH") or "cmsh").strip() or "cmsh"
        return [
            cmsh, "-c",
            "device; foreach -t physicalnode (get hostname; interfaces; use rf0; get ip)",
        ]

    def device_power_cmd(self, inner: str) -> list[str]:
        cmsh = (os.environ.get("RACK_CMSH") or "cmsh").strip() or "cmsh"
        return [cmsh, "-c", inner]

    # -- pdsh service management --------------------------------------------

    def services_restart_remote_cmd(self) -> str:
        return (
            "mount -a; "
            "systemctl restart munge; "
            "systemctl restart slurmd; "
            "systemctl restart nvidia-imex; "
            "systemctl restart nvidia-dcgm 2>/dev/null || systemctl restart cuda-dcgm"
        )
