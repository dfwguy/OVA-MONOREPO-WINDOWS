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
import type { ClusterForecastReport, ForecastUnit } from "../types";

function unit(partial: Partial<ForecastUnit> & Pick<ForecastUnit, "unit">): ForecastUnit {
  return {
    label: partial.unit.toUpperCase(),
    kind: "su",
    phase: "validating",
    handed_over_at: "",
    nodes: 36,
    nodes_passed: 36,
    nodes_failing: 0,
    nodes_missing: 0,
    racks: 2,
    racks_passed: 2,
    complete: false,
    open_racks: [],
    current_pace: null,
    slowing_tail: null,
    ...partial,
  };
}

/**
 * Three scalable units validating (one complete, one a rack short, one with a held rack), one not
 * started and one handed over -- the shapes the page has to tell apart.
 */
export const FORECAST: ClusterForecastReport = {
  meta: {
    cluster: "Nscale NC",
    project: "Nscale",
    generated_at: "2026-10-23T14:37:00+00:00",
    snapshot_at: "2026-10-23T14:36:30+00:00",
    stage2_loading: false,
    rack_run_days: 1,
    definitions: {
      node_passed: "Both node stages passed.",
      rack_passed: "Rack Stage 2 passed.",
    },
    scenarios: {
      current_pace: "Repairs keep returning nodes at the measured daily rate.",
      slowing_tail: "The backlog keeps shrinking by the same fraction each day.",
    },
    stage2_available: true,
    stage2_source: "bringup:llm-pretrain-solo",
    sampling: {
      interval_sec: 3600,
      last_sample_at: "2026-10-23T14:00:00Z",
      last_check: { at: "2026-10-23T14:30:00+00:00", outcome: "Not due yet." },
      observes: "active cluster only",
    },
  },
  shape: {
    has_racks: true,
    has_units: true,
    group_label: "Scalable unit",
    finish: { label: "Every rack and SU complete", phrase: "every rack and SU is done" },
  },
  summary: {
    units: 3,
    nodes: 108,
    nodes_passed: 82,
    nodes_remaining: 26,
    nodes_failing: 9,
    racks: 6,
    racks_passed: 3,
    units_complete: 1,
    onboarding: { units: 1, nodes: 36, racks: 2 },
    handed_over: { units: 1, nodes: 18, racks: 1 },
  },
  pace: {
    enough_history: true,
    reason: "",
    window_days: 7,
    from: "2026-10-16T15:58+00:00",
    to: "2026-10-23T14:37+00:00",
    days: 6.94,
    remaining_from: 40,
    remaining_to: 26,
    nodes_per_day: 2.02,
    mean_days: 16.1,
    half_life_days: 11.16,
    racks_from: 1,
    racks_to: 3,
    racks_per_day: 0.29,
    baseline_source: "import",
  },
  milestones: [
    { id: "unit_first", label: "First SU complete", reached: true, current_pace: null, slowing_tail: null },
    { id: "racks_half", label: "Half of racks passed", reached: true, current_pace: null, slowing_tail: null },
    { id: "nodes_95", label: "95% of nodes passed", reached: false, current_pace: "2026-11-02", slowing_tail: "2026-11-25" },
    { id: "units_half", label: "Half of SUs complete", reached: false, current_pace: "2026-10-30", slowing_tail: "2026-11-10" },
    { id: "nodes_all", label: "Every node passed", reached: false, current_pace: "2026-11-05", slowing_tail: null },
    { id: "all", label: "Every rack and SU complete", reached: false, current_pace: "2026-11-07", slowing_tail: "2027-01-13" },
  ],
  units: [
    unit({ unit: "su20", complete: true }),
    unit({
      unit: "su21",
      nodes_passed: 35,
      nodes_failing: 1,
      nodes_missing: 1,
      racks_passed: 1,
      open_racks: [{ rack: "Q20", missing: 1 }],
      current_pace: "2026-10-30",
      slowing_tail: "2026-11-10",
    }),
    unit({
      unit: "su22",
      nodes_passed: 11,
      nodes_failing: 8,
      nodes_missing: 25,
      racks_passed: 0,
      open_racks: [{ rack: "Q8", missing: 18 }, { rack: "Q9", missing: 7 }],
      current_pace: "2026-11-07",
      slowing_tail: "2027-01-13",
    }),
    unit({ unit: "su1", phase: "onboarding", nodes_passed: 0, racks_passed: 0, open_racks: [{ rack: "A2", missing: 18 }, { rack: "A3", missing: 18 }] }),
    unit({ unit: "su19", phase: "handed_over", handed_over_at: "2026-10-17", nodes: 18, nodes_passed: 0, racks: 1, racks_passed: 1 }),
  ],
  rack_buckets: [
    { label: "0", min: 0, max: 0, racks: 0, nodes_missing: 0 },
    { label: "1", min: 1, max: 1, racks: 1, nodes_missing: 1 },
    { label: "2–3", min: 2, max: 3, racks: 0, nodes_missing: 0 },
    { label: "4–9", min: 4, max: 9, racks: 1, nodes_missing: 7 },
    { label: "10+", min: 10, max: 10000, racks: 1, nodes_missing: 18 },
  ],
  projection: [
    { date: "2026-10-23", current_pace: 26, slowing_tail: 26 },
    { date: "2026-10-24", current_pace: 24, slowing_tail: 24.4 },
  ],
  history: [
    { at: "2026-10-16T15:58+00:00", source: "import", nodes: 108, nodes_passed: 68, racks: 6, racks_passed: 1 },
    { at: "2026-10-23T14:37+00:00", source: "now", nodes: 108, nodes_passed: 82, racks: 6, racks_passed: 3 },
  ],
  scope_changes: [],
};
