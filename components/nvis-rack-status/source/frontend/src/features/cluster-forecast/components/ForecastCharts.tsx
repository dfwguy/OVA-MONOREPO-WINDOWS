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
import { useMemo } from "react";
import {
  Chart as ChartJS,
  Filler,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
  type ChartOptions,
} from "chart.js";
import { Line } from "react-chartjs-2";
import { Text } from "@nvidia/foundations-react-core";
import { useThemeMode } from "../../../context/ThemeContext";
import type { ClusterForecastReport } from "../types";
import { PASSED_COLOR, SCENARIOS, formatCount } from "../lib/forecastModel";
import { tokenColor } from "../../../lib/tokenColor";

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend, Filler);

const DAY_MS = 86_400_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function dayLabel(ms: number): string {
  const d = new Date(ms);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

/**
 * The colours the canvas needs, read from the Kaizen tokens the rest of the page uses. Re-read on
 * a theme switch: a canvas does not repaint itself when a CSS variable changes.
 */
function useChartPalette() {
  const { mode } = useThemeMode();
  return useMemo(
    () => ({
      mode,
      text: tokenColor("var(--text-color-secondary)", mode === "dark" ? "#a0a0a0" : "#5e5e5e"),
      grid: tokenColor("var(--border-color-base)", mode === "dark" ? "#333" : "#ddd"),
      passed: tokenColor(PASSED_COLOR, "#76b900"),
      current: tokenColor(SCENARIOS[0].color, "#76b900"),
      tail: tokenColor(SCENARIOS[1].color, "#f2c94c"),
      reference: tokenColor("var(--text-color-subtle)", "#888"),
      racks: tokenColor("var(--color-teal-400)", "#00b3a4"),
    }),
    [mode],
  );
}

function baseOptions(text: string, grid: string, yTitle: string): ChartOptions<"line"> {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "bottom", labels: { color: text, usePointStyle: true, boxWidth: 8 } },
      tooltip: {
        callbacks: {
          title: (items) => (items[0] ? dayLabel(Number(items[0].parsed.x)) : ""),
          label: (item) => `${item.dataset.label}: ${formatCount(Math.round(Number(item.parsed.y)))}`,
        },
      },
    },
    scales: {
      x: {
        type: "linear",
        ticks: { color: text, maxTicksLimit: 8, callback: (v) => dayLabel(Number(v)) },
        grid: { color: grid },
      },
      y: {
        beginAtZero: true,
        title: { display: true, text: yTitle, color: text },
        ticks: { color: text, callback: (v) => formatCount(Number(v)) },
        grid: { color: grid },
      },
    },
  };
}

/** Nodes still to pass, projected forward under both scenarios, with 95% and 99% marked. */
export function ProjectionChart({ report }: { report: ClusterForecastReport }) {
  const c = useChartPalette();
  const rows = report.projection;
  if (!rows.length) {
    return (
      <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
        {report.summary.nodes_remaining === 0
          ? "Every node in scope has passed."
          : `No projection yet. ${report.pace.reason}`}
      </Text>
    );
  }
  const xs = rows.map((r) => Date.parse(`${r.date}T00:00:00Z`));
  const n = report.summary.nodes;
  const flat = (y: number) => [{ x: xs[0], y }, { x: xs[xs.length - 1], y }];
  const data = {
    datasets: [
      {
        label: SCENARIOS[0].label,
        data: rows.map((r, i) => ({ x: xs[i], y: r.current_pace })).filter((p) => p.y !== null),
        borderColor: c.current,
        backgroundColor: c.current,
        borderWidth: 2,
        pointRadius: 0,
      },
      {
        label: SCENARIOS[1].label,
        data: rows.map((r, i) => ({ x: xs[i], y: r.slowing_tail })).filter((p) => p.y !== null),
        borderColor: c.tail,
        backgroundColor: c.tail,
        borderWidth: 2,
        pointRadius: 0,
      },
      {
        label: "95% passed",
        data: flat(0.05 * n),
        borderColor: c.reference,
        borderDash: [4, 4],
        borderWidth: 1,
        pointRadius: 0,
      },
      {
        label: "99% passed",
        data: flat(0.01 * n),
        borderColor: c.reference,
        borderDash: [1, 3],
        borderWidth: 1,
        pointRadius: 0,
      },
    ],
  };
  const options = baseOptions(c.text, c.grid, "nodes still to pass");
  options.scales!.x = { ...options.scales!.x, min: xs[0], max: xs[0] + Math.min(xs.length - 1, 90) * DAY_MS } as never;
  return (
    <div style={{ height: 280 }} role="img" aria-label="Projection of nodes still to pass under both scenarios">
      <Line key={c.mode} data={data} options={options} />
    </div>
  );
}

/** Nodes and racks passed since sampling began; imported history drawn dashed, today as a dot. */
export function HistoryChart({ report, measure }: { report: ClusterForecastReport; measure: "nodes" | "racks" }) {
  const c = useChartPalette();
  const points = report.history;
  if (points.length < 2) {
    return (
      <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
        No history yet. Rack Status samples progress every hour; the line starts with the first sample.
      </Text>
    );
  }
  const passedKey = measure === "nodes" ? "nodes_passed" : "racks_passed";
  const color = measure === "nodes" ? c.passed : c.racks;
  const xs = points.map((p) => Date.parse(p.at));
  const data = {
    datasets: [
      {
        label: measure === "nodes" ? "Nodes passed" : "Racks passed",
        data: points.map((p, i) => ({ x: xs[i], y: p[passedKey] })),
        borderColor: color,
        backgroundColor: color,
        borderWidth: 2,
        pointRadius: points.map((p) => (p.source === "now" ? 4 : 0)),
        segment: {
          // Imported history is drawn dashed, so measured and brought-in data are told apart.
          borderDash: (ctx: { p1DataIndex: number }) => (points[ctx.p1DataIndex]?.source === "import" ? [4, 3] : undefined),
        },
      },
      {
        label: measure === "nodes" ? "Nodes in scope" : "Racks in scope",
        data: points.map((p, i) => ({ x: xs[i], y: p[measure] })),
        borderColor: c.reference,
        borderDash: [2, 3],
        borderWidth: 1,
        pointRadius: 0,
        stepped: true as const,
      },
    ],
  };
  return (
    <div style={{ height: 240 }} role="img" aria-label={`${measure === "nodes" ? "Nodes" : "Racks"} passed over time`}>
      <Line key={c.mode} data={data} options={baseOptions(c.text, c.grid, measure)} />
    </div>
  );
}
