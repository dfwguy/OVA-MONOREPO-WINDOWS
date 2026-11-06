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
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import { Tag, Text } from "@nvidia/foundations-react-core";
import type { ClusterForecastReport } from "../types";
import { SCENARIOS, formatDay, reportYear } from "../lib/forecastModel";

/** When each milestone falls under each scenario; a milestone already passed says so instead. */
export function ForecastMilestones({ report }: { report: ClusterForecastReport }) {
  const year = reportYear(report);
  return (
    <TableContainer>
      <Table size="small" aria-label="Milestones">
        <TableHead>
          <TableRow>
            <TableCell>
              <Text kind="body/bold/sm">Milestone</Text>
            </TableCell>
            {SCENARIOS.map((s) => (
              <TableCell key={s.key} align="right">
                <Text kind="body/bold/sm" style={{ color: s.text }}>
                  {s.label}
                </Text>
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {report.milestones.map((m) => (
            <TableRow key={m.id} hover data-testid={`milestone-${m.id}`}>
              <TableCell>
                <Text kind="body/regular/md">{m.label}</Text>
              </TableCell>
              {m.reached ? (
                <TableCell align="right" colSpan={SCENARIOS.length}>
                  <Tag color="green" kind="outline" readOnly density="compact">
                    Reached
                  </Tag>
                </TableCell>
              ) : (
                SCENARIOS.map((s) => (
                  <TableCell key={s.key} align="right">
                    <Text kind="body/regular/md" style={{ fontVariantNumeric: "tabular-nums" }}>
                      {m[s.key] ? formatDay(m[s.key], year) : "Not projected"}
                    </Text>
                  </TableCell>
                ))
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
