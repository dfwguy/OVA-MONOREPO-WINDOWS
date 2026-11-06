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
import type { HandoverRun, HandoverRunDetail, HandoverRunsResponse } from "../types";

const GIB = 1024 ** 3;

export const NCCL_RUN: HandoverRun = {
  activity_id: "3989e310-02de-47b9-95ef-7648ec8f5c19",
  created_at: "2026-10-24T19:27:34+00:00",
  finished_at: "2026-10-24T19:27:39+00:00",
  job_started_at: "2026-10-24T19:27:44+00:00",
  job_ended_at: "2026-10-24T19:40:22+00:00",
  tool: "llmb-nccl",
  stage: "stage1",
  operator: "admin",
  racks: ["U2", "W19"],
  scalable_units: ["SU20", "SU27"],
  scheduler_job_ids: ["221301"],
  outcome: "passed",
  summary_state: "ready",
  run_type: "nccl",
  nodes: 36,
  gpus: 144,
  collectives: {
    all_reduce: { busbw_peak_gbps: 792.8, busbw_2g_gbps: 676.1, max_size_bytes: 16 * GIB },
    alltoall: { busbw_peak_gbps: 140.6, busbw_2g_gbps: 138.2, max_size_bytes: 17179869180 },
  },
  llm: null,
};

export const LLM_RUN: HandoverRun = {
  ...NCCL_RUN,
  activity_id: "e9cdd5d8-ba9c-4211-9bc2-ae80554bfdcc",
  created_at: "2026-10-24T15:27:00+00:00",
  tool: "nemo-xrack",
  racks: ["R4", "W24"],
  scalable_units: ["SU26", "SU27"],
  scheduler_job_ids: ["221238"],
  run_type: "both",
  collectives: { all_gather: { busbw_peak_gbps: 291.0, busbw_2g_gbps: 280.5, max_size_bytes: 16 * GIB } },
  llm: {
    model: "nemotronh",
    model_size: "56b",
    dtype: "fp8_cs",
    global_batch: 432,
    step_time_s: 4.16,
    tflops_per_gpu: 1980.0,
    mfu_percent: 39.6,
    steps: 50,
    declared_steps: 50,
    finished: true,
  },
};

export const PENDING_RUN: HandoverRun = {
  ...NCCL_RUN,
  activity_id: "pending-0001",
  scheduler_job_ids: ["221400"],
  summary_state: "pending",
  run_type: "none",
  collectives: {},
  gpus: null,
};

export const RUNS: HandoverRunsResponse = {
  ok: true,
  site: { project: "Nscale", cluster: "NscaleTX-NC", platform: "GB300 NVL72", gpu_model: "GB300" },
  scalable_units: ["SU20", "SU26", "SU27"],
  runs: [NCCL_RUN, LLM_RUN],
  backfill: { running: false, done: 0, total: 0, error: "" },
};

export const DETAIL: HandoverRunDetail = {
  ...LLM_RUN,
  site: RUNS.site,
  rack_su: { R4: "SU26", W24: "SU27" },
  logs: [{ path: "/home/cmods/nvis/logs/root-NEMO-R4+W24-36N-221238.txt", scanned: true, bytes: 15885109 }],
  nccl_curves: {
    all_gather: [
      { size_bytes: GIB, busbw_gbps: 250.1 },
      { size_bytes: 2 * GIB, busbw_gbps: 280.5 },
    ],
  },
  llm_steps: [
    { step: 1, step_time_s: 95.5, steps_per_s: 0.0105 },
    { step: 2, step_time_s: 4.2, steps_per_s: 0.2381 },
  ],
  settings: {
    launch_env: { NCCL_IB_QPS_PER_CONNECTION: "4", HF_TOKEN: "[REDACTED]" },
    stated: {
      env: { NCCL_IB_HCA: "roce_vf_r", UCX_TLS: "tcp" },
      per_collective: { alltoall: { NCCL_BUFFSIZE: "8388608" } },
      forwarded: ["NCCL_BUFFSIZE"],
      nccl_version: "2.30.7",
      sizes: "8..16G",
      rounds: 1,
      collectives: ["all_reduce", "alltoall"],
      model_args: "--model_family_name nemotronh",
      extra_args: "-tp 2 -gb 432",
    },
  },
  statements: [],
  command: { launcher: "./run-nemo-xrack.sh --nodelist gpu1-su26,gpu1-su27 R4 W24", submitted: [] },
  nccl_commands: [
    {
      collective: "all_gather",
      source: "reconstructed",
      env: { NCCL_IB_HCA: "roce_vf_r", UCX_TLS: "" },
      ld_library_path: "/opt/nccl/lib",
      command: "mpirun -np 144 --hostfile hosts -x NCCL_IB_HCA -x UCX_TLS /opt/nccl-tests/build/all_gather_perf -b 2G -e 16G -f 2 -g 1",
    },
  ],
  error_summary: "",
  node_rows: [
    {
      host: "gpu1-su26",
      rack: "R4",
      ip: "192.0.2.26",
      bringup: { allreduce: "219.6", alltoall: "190.9", "allreduce-nonvlink": "46.1", "alltoall-nonvlink": "NOT_RUN" },
    },
    { host: "gpu1-su27", rack: "W24", ip: "", bringup: {} },
  ],
  floor_plan: [
    {
      su: "SU26",
      racks: [
        { rack: "R3", in_run: false, nodes: [{ host: "gpu0-su26", used: false }] },
        { rack: "R4", in_run: true, nodes: [{ host: "gpu1-su26", used: true }, { host: "gpu2-su26", used: false }] },
      ],
    },
  ],
  alltoall_ceiling: {
    nic_gbps: 95.46,
    nic_min_gbps: 83.9,
    nic_min_host: "gpu1-su26",
    nic_nodes: 2,
    gpus_per_rack: 64,
    ceiling_gbps: 108.9,
    busbw_2g_gbps: 81.13,
    pct_2g: 74.5,
    busbw_peak_gbps: 80.2,
    pct_peak: 73.7,
    max_size_bytes: 17179869184,
    su_racks: { SU26: 1, SU27: 1 },
  },
  node_facts: {
    state: "ready",
    collected_at: "2026-10-24T22:00:00+00:00",
    bringup_jobs: ["allreduce", "alltoall", "allreduce-nonvlink", "alltoall-nonvlink"],
    bringup_error: "",
  },
};
