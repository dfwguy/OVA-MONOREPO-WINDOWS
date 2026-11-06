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
 * A Kaizen token's computed colour, for Chart.js, which paints on a canvas and cannot read CSS
 * variables itself. Falls back when the token is missing (a test, an unstyled shell).
 *
 * Shared by every feature that charts on a canvas (the cluster forecast, the handover reports).
 */
export function tokenColor(token: string, fallback: string): string {
  const name = /var\((--[^)]+)\)/.exec(token)?.[1] ?? token;
  if (typeof window === "undefined" || !name.startsWith("--")) return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}
