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
import { apiDownload, apiFetch } from "../../../lib/apiFetch";
import type { HandoverRunDetail, HandoverRunsResponse } from "../types";

export const HANDOVER_URL = "/api/handover-reports";

async function json<T>(url: string): Promise<T> {
  const res = await apiFetch(url, { cache: "no-store" });
  const text = await res.text();
  let payload: Record<string, unknown>;
  try {
    payload = text ? (JSON.parse(text) as Record<string, unknown>) : {};
  } catch {
    throw new Error(`Invalid JSON (HTTP ${res.status}): ${text.slice(0, 240)}`);
  }
  if (!res.ok || payload.ok === false) {
    throw new Error(typeof payload.error === "string" ? payload.error : `HTTP ${res.status}`);
  }
  return payload as T;
}

/** The multi-rack runs, newest first; `su` narrows to runs on that scalable unit. */
export function fetchHandoverRuns(su = ""): Promise<HandoverRunsResponse> {
  const q = su ? `?su=${encodeURIComponent(su)}` : "";
  return json<HandoverRunsResponse>(`${HANDOVER_URL}/runs${q}`);
}

/** One run in full: curves, steps, settings and command. */
export async function fetchHandoverRun(activityId: string): Promise<HandoverRunDetail> {
  const body = await json<{ run: HandoverRunDetail }>(`${HANDOVER_URL}/runs/${encodeURIComponent(activityId)}`);
  return body.run;
}

/** Collect a finished run's per-node bring-up results again, in the background. */
export async function recollectNodeFacts(activityId: string): Promise<void> {
  const res = await apiFetch(`${HANDOVER_URL}/runs/${encodeURIComponent(activityId)}/node-facts`, { method: "POST" });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error || `HTTP ${res.status}`);
  }
}

/** The handover report over these runs, as the PDF on the NVIDIA letterhead. */
export function downloadHandoverReport(activityIds: string[]): Promise<void> {
  const ids = activityIds.map(encodeURIComponent).join(",");
  return apiDownload(`${HANDOVER_URL}/report?ids=${ids}`, "handover-report.pdf");
}
