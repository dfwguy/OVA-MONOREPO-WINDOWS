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
// What a wave plan does, drawn: the app server's seeds on the left, then the waves left to right.
// Author: Rafael M. Koike
//
// Three example racks of six nodes stand in for the roster; the point is the shape, not the counts.
// Rack-staged: only the first stage pulls from the seeds (one node per rack), and every later stage
// grows each rack from its own rack-mates, so the arrows run along a rack's row. Sequential: waves
// take the roster in order, so a wave is whichever nodes come next -- here a rack at a time -- and
// every wave can pull from the seeds, so the arrows all fan out of the app server.
//
// Drawn in theme tokens (brand for the nodes a step adds, secondary for the ones already holding),
// so it reads in light and dark alike. Mirrors operations-worker.py's rack_staged_waves.
import type { RolloutStrategy } from "../../services/fleetService";
import { stageFill } from "../../lib/rolloutStages";

const RACKS = ["Rack A", "Rack B", "Rack C"];
const RACK_SIZE = 6;
const W = 720;
const SEED = { x: 8, w: 104 };
const TOP = 34; // room for the column headings
const ROW_H = 44;
const CELL = 11; // one node square
const GAP = 3;
const NEW = "var(--text-color-brand)";
const HELD = "var(--text-color-secondary)";
const EMPTY = "var(--border-color-base)";
const TEXT = "var(--text-color-primary)";
const MUTED = "var(--text-color-secondary)";

type Column = { heading: string; fill: number[] }; // nodes holding after this column, per rack

function columnsFor(strategy: RolloutStrategy, stages: string[]): Column[] {
  if (strategy === "rack-staged") {
    const ladder = stages.length ? stages : ["1", "50%", "100%"];
    return ladder.slice(0, 4).map((stage, i) => ({
      heading: `Stage ${i + 1} \u00b7 ${stage}${stage.endsWith("%") ? " of each rack" : " per rack"}`,
      fill: RACKS.map(() => stageFill(stage, RACK_SIZE)),
    }));
  }
  // Sequential, roster in order: with a wave the size of a rack, wave k is rack k.
  return RACKS.map((_, i) => ({
    heading: `Wave ${i + 1}`,
    fill: RACKS.map((__, r) => (r <= i ? RACK_SIZE : 0)),
  }));
}

/** A rack's row of node squares at (x, y): *held* already there, *added* new in this column. */
function RackCells({ x, y, held, added }: { x: number; y: number; held: number; added: number }) {
  return (
    <g>
      {Array.from({ length: RACK_SIZE }, (_, i) => (
        <rect
          key={i}
          x={x + i * (CELL + GAP)}
          y={y}
          width={CELL}
          height={CELL}
          rx={2}
          fill={i < held ? HELD : i < held + added ? NEW : "none"}
          stroke={i < held + added ? "none" : EMPTY}
        />
      ))}
    </g>
  );
}

export function WavePlanDiagram({
  strategy, stages, caption,
}: { strategy: RolloutStrategy; stages: string[]; caption: string }) {
  const columns = columnsFor(strategy, stages);
  const rackW = RACK_SIZE * (CELL + GAP) - GAP;
  const colStart = SEED.x + SEED.w + 40;
  const LABEL_W = 56; // rack names sit at the right edge, clear of every arrow
  const colW = (W - colStart - LABEL_W) / columns.length;
  const rowY = (r: number) => TOP + 8 + r * ROW_H;
  const cellX = (c: number) => colStart + c * colW + (colW - rackW) / 2;
  const height = TOP + 8 + RACKS.length * ROW_H + 10;
  const seedMid = TOP + 8 + ((RACKS.length - 1) * ROW_H) / 2 + CELL / 2;

  // A seed arrow runs along the gap above its rack's row (its lane), so a pull into a later column
  // never crosses the racks drawn in the columns before it.
  const laneY = (r: number) => rowY(r) - (ROW_H - CELL) / 2 + 2;
  const arrows: { x1: number; y1: number; x2: number; y2: number; seed: boolean; lane: number }[] = [];
  columns.forEach((col, c) => {
    RACKS.forEach((_, r) => {
      const before = c === 0 ? 0 : columns[c - 1].fill[r];
      if (col.fill[r] <= before) return; // this column adds nothing to this rack
      const y = rowY(r) + CELL / 2;
      // Rack-staged: seeds feed stage 1 only, then each rack feeds itself. Sequential: always the seeds.
      if (strategy === "sequential" || c === 0) {
        arrows.push({ x1: SEED.x + SEED.w, y1: seedMid, x2: cellX(c) - 4, y2: y, seed: true, lane: laneY(r) });
      } else {
        arrows.push({ x1: cellX(c - 1) + rackW + 4, y1: y, x2: cellX(c) - 4, y2: y, seed: false, lane: y });
      }
    });
  });

  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${W} ${height}`}
        width="100%"
        role="img"
        aria-label={`Wave plan: ${caption}`}
        style={{ display: "block", maxWidth: W }}
      >
        <defs>
          <marker id="wave-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill={MUTED} />
          </marker>
        </defs>

        <rect x={SEED.x} y={seedMid - 22} width={SEED.w} height={44} rx={6} fill="none" stroke={MUTED} />
        <text x={SEED.x + SEED.w / 2} y={seedMid - 3} textAnchor="middle" fontSize={12} fontWeight={600} fill={TEXT}>App server</text>
        <text x={SEED.x + SEED.w / 2} y={seedMid + 12} textAnchor="middle" fontSize={11} fill={MUTED}>seeds</text>

        {arrows.map((a, i) => (
          <path
            key={i}
            d={a.seed
              ? a.x2 - colStart < colW
                // Into the first column: one curve, straight to the row.
                ? `M${a.x1},${a.y1} C${a.x1 + 30},${a.y1} ${a.x2 - 30},${a.y2} ${a.x2},${a.y2}`
                // Further right: out to the row's lane, along it, then down into the cell.
                : `M${a.x1},${a.y1} C${a.x1 + 24},${a.y1} ${colStart - 32},${a.lane} ${colStart - 8},${a.lane} L${a.x2 - 22},${a.lane} Q${a.x2 - 10},${a.lane} ${a.x2},${a.y2}`
              : `M${a.x1},${a.y1} L${a.x2},${a.y2}`}
            fill="none"
            stroke={MUTED}
            strokeWidth={1.2}
            markerEnd="url(#wave-arrow)"
          />
        ))}

        {columns.map((col, c) => (
          <g key={col.heading}>
            <text x={cellX(c) + rackW / 2} y={16} textAnchor="middle" fontSize={11} fontWeight={600} fill={TEXT}>{col.heading}</text>
            {RACKS.map((rack, r) => {
              const before = c === 0 ? 0 : columns[c - 1].fill[r];
              return <RackCells key={rack} x={cellX(c)} y={rowY(r)} held={before} added={Math.max(0, col.fill[r] - before)} />;
            })}
          </g>
        ))}

        {RACKS.map((rack, r) => (
          <text key={rack} x={W - LABEL_W + 10} y={rowY(r) + CELL - 1} fontSize={11} fill={MUTED}>{rack}</text>
        ))}
      </svg>
      <figcaption style={{ fontSize: 12, color: MUTED, marginTop: 4 }}>
        <span style={{ color: NEW, fontWeight: 600 }}>{"■"}</span> added in that step{" · "}
        <span style={{ color: HELD, fontWeight: 600 }}>{"■"}</span> already holding{" · "}
        {caption}
      </figcaption>
    </figure>
  );
}
