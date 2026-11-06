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
import type { Collective, CurvePoint, HandoverRun, NcclCommand, RunType } from "../types";

/** The product name a document and page sign with. */
export const PRODUCT = "NVIS Rack Status";

/** The collectives drawn one chart each, over the message sizes acceptance is judged at. */
export const BAND_COLLECTIVES: Collective[] = ["all_reduce", "alltoall", "all_gather"];
const BAND_MIN = 2 * 1024 ** 3;
const BAND_MAX = 16 * 1024 ** 3;

/** Bring-up's own per-node NCCL jobs, as the node table heads them. */
export const BRINGUP_HEADS: Record<string, string> = {
  allreduce: "AR",
  alltoall: "A2A",
  "allreduce-nonvlink": "AR RoCE",
  "alltoall-nonvlink": "A2A RoCE",
};

/** The collectives a handover reports, in the order shown everywhere. */
export const COLLECTIVES: Collective[] = ["all_reduce", "alltoall", "all_gather", "reduce_scatter"];

export const COLLECTIVE_LABEL: Record<Collective, string> = {
  all_reduce: "All-reduce",
  alltoall: "All-to-all",
  all_gather: "All-gather",
  reduce_scatter: "Reduce-scatter",
};

/** Short labels for table headers. */
export const COLLECTIVE_SHORT: Record<Collective, string> = {
  all_reduce: "AR",
  alltoall: "A2A",
  all_gather: "AG",
  reduce_scatter: "RS",
};

/**
 * One hue per collective, fixed order, the same as the PDF: Okabe-Ito hues with NVIDIA green for
 * the headline (all-to-all). Every series also has a legend entry, so identity is never colour alone.
 */
export const COLLECTIVE_COLOR: Record<Collective, string> = {
  alltoall: "#76B900",
  all_reduce: "#0072B2",
  all_gather: "#CC79A7",
  reduce_scatter: "#E69F00",
};

export const RUN_TYPE_LABEL: Record<RunType, string> = {
  nccl: "NCCL",
  llm: "LLM",
  both: "LLM + NCCL preflight",
  none: "No results",
};

export function formatGbps(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "—";
}

/**
 * A message size as the size it stands for. nccl-tests rounds a size to what divides across the
 * ranks, so 17,179,869,180 bytes is "16 GB", not "16777215 KB".
 */
export function formatSize(bytes: number | null | undefined): string {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes <= 0) return "—";
  const units: [string, number][] = [["GB", 1024 ** 3], ["MB", 1024 ** 2], ["KB", 1024]];
  for (const [unit, div] of units) {
    if (bytes >= div * 0.99) {
      const v = bytes / div;
      return Math.abs(v - Math.round(v)) <= 0.01 * v ? `${Math.round(v)} ${unit}` : `${v.toFixed(1)} ${unit}`;
    }
  }
  return `${bytes} B`;
}

/** `2026-10-24 19:27` in UTC: runs are compared across operators in different time zones. */
export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 16)} UTC`;
}

export function modelLabel(run: Pick<HandoverRun, "llm">): string {
  const llm = run.llm;
  if (!llm) return "—";
  return [llm.model, llm.model_size].filter(Boolean).join(" ") || "—";
}

/** Job ids, or the start of the activity id for a run never submitted to the scheduler. */
export function jobLabel(run: Pick<HandoverRun, "scheduler_job_ids" | "activity_id">): string {
  return run.scheduler_job_ids.join(", ") || run.activity_id.slice(0, 8);
}

/** A curve's points from 2 GB to 16 GB (nccl-tests rounds sizes, so 1% either way still counts). */
export function bandPoints(points: CurvePoint[] | undefined): CurvePoint[] {
  return (points ?? []).filter((p) => p.size_bytes >= BAND_MIN * 0.99 && p.size_bytes <= BAND_MAX * 1.01);
}

/** A percentage of the all-to-all ceiling, to one decimal (as the PDF prints it). */
export function formatPct(value: number | null | undefined): string {
  return typeof value === "number" ? `${value.toFixed(1)}%` : "—";
}

/** Racks per scalable unit, as "SU20 x6, SU23 x2". */
export function formatSuRacks(suRacks: Record<string, number>): string {
  return Object.entries(suRacks).map(([su, n]) => `${su} x${n}`).join(", ") || "—";
}

/** One collective's program as shell lines: its exports, then the command. */
export function commandBlock(cmd: NcclCommand): string {
  const lines = [`# ${COLLECTIVE_LABEL[cmd.collective] ?? cmd.collective} (${cmd.source})`];
  if (cmd.ld_library_path) lines.push(`export LD_LIBRARY_PATH=${cmd.ld_library_path}`);
  for (const [k, v] of Object.entries(cmd.env)) lines.push(`export ${k}=${v === "" ? "<not recorded>" : v}`);
  lines.push(cmd.command);
  return lines.join("\n");
}

/** The launcher line with its node list summarized: the nodes are tabled beside it. */
export function shortNodelist(command: string): string {
  return command.replace(/--nodelist\s+(\S+)/, (_m, list: string) => `--nodelist <${list.split(",").length} nodes, see Nodes>`);
}

/** Runs matching a free-text filter on racks, SUs, job ids, model and tool. */
export function matchesQuery(run: HandoverRun, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const hay = [
    ...run.racks,
    ...run.scalable_units,
    ...run.scheduler_job_ids,
    run.tool,
    run.llm?.model ?? "",
    run.activity_id,
  ]
    .join(" ")
    .toLowerCase();
  return q.split(/\s+/).every((term) => hay.includes(term));
}
