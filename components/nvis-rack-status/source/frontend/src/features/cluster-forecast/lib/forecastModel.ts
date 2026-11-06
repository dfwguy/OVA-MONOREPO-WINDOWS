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
 * Presentation rules for the cluster forecast: labels, colours, dates.
 *
 * The colours are the deployment tracker's, so the two reports read as one family: passed is the
 * tracker's completed green, the open work its remediation red, onboarding its not-started track,
 * handed over its teal. The model itself -- what passed means, how a date is projected -- is the
 * backend's, and arrives in `meta`.
 */
import { STATE_COLOR, STATE_TEXT, formatCount, formatUtc } from "../../deployment-tracker/lib/trackerModel";
import type { ClusterForecastReport, ForecastUnit, UnitPhase } from "../types";

export { formatCount, formatUtc };

export const PHASE_LABEL: Record<UnitPhase, string> = {
  validating: "Validating",
  onboarding: "Not started",
  handed_over: "Handed over",
};

export const PHASE_TAG: Record<UnitPhase, "yellow" | "gray" | "teal"> = {
  validating: "yellow",
  onboarding: "gray",
  handed_over: "teal",
};

/** The two scenarios, in the order and colours every table, chart and legend uses. */
export const SCENARIOS = [
  { key: "current_pace", label: "Current pace", color: "var(--color-green-300)", text: STATE_TEXT.completed },
  { key: "slowing_tail", label: "Slowing tail", color: "var(--color-yellow-200)", text: STATE_TEXT.in_progress },
] as const;

export type ScenarioKey = (typeof SCENARIOS)[number]["key"];

export const PASSED_COLOR = STATE_COLOR.completed;
export const PASSED_TEXT = STATE_TEXT.completed;
export const OPEN_COLOR = STATE_COLOR.remediation;
export const OPEN_TEXT = STATE_TEXT.remediation;
export const TRACK_COLOR = STATE_COLOR.not_started;
export const HANDED_COLOR = STATE_COLOR.handed_over;
export const HANDED_TEXT = STATE_TEXT.handed_over;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * An ISO date (`2026-11-07`) as the page prints it: "Nov 7", with the year only when it is not
 * the year the forecast was made. Parsed by hand, because `new Date("2026-11-07")` is UTC midnight
 * and prints as the day before anywhere west of Greenwich.
 */
export function formatDay(iso: string | null | undefined, referenceYear?: number): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  const [, y, mo, d] = m;
  const label = `${MONTHS[Number(mo) - 1]} ${Number(d)}`;
  return referenceYear !== undefined && Number(y) !== referenceYear ? `${label}, ${y}` : label;
}

/** The year the forecast was made, which a date in it is printed relative to. */
export function reportYear(report: ClusterForecastReport): number {
  const y = Number((report.meta.generated_at || "").slice(0, 4));
  return Number.isFinite(y) && y > 0 ? y : new Date().getUTCFullYear();
}

/** A share 0..1 as a whole percentage rounded down, so 99.6% never reads as finished. */
export function formatShare(n: number, total: number): string {
  if (!total) return "0%";
  const pct = (100 * n) / total;
  if (pct > 0 && pct < 1) return `${pct.toFixed(1)}%`;
  return `${Math.floor(pct)}%`;
}

export function formatRate(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined || !Number.isFinite(n) ? "—" : n.toFixed(digits);
}

/** How a unit's date cell reads: a date, or what stands in for one. */
export function unitDate(unit: ForecastUnit, key: ScenarioKey, year: number): string {
  if (unit.phase === "handed_over") return "Handed over";
  if (unit.phase === "onboarding") return "Not started";
  if (unit.complete) return "Complete";
  return formatDay(unit[key], year);
}

/**
 * Validating groups first, then those not started, then those handed over; within each, SUs in
 * number order before the racks no SU holds and a pool.
 */
export function orderedUnits(units: ForecastUnit[]): ForecastUnit[] {
  const rank: Record<UnitPhase, number> = { validating: 0, onboarding: 1, handed_over: 2 };
  const kindRank = (u: ForecastUnit) => (u.kind === "su" ? 0 : 1);
  const num = (u: ForecastUnit) => Number(/\d+/.exec(u.unit)?.[0] ?? Number.MAX_SAFE_INTEGER);
  return [...units].sort(
    (a, b) => rank[a.phase] - rank[b.phase] || kindRank(a) - kindRank(b) || num(a) - num(b) || a.unit.localeCompare(b.unit),
  );
}

/** The one-line description both shells put under their title. */
export function forecastSubtitle(report: ClusterForecastReport): string {
  const s = report.summary;
  const parts = [`Validation forecast`, `${formatCount(s.nodes)} nodes`];
  if (report.shape.has_units) {
    const handed = s.handed_over.units ? ` · ${s.handed_over.units} handed over` : "";
    parts.push(`${s.units} scalable unit${s.units === 1 ? "" : "s"} validating${handed}`);
  }
  if (report.shape.has_racks) parts.push(`${formatCount(s.racks)} racks`);
  parts.push(`data as of ${formatUtc(report.meta.generated_at)}`);
  return parts.join(" · ");
}

/** The milestone the headline quotes: everything done, under each scenario. */
export function finishLine(report: ClusterForecastReport): {
  /** What "done" means on this cluster, e.g. "Every rack and SU complete". */
  label: string;
  current_pace: string;
  slowing_tail: string;
  reached: boolean;
  /** The year a date falls in when it is not the forecast's own, for a caption; empty otherwise. */
  current_pace_year: string;
  slowing_tail_year: string;
} {
  const all = report.milestones.find((m) => m.id === "all");
  const year = reportYear(report);
  const yearOf = (iso: string | null | undefined) => {
    const y = (iso || "").slice(0, 4);
    return y && Number(y) !== year ? y : "";
  };
  return {
    label: report.shape.finish.label,
    reached: Boolean(all?.reached),
    current_pace: formatDay(all?.current_pace ?? null),
    slowing_tail: formatDay(all?.slowing_tail ?? null),
    current_pace_year: yearOf(all?.current_pace),
    slowing_tail_year: yearOf(all?.slowing_tail),
  };
}
