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
  Legend,
  LineElement,
  LinearScale,
  LogarithmicScale,
  PointElement,
  Tooltip,
  type ChartOptions,
} from "chart.js";
import { Line } from "react-chartjs-2";
import { Flex, Text } from "@nvidia/foundations-react-core";
import { useThemeMode } from "../../../context/ThemeContext";
import { tokenColor } from "../../../lib/tokenColor";
import { BAND_COLLECTIVES, COLLECTIVE_COLOR, COLLECTIVE_LABEL, bandPoints, formatSize } from "../lib/handoverModel";
import type { Collective, CurvePoint, HandoverRunDetail, StepPoint } from "../types";

ChartJS.register(LinearScale, LogarithmicScale, PointElement, LineElement, Tooltip, Legend);

const muted = { color: "var(--text-color-secondary)" } as const;

function usePalette() {
  const { mode } = useThemeMode();
  return useMemo(
    () => ({
      text: tokenColor("var(--text-color-secondary)", mode === "dark" ? "#a0a0a0" : "#5e5e5e"),
      grid: tokenColor("var(--border-color-base)", mode === "dark" ? "#333" : "#ddd"),
    }),
    [mode],
  );
}

/** One collective's bus bandwidth from 2 GB to 16 GB: the sizes a handover is judged at. */
export function NcclBandChart({ collective, points }: { collective: Collective; points: CurvePoint[] | undefined }) {
  const c = usePalette();
  const band = bandPoints(points);
  const label = COLLECTIVE_LABEL[collective];
  if (!band.length) {
    return (
      <Flex direction="col" gap="1" data-testid={`nccl-band-${collective}`}>
        <Text kind="label/bold/sm">{label}</Text>
        <Text kind="body/regular/sm" style={muted}>Not measured from 2 GB to 16 GB in this run.</Text>
      </Flex>
    );
  }
  const color = COLLECTIVE_COLOR[collective];
  const data = {
    datasets: [
      {
        label,
        data: band.map((p) => ({ x: p.size_bytes, y: p.busbw_gbps })),
        borderColor: color,
        backgroundColor: color,
        borderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 6,
      },
    ],
  };
  const options: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "nearest", axis: "x", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => (items[0] ? formatSize(Number(items[0].parsed.x)) : ""),
          label: (item) => `${label}: ${Number(item.parsed.y).toFixed(1)} GB/s`,
        },
      },
    },
    scales: {
      x: {
        type: "logarithmic",
        min: 2 * 1024 ** 3 * 0.9,
        max: 16 * 1024 ** 3 * 1.1,
        title: { display: true, text: "Message size", color: c.text },
        ticks: { color: c.text, autoSkip: false, callback: (v) => formatSize(Number(v)).replace(" ", "") },
        afterBuildTicks: (axis) => {
          axis.ticks = [1, 2, 3, 4].map((e) => ({ value: 2 ** (30 + e) }));
        },
        grid: { color: c.grid },
      },
      y: {
        beginAtZero: true,
        title: { display: true, text: "Bus bandwidth (GB/s)", color: c.text },
        ticks: { color: c.text },
        grid: { color: c.grid },
      },
    },
  };
  return (
    <Flex direction="col" gap="1" data-testid={`nccl-band-${collective}`}>
      <Text kind="label/bold/sm">{label}</Text>
      <div style={{ height: 240 }}>
        <Line data={data} options={options} aria-label={`${label} bus bandwidth from 2 GB to 16 GB`} />
      </div>
    </Flex>
  );
}

/** The three acceptance collectives side by side, each on its own scale. */
export function NcclBandCharts({ curves }: { curves: HandoverRunDetail["nccl_curves"] }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
      {BAND_COLLECTIVES.map((k) => (
        <NcclBandChart key={k} collective={k} points={curves[k]} />
      ))}
    </div>
  );
}

/** Training throughput per step, in steps per second. */
export function LlmStepsChart({ steps }: { steps: StepPoint[] }) {
  const c = usePalette();
  if (steps.length < 2) {
    return <Text kind="body/regular/sm" style={muted}>No training steps in this run's logs.</Text>;
  }
  // Warm-up steps are slow outliers on the low side only: scale to the steady state.
  const sorted = steps.map((p) => p.steps_per_s).sort((a, b) => a - b);
  const top = sorted[Math.floor(sorted.length * 0.95)] * 1.15;
  const data = {
    datasets: [
      {
        label: "Steps per second",
        data: steps.map((p) => ({ x: p.step, y: p.steps_per_s })),
        borderColor: COLLECTIVE_COLOR.alltoall,
        backgroundColor: COLLECTIVE_COLOR.alltoall,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
      },
    ],
  };
  const options: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "nearest", axis: "x", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => (items[0] ? `Step ${items[0].parsed.x}` : ""),
          label: (item) => {
            const p = steps[item.dataIndex];
            return `${Number(item.parsed.y).toFixed(3)} steps/s (${p ? p.step_time_s.toFixed(2) : "?"} s/step)`;
          },
        },
      },
    },
    scales: {
      x: {
        type: "linear",
        title: { display: true, text: "Training step", color: c.text },
        ticks: { color: c.text, maxTicksLimit: 10 },
        grid: { color: c.grid },
      },
      y: {
        min: 0,
        suggestedMax: top,
        title: { display: true, text: "Steps per second", color: c.text },
        ticks: { color: c.text },
        grid: { color: c.grid },
      },
    },
  };
  return (
    <div style={{ height: 260 }} data-testid="llm-chart">
      <Line data={data} options={options} aria-label="Training steps per second" />
    </div>
  );
}
