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
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// Catalog coverage heatmap: one cell per node, grouped by SU.
//
// A CSS grid rather than a charting library, for the same reasons the Rack
// Status node heatmap is: cells are a fixed small size, every cell needs its own
// tooltip, and the encoding is two-channel (fill + border). A chart abstraction
// fights all three.
//
// Encoding rules live in lib/fleetHeatmap.ts so they are testable without
// rendering, and so the legend and the cells cannot describe different things.
import { useMemo, type CSSProperties, type ReactNode } from "react";
import { Card, Flex, Tag, Text } from "@nvidia/foundations-react-core";
import Tooltip from "@mui/material/Tooltip";
import {
  COVERAGE_FILL,
  COVERAGE_LABEL,
  COVERAGE_MEANING,
  INTEGRITY_BORDER,
  INTEGRITY_LABEL,
  INTEGRITY_MEANING,
  integrityBorderWidth,
  cellTitle,
  coverageToneOf,
  groupBySu,
  integrityToneOf,
  suLabel,
  toneCounts,
  type CoverageTone,
  type IntegrityTone,
} from "../../lib/fleetHeatmap";
import type { NodeCoverage } from "../../types/fleet";

/** Racks per SU, and nodes per rack -- the physical layout the grid mirrors. */
const NODES_PER_ROW = 24;

const TONE_ORDER: CoverageTone[] = ["complete", "syncing", "incomplete", "unavailable"];
const INTEGRITY_ORDER: IntegrityTone[] = ["verified", "unverified", "corrupt", "unknown"];

/** Kaizen Tag colours that correspond to each coverage tone in the legend. */
const TONE_TAG_COLOR: Record<CoverageTone, "green" | "blue" | "yellow" | "gray"> = {
  complete: "green",
  syncing: "blue",
  incomplete: "yellow",
  unavailable: "gray",
};

export type NodeHeatmapProps = {
  nodes: NodeCoverage[];
  requiredCount: number;
  generatedAt: string | null;
};

/** One cell's square: the fill and the border, drawn the same way in the grid and the legend. */
function swatchStyle(fill: string, integrity: IntegrityTone): CSSProperties {
  return {
    display: "block",
    aspectRatio: "1",
    minWidth: 8,
    maxWidth: 14,
    borderRadius: 2,
    backgroundColor: fill,
    border: `${integrityBorderWidth(integrity)}px solid ${INTEGRITY_BORDER[integrity]}`,
  };
}

function Cell({ node, requiredCount }: { node: NodeCoverage; requiredCount: number }) {
  const tone = coverageToneOf(node, requiredCount);
  const integrity = integrityToneOf(node);
  const title = cellTitle(node, requiredCount);

  return (
    <Tooltip
      title={<span style={{ whiteSpace: "pre-line" }}>{title}</span>}
      arrow
      enterTouchDelay={0}
      describeChild
    >
      <span
        tabIndex={0}
        aria-label={title.replaceAll("\n", ". ")}
        style={{ ...swatchStyle(COVERAGE_FILL[tone], integrity), cursor: "help" }}
      />
    </Tooltip>
  );
}

function LegendEntry({ swatch, label, meaning }: { swatch: CSSProperties; label: string; meaning: string }) {
  return (
    <Flex align="center" gap="2">
      <span aria-hidden style={{ ...swatch, width: 14, flex: "none" }} />
      <Text kind="body/regular/sm">
        <span style={{ fontWeight: 600 }}>{label}</span>
        <span style={{ color: "var(--text-color-secondary)" }}>{` \u2014 ${meaning}`}</span>
      </Text>
    </Flex>
  );
}

/**
 * The key to both channels, drawn with the cells' own swatches so it cannot describe a colour the
 * grid does not use. Fill swatches carry the verified border; border swatches sit on the neutral
 * unavailable fill so only the border is read.
 */
function Legend() {
  const column = (title: string, entries: ReactNode) => (
    <Flex direction="column" gap="1" style={{ minWidth: 0 }}>
      <Text kind="body/bold/sm">{title}</Text>
      {entries}
    </Flex>
  );
  return (
    <div
      role="group"
      aria-label="Colour key"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))",
        gap: 12,
        padding: 12,
        border: "1px solid var(--border-color-base)",
        borderRadius: 6,
      }}
    >
      {column("Fill \u00b7 catalog progress", TONE_ORDER.map((tone) => (
        <LegendEntry key={tone} swatch={swatchStyle(COVERAGE_FILL[tone], "verified")}
          label={COVERAGE_LABEL[tone]} meaning={COVERAGE_MEANING[tone]} />
      )))}
      {column("Border \u00b7 content trust", INTEGRITY_ORDER.map((tone) => (
        <LegendEntry key={tone} swatch={swatchStyle(COVERAGE_FILL.unavailable, tone)}
          label={INTEGRITY_LABEL[tone]} meaning={INTEGRITY_MEANING[tone]} />
      )))}
    </div>
  );
}

/** Draws exactly the nodes it is given; the caller filters (by roster, by tone) before passing them. */
export function NodeHeatmap({ nodes, requiredCount, generatedAt }: NodeHeatmapProps) {
  const visible = nodes;
  const bySu = useMemo(() => groupBySu(visible), [visible]);
  const counts = useMemo(() => toneCounts(visible, requiredCount), [visible, requiredCount]);
  const sus = useMemo(() => [...bySu.keys()].sort((a, b) => a - b), [bySu]);

  return (
    <Card>
      <Flex direction="column" gap="3">
        <Flex justify="between" align="start" wrap="wrap" gap="2">
          <Flex direction="column" gap="1">
            <Text kind="title/md">Catalog coverage</Text>
            <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
              {visible.length.toLocaleString()} nodes across {sus.length} SU
              {sus.length === 1 ? "" : "s"}
              {generatedAt ? ` \u00b7 observed through ${generatedAt}` : " \u00b7 never verified"}
            </Text>
          </Flex>
          <Flex gap="1" wrap="wrap" aria-label="Coverage legend">
            {TONE_ORDER.map((tone) => (
              <Tag key={tone} color={TONE_TAG_COLOR[tone]} kind="solid" readOnly density="compact">
                {`${COVERAGE_LABEL[tone]} ${counts[tone].toLocaleString()}`}
              </Tag>
            ))}
          </Flex>
        </Flex>

        <Legend />

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 300px), 1fr))",
            gap: 12,
          }}
        >
          {sus.map((su) => {
            const suNodes = bySu.get(su) ?? [];
            const suCounts = toneCounts(suNodes, requiredCount);
            return (
              <Flex
                key={su}
                direction="column"
                gap="2"
                style={{
                  minWidth: 0,
                  padding: 12,
                  border: "1px solid var(--border-color-base)",
                  borderRadius: 6,
                  backgroundColor: "var(--background-color-surface-raised)",
                }}
              >
                <Flex justify="between" align="center" gap="2">
                  <Text kind="body/bold/sm">{suLabel(su)}</Text>
                  <Text kind="mono/sm" style={{ color: "var(--text-color-secondary)" }}>
                    {suCounts.complete}/{suNodes.length} complete
                  </Text>
                </Flex>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: `repeat(${NODES_PER_ROW}, minmax(8px, 1fr))`,
                    gap: 2,
                    maxWidth: 360,
                  }}
                >
                  {suNodes.map((node) => (
                    <Cell key={node.node} node={node} requiredCount={requiredCount} />
                  ))}
                </div>
              </Flex>
            );
          })}
        </div>
      </Flex>
    </Card>
  );
}
