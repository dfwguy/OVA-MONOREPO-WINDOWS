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
 * The handover dataset as `/api/handover-reports` serves it (backend/handover_report.py).
 */

export type Collective = "all_reduce" | "alltoall" | "all_gather" | "reduce_scatter";

export type RunType = "nccl" | "llm" | "both" | "none";

/** `ready` summarized; `pending` finished, being summarized; `running` still writing its logs. */
export type SummaryState = "ready" | "pending" | "running" | "no_logs";

export interface CollectiveSummary {
  busbw_peak_gbps: number | null;
  busbw_2g_gbps: number | null;
  max_size_bytes: number | null;
}

export interface LlmSummary {
  model: string;
  model_size: string;
  dtype: string;
  global_batch: number | null;
  step_time_s: number | null;
  tflops_per_gpu: number | null;
  mfu_percent: number | null;
  steps: number | null;
  declared_steps: number | null;
  finished: boolean;
}

export interface HandoverRun {
  activity_id: string;
  created_at: string | null;
  finished_at: string | null;
  /** The scheduler job's own start and end; finished_at is when the launcher returned. */
  job_started_at?: string | null;
  job_ended_at?: string | null;
  tool: string;
  stage: string;
  operator: string;
  racks: string[];
  scalable_units: string[];
  scheduler_job_ids: string[];
  outcome: string;
  summary_state: SummaryState;
  run_type: RunType;
  nodes: number | null;
  gpus: number | null;
  collectives: Partial<Record<Collective, CollectiveSummary>>;
  llm: LlmSummary | null;
}

export interface SiteContext {
  project: string;
  cluster: string;
  platform: string;
  gpu_model: string;
}

export interface BackfillStatus {
  running: boolean;
  done: number;
  total: number;
  error: string;
}

export interface HandoverRunsResponse {
  ok: boolean;
  site: SiteContext;
  scalable_units: string[];
  runs: HandoverRun[];
  backfill: BackfillStatus;
}

export interface CurvePoint {
  size_bytes: number;
  busbw_gbps: number;
}

export interface StepPoint {
  step: number;
  step_time_s: number;
  steps_per_s: number;
}

export interface StatedSettings {
  env: Record<string, string>;
  per_collective: Record<string, Record<string, string>>;
  forwarded: string[];
  nccl_version: string;
  sizes: string;
  rounds: number | null;
  collectives: string[];
  model_args: string;
  extra_args: string;
}

export interface NodeRow {
  host: string;
  rack: string;
  ip: string;
  /** Bring-up job -> its metric (busbw GB/s) or status word (NOT_RUN, FAIL, ...). */
  bringup: Record<string, string>;
}

/** `collecting` in the background; `not_collected` for a run still going; `none` with no roster. */
export type NodeFactsState = "ready" | "collecting" | "not_collected" | "none";

export interface NodeFacts {
  state: NodeFactsState;
  collected_at: string;
  bringup_jobs: string[];
  bringup_error: string;
}

export interface NcclCommand {
  collective: Collective;
  /** `stated`: the job printed it; `reconstructed`: rebuilt from an older job's log. */
  source: "stated" | "reconstructed";
  env: Record<string, string>;
  ld_library_path: string;
  command: string;
}

/**
 * All-to-all against the most it could reach on this run's racks:
 * ceiling = nic_gbps x (N - 1) / (N - gpus_per_rack), nic_gbps measured by the nodes' own bring-up.
 */
export interface AlltoallCeiling {
  nic_gbps: number;
  nic_min_gbps: number;
  nic_min_host: string;
  nic_nodes: number;
  gpus_per_rack: number;
  ceiling_gbps: number;
  busbw_2g_gbps: number | null;
  pct_2g: number | null;
  busbw_peak_gbps: number | null;
  pct_peak: number | null;
  max_size_bytes: number | null;
  /** Scalable unit -> how many of the run's racks it holds. */
  su_racks: Record<string, number>;
}

/** One scalable unit the run touched, drawn whole: racks in floor order, nodes in tray order. */
export interface FloorPlanUnit {
  su: string;
  racks: { rack: string; in_run: boolean; nodes: { host: string; used: boolean }[] }[];
}

export interface HandoverRunDetail extends HandoverRun {
  site: SiteContext;
  rack_su: Record<string, string>;
  logs: { path: string; scanned: boolean; bytes: number | null }[];
  nccl_curves: Partial<Record<Collective, CurvePoint[]>>;
  llm_steps: StepPoint[];
  settings: { launch_env: Record<string, string>; stated: StatedSettings };
  statements: string[];
  command: { launcher: string; submitted: string[] };
  nccl_commands: NcclCommand[];
  error_summary: string;
  node_rows: NodeRow[];
  floor_plan: FloorPlanUnit[];
  /** Null without bring-up's per-node NIC measurement, or for a run inside one rack. */
  alltoall_ceiling: AlltoallCeiling | null;
  node_facts: NodeFacts;
}
