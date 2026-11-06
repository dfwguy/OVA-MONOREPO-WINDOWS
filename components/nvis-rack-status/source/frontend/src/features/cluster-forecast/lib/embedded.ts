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
import type { ClusterForecastReport } from "../types";

/** The id of the element `backend/cluster_forecast.py` writes the dataset into. */
export const DATA_ELEMENT_ID = "forecast-data";

/**
 * The dataset embedded in the static page, or `null` when there is none (an unexported bundle
 * opened directly) or it is not a forecast dataset. Never throws: the page shows an empty state.
 */
export function readEmbeddedForecast(doc: Document): ClusterForecastReport | null {
  const text = doc.getElementById(DATA_ELEMENT_ID)?.textContent?.trim();
  if (!text) return null;
  try {
    const data = JSON.parse(text) as unknown;
    if (!data || typeof data !== "object") return null;
    const r = data as Partial<ClusterForecastReport>;
    return r.meta && r.summary && r.pace && r.shape && Array.isArray(r.units) && Array.isArray(r.milestones)
      ? (r as ClusterForecastReport)
      : null;
  } catch {
    return null;
  }
}
