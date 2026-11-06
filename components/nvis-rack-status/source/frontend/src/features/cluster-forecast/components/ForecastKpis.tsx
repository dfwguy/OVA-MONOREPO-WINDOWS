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
import { Card, Flex, Text } from "@nvidia/foundations-react-core";
import type { ClusterForecastReport } from "../types";
import {
  HANDED_COLOR,
  HANDED_TEXT,
  OPEN_COLOR,
  OPEN_TEXT,
  PASSED_COLOR,
  PASSED_TEXT,
  SCENARIOS,
  finishLine,
  formatCount,
  formatRate,
  formatShare,
} from "../lib/forecastModel";

interface Tile {
  key: string;
  label: string;
  value: string;
  caption: string;
  /** The card's leading edge and the value's colour; none for a neutral figure. */
  edge?: string;
  text?: string;
}

/** The headline numbers, in the tracker's tile style: where it stands, how fast, and when. */
export function ForecastKpis({ report }: { report: ClusterForecastReport }) {
  const s = report.summary;
  const handed = s.handed_over.units;
  const pace = report.pace;
  const finish = finishLine(report);
  const [current, tail] = SCENARIOS;
  const { has_racks: hasRacks, has_units: hasUnits } = report.shape;
  // "Every rack and SU complete" -> "every rack and SU complete": only the first letter, so "SU" survives.
  const done = finish.label.charAt(0).toLowerCase() + finish.label.slice(1);
  const tiles: (Tile | false)[] = [
    {
      key: "nodes",
      label: "Nodes passed",
      value: formatCount(s.nodes_passed),
      caption: `${formatShare(s.nodes_passed, s.nodes)} of ${formatCount(s.nodes)} nodes`,
      edge: PASSED_COLOR,
      text: PASSED_TEXT,
    },
    hasRacks && {
      key: "racks",
      label: "Racks passed",
      value: formatCount(s.racks_passed),
      caption: `${formatShare(s.racks_passed, s.racks)} of ${formatCount(s.racks)} racks`,
      edge: PASSED_COLOR,
      text: PASSED_TEXT,
    },
    // A handed-over SU is delivered, as the tracker counts it: it is in the count here, and only
    // left out of the pace and the dates, which are about the work still ours to do.
    hasUnits && {
      key: "units",
      label: "SUs complete",
      value: formatCount(s.units_complete + handed),
      caption: handed
        ? `of ${s.units + handed} · ${handed} handed over`
        : `of ${s.units} validating`,
      edge: s.units_complete ? PASSED_COLOR : handed ? HANDED_COLOR : undefined,
      text: s.units_complete ? PASSED_TEXT : handed ? HANDED_TEXT : undefined,
    },
    {
      key: "remaining",
      label: "Nodes still open",
      value: formatCount(s.nodes_remaining),
      caption: `${formatCount(s.nodes_failing)} failing a stage`,
      edge: s.nodes_remaining ? OPEN_COLOR : undefined,
      text: s.nodes_remaining ? OPEN_TEXT : undefined,
    },
    {
      key: "pace",
      label: "Repairs per day",
      value: pace.enough_history ? formatRate(pace.nodes_per_day) : "—",
      caption: pace.enough_history && pace.days
        ? `nodes, over the last ${Math.round(pace.days)} days`
        : "not enough history yet",
    },
    {
      key: "finish_current",
      label: `Done · ${current.label.toLowerCase()}`,
      value: finish.reached ? "Done" : finish.current_pace,
      caption: finish.current_pace_year ? `${finish.current_pace_year} · ${done}` : done,
      edge: current.color,
      text: current.text,
    },
    {
      key: "finish_tail",
      label: `Done · ${tail.label.toLowerCase()}`,
      value: finish.reached ? "Done" : finish.slowing_tail,
      caption: finish.slowing_tail_year ? `${finish.slowing_tail_year} · ${done}` : done,
      edge: tail.color,
      text: tail.text,
    },
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 12 }}>
      {tiles.filter((t): t is Tile => Boolean(t)).map((tile) => (
        <Card key={tile.key} style={{ borderLeft: `4px solid ${tile.edge ?? "var(--border-color-base)"}` }}>
          <Flex direction="col" gap="1">
            <Text kind="label/regular/sm" style={{ color: "var(--text-color-secondary)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              {tile.label}
            </Text>
            <Text kind="display/sm" data-testid={`kpi-${tile.key}`} style={{ color: tile.text }}>
              {tile.value}
            </Text>
            <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
              {tile.caption}
            </Text>
          </Flex>
        </Card>
      ))}
    </div>
  );
}
