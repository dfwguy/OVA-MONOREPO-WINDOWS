/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */
import { useState } from "react";
import IconButton from "@mui/material/IconButton";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import { Flex, Tag, Text } from "@nvidia/foundations-react-core";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ClusterForecastReport, ForecastUnit } from "../types";
import {
  OPEN_TEXT,
  PASSED_COLOR,
  PHASE_LABEL,
  PHASE_TAG,
  SCENARIOS,
  TRACK_COLOR,
  formatCount,
  formatShare,
  orderedUnits,
  reportYear,
  unitDate,
} from "../lib/forecastModel";


function UnitLine({ unit, year, showRacks }: { unit: ForecastUnit; year: number; showRacks: boolean }) {
  const [open, setOpen] = useState(false);
  const muted = unit.phase !== "validating";
  const openRacks = unit.phase === "validating" ? unit.open_racks : [];
  const share = unit.nodes ? (100 * unit.nodes_passed) / unit.nodes : 0;
  const tone = muted ? { color: "var(--text-color-secondary)" } : undefined;
  return (
    <>
      <TableRow hover data-testid={`unit-${unit.unit}`}>
        <TableCell>
          <Flex align="center" gap="1">
            {openRacks.length ? (
              <IconButton
                size="small"
                aria-label={`${open ? "Collapse" : "Expand"} ${unit.label}`}
                aria-expanded={open}
                onClick={() => setOpen((o) => !o)}
              >
                {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </IconButton>
            ) : (
              <span style={{ display: "inline-block", width: 34 }} />
            )}
            <Text kind="body/bold/md" style={tone}>
              {unit.label}
            </Text>
          </Flex>
        </TableCell>
        <TableCell>
          {unit.complete ? (
            <Tag color="green" kind="solid" readOnly density="compact">Complete</Tag>
          ) : (
            <Tag color={PHASE_TAG[unit.phase]} kind="outline" readOnly density="compact">
              {PHASE_LABEL[unit.phase]}
            </Tag>
          )}
        </TableCell>
        <TableCell align="right">
          <Text kind="body/regular/md" style={tone}>{formatCount(unit.nodes)}</Text>
        </TableCell>
        <TableCell align="right">
          <Flex direction="col" align="end" gap="1">
            <Text kind="body/regular/md" style={tone}>
              {formatCount(unit.nodes_passed)} · {formatShare(unit.nodes_passed, unit.nodes)}
            </Text>
            <div aria-hidden style={{ width: 96, height: 6, borderRadius: 3, overflow: "hidden", background: TRACK_COLOR }}>
              <div style={{ width: `${share}%`, height: "100%", background: PASSED_COLOR }} />
            </div>
          </Flex>
        </TableCell>
        <TableCell align="right">
          <Text kind="body/regular/md" style={{ color: unit.nodes_failing ? OPEN_TEXT : "var(--text-color-subtle)" }}>
            {formatCount(unit.nodes_failing)}
          </Text>
        </TableCell>
        {showRacks ? (
          <TableCell align="right">
            <Text kind="body/regular/md" style={tone}>
              {unit.racks ? `${unit.racks_passed} / ${unit.racks}` : "—"}
            </Text>
          </TableCell>
        ) : null}
        {SCENARIOS.map((s) => (
          <TableCell key={s.key} align="right">
            <Text
              kind="body/bold/md"
              style={{ color: unit.complete ? s.text : muted ? "var(--text-color-secondary)" : undefined, fontVariantNumeric: "tabular-nums" }}
            >
              {unitDate(unit, s.key, year)}
            </Text>
          </TableCell>
        ))}
      </TableRow>
      {open ? (
        <TableRow>
          <TableCell colSpan={(showRacks ? 6 : 5) + SCENARIOS.length} sx={{ pl: 7 }}>
            <Flex gap="2" wrap="wrap" align="center">
              <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
                Open racks, by nodes still missing:
              </Text>
              {openRacks.map((r) => (
                <Tag key={r.rack} color={r.missing === 0 ? "green" : r.missing >= 10 ? "red" : "gray"} kind="outline" readOnly density="compact">
                  {r.rack} · {r.missing === 0 ? "ready" : r.missing}
                </Tag>
              ))}
            </Flex>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}

/** Every scalable unit: how far it has got, and when it finishes under each scenario. */
export function ForecastUnits({ report }: { report: ClusterForecastReport }) {
  const year = reportYear(report);
  const showRacks = report.shape.has_racks;
  const numeric = ["Nodes", "Passed", "Failing", ...(showRacks ? ["Racks passed"] : [])];
  return (
    <TableContainer>
      <Table size="small" aria-label={report.shape.has_units ? "Scalable units" : "Groups"}>
        <TableHead>
          <TableRow>
            <TableCell>
              <Text kind="body/bold/sm">{report.shape.group_label}</Text>
            </TableCell>
            <TableCell>
              <Text kind="body/bold/sm">Status</Text>
            </TableCell>
            {numeric.map((h) => (
              <TableCell key={h} align="right">
                <Text kind="body/bold/sm">{h}</Text>
              </TableCell>
            ))}
            {SCENARIOS.map((s) => (
              <TableCell key={s.key} align="right">
                <Text kind="body/bold/sm" style={{ color: s.text }}>
                  Done · {s.label.toLowerCase()}
                </Text>
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {orderedUnits(report.units).map((unit) => (
            <UnitLine key={unit.unit} unit={unit} year={year} showRacks={showRacks} />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
