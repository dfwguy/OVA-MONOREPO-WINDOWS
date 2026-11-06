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
/**
 * The cluster forecast dataset (`GET /api/cluster-forecast`, `backend/cluster_forecast.py`).
 *
 * The same shape reaches the in-app view and the static page published from `site.html`. What a
 * term or a scenario means travels in `meta`, written beside the code that computes it.
 */

export type UnitPhase = "validating" | "onboarding" | "handed_over";

/**
 * What a group is: a scalable unit; the tracker's racks-in-no-SU bucket ("All racks" on a cluster
 * with no SU map), which is real work but never counted as an SU; or a pool cluster's nodes, which
 * have no racks to pass.
 */
export type GroupKind = "su" | "racks" | "pool";

export interface ForecastPace {
  enough_history: boolean;
  /** Why there is no pace, or a note when the work is already done; empty otherwise. */
  reason: string;
  window_days: number;
  from: string | null;
  to: string;
  days: number | null;
  remaining_from: number | null;
  remaining_to: number;
  nodes_per_day: number | null;
  mean_days: number | null;
  half_life_days: number | null;
  racks_from: number | null;
  racks_to: number;
  racks_per_day: number | null;
  baseline_source: "sampler" | "import" | null;
}

export interface ForecastMilestone {
  id: string;
  label: string;
  reached: boolean;
  /** ISO dates; `null` when reached, or when the scenario has no pace to project with. */
  current_pace: string | null;
  slowing_tail: string | null;
}

export interface ForecastOpenRack {
  rack: string;
  missing: number;
}

export interface ForecastUnit {
  unit: string;
  label: string;
  kind: GroupKind;
  phase: UnitPhase;
  handed_over_at: string;
  nodes: number;
  nodes_passed: number;
  nodes_failing: number;
  nodes_missing: number;
  racks: number;
  racks_passed: number;
  complete: boolean;
  open_racks: ForecastOpenRack[];
  current_pace: string | null;
  slowing_tail: string | null;
}

export interface ForecastPhaseTotals {
  units: number;
  nodes: number;
  racks: number;
}

export interface ForecastBucket {
  label: string;
  min: number;
  max: number;
  racks: number;
  nodes_missing: number;
}

export interface ForecastHistoryPoint {
  at: string;
  /** `now` is today's point, computed live rather than read back from a sample. */
  source: "sampler" | "import" | "now";
  nodes: number;
  nodes_passed: number;
  racks: number;
  racks_passed: number;
}

export interface ClusterForecastReport {
  meta: {
    cluster: string;
    project: string;
    generated_at: string;
    snapshot_at: string;
    stage2_loading: boolean;
    /** False on a cluster with no Stage 2 source: a node passes on Stage 1 alone. */
    stage2_available?: boolean;
    stage2_source?: string;
    rack_run_days: number;
    definitions: Record<string, string>;
    scenarios: { current_pace: string; slowing_tail: string };
    sampling?: {
      interval_sec: number;
      last_sample_at: string | null;
      /** The sampler's last check and what came of it, including why it skipped. */
      last_check?: { at: string; outcome: string } | null;
      observes?: string;
    };
  };
  /** What this cluster is made of, which decides the terms and milestones the page can use. */
  shape: {
    has_racks: boolean;
    has_units: boolean;
    group_label: string;
    finish: { label: string; phrase: string };
  };
  summary: {
    units: number;
    nodes: number;
    nodes_passed: number;
    nodes_remaining: number;
    nodes_failing: number;
    racks: number;
    racks_passed: number;
    units_complete: number;
    onboarding: ForecastPhaseTotals;
    handed_over: ForecastPhaseTotals;
  };
  pace: ForecastPace;
  milestones: ForecastMilestone[];
  units: ForecastUnit[];
  rack_buckets: ForecastBucket[];
  projection: { date: string; current_pace: number | null; slowing_tail: number | null }[];
  history: ForecastHistoryPoint[];
  scope_changes: { at: string; from: number; to: number }[];
}

export interface ClusterForecastResponse extends ClusterForecastReport {
  ok: true;
}
