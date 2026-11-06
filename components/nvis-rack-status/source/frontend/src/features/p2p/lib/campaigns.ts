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
// What a campaign is made of, shared by the two places that author one: the Campaigns editor and
// the New campaign wizard on the Artifact Distribution page. One definition, so a field added to a
// campaign cannot appear in one and silently default in the other.
//
// A campaign is a task (one catalog image) + a roster (which nodes) + a plan (how to pace it). It
// holds no run state: launching one enqueues a `distribute` operation tagged with its name.
import type { CampaignEdit, RolloutStrategy } from "../services/fleetService";
import type { NodeCoverage, Operation } from "../types/fleet";

export const emptyCampaign = (): CampaignEdit => ({
  name: "", description: "", image: "", roster: "",
  wave_size: 0, parallelism: 0, poll_seconds: 0, max_launches: 0, max_unreachable: 0, timeout_seconds: 0,
  fill_wave_size: 0, stall_seconds: 0, verify_mb_per_second: 0, download_timeout_seconds: 0, strategy: "", stages: [],
});

export const STRATEGY_ITEMS = [
  { value: "inherit", children: "Cluster default" },
  { value: "sequential", children: "Sequential" },
  { value: "rack-staged", children: "Rack-staged" },
];

/** The words a person reads for a campaign's wave plan; blank means the cluster's own. */
export function strategyLabel(strategy: "" | RolloutStrategy): string {
  return strategy === "rack-staged" ? "Rack-staged" : strategy === "sequential" ? "Sequential" : "Cluster default";
}

/** The pacing knobs a campaign may override; 0 inherits the cluster's rollout default. */
export const PACING_FIELDS: { key: keyof CampaignEdit; label: string; placeholder: string }[] = [
  { key: "wave_size", label: "Wave size", placeholder: "default" },
  { key: "parallelism", label: "Parallelism", placeholder: "default" },
  { key: "poll_seconds", label: "Poll (s)", placeholder: "default" },
  { key: "max_launches", label: "Max launches", placeholder: "default" },
  { key: "max_unreachable", label: "Max unreachable", placeholder: "default" },
  { key: "timeout_seconds", label: "Timeout (s)", placeholder: "default" },
  { key: "stall_seconds", label: "Stall (s)", placeholder: "default" },
  { key: "verify_mb_per_second", label: "Verify rate (MB/s)", placeholder: "default" },
  { key: "download_timeout_seconds", label: "Download limit (s)", placeholder: "default" },
];

/** The pacing overrides a campaign sets, as "Label value" pairs, for a review or a summary. */
export function pacingOverrides(campaign: CampaignEdit): string[] {
  return PACING_FIELDS.filter((f) => Number(campaign[f.key]) > 0).map((f) => `${f.label} ${campaign[f.key]}`);
}

/** Why a campaign cannot be saved under this name, or null when it can. Mirrors the backend's rules. */
export function campaignNameProblem(name: string, taken: readonly string[]): string | null {
  const trimmed = name.trim();
  if (!trimmed) return "A campaign needs a name.";
  if (taken.includes(trimmed)) return `A campaign named "${trimmed}" already exists.`;
  return null;
}

/** The newest operation a campaign launched, or null if it has never run. */
export function lastRun(operations: readonly Operation[], campaign: string): Operation | null {
  const runs = operations.filter((op) => op.campaign === campaign);
  if (!runs.length) return null;
  return [...runs].sort((a, b) => b.started_at.localeCompare(a.started_at))[0];
}

/** Of *nodes*, how many hold *image* verified (state "ready" in the snapshot). */
export function holders(nodes: readonly NodeCoverage[], image: string): number {
  return nodes.reduce((n, node) => n + (node.images[image] === "ready" ? 1 : 0), 0);
}
