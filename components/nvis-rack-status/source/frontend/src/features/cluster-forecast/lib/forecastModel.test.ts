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
import { describe, expect, it } from "vitest";
import { FORECAST } from "../__fixtures__/forecast";
import { readEmbeddedForecast } from "./embedded";
import { finishLine, forecastSubtitle, formatDay, formatShare, orderedUnits, unitDate } from "./forecastModel";

/** A document holding the static page's data element with this text in it. */
function readEmbeddedForecastFor(text: string) {
  const doc = document.implementation.createHTMLDocument("forecast");
  const el = doc.createElement("script");
  el.id = "forecast-data";
  el.type = "application/json";
  el.textContent = text;
  doc.body.appendChild(el);
  return readEmbeddedForecast(doc);
}

describe("forecastModel", () => {
  it("prints a date as the calendar day it names, whatever the reader's time zone", () => {
    // new Date("2026-11-07") is UTC midnight and would print Nov 6 west of Greenwich.
    expect(formatDay("2026-11-07", 2026)).toBe("Nov 7");
    expect(formatDay("2027-01-13", 2026)).toBe("Jan 13, 2027");
    expect(formatDay(null, 2026)).toBe("—");
  });

  it("rounds a share down, so a unit one node short never reads finished", () => {
    expect(formatShare(125, 126)).toBe("99%");
    expect(formatShare(1, 400)).toBe("0.3%");
    expect(formatShare(0, 0)).toBe("0%");
  });

  it("says what stands in for a date when a unit has none", () => {
    const [su20, su21, , su1, su19] = FORECAST.units;
    expect(unitDate(su20, "current_pace", 2026)).toBe("Complete");
    expect(unitDate(su21, "slowing_tail", 2026)).toBe("Nov 10");
    expect(unitDate(su1, "current_pace", 2026)).toBe("Not started");
    expect(unitDate(su19, "current_pace", 2026)).toBe("Handed over");
  });

  it("orders validating units by SU number before the rest", () => {
    expect(orderedUnits(FORECAST.units).map((u) => u.unit)).toEqual(["su20", "su21", "su22", "su1", "su19"]);
  });

  it("leaves SUs and racks out of the subtitle on a cluster that has neither", () => {
    const pool = { ...FORECAST, shape: { ...FORECAST.shape, has_racks: false, has_units: false } };
    expect(forecastSubtitle(pool)).not.toMatch(/scalable unit|racks/);
  });

  it("names the handed-over SUs in the subtitle", () => {
    expect(forecastSubtitle(FORECAST)).toContain("3 scalable units validating · 1 handed over");
    const none = { ...FORECAST, summary: { ...FORECAST.summary, handed_over: { units: 0, nodes: 0, racks: 0 } } };
    expect(forecastSubtitle(none)).not.toContain("handed over");
  });

  it("quotes the finish line from the all-complete milestone", () => {
    // The year goes beside the date rather than in it, so a headline tile never wraps.
    expect(finishLine(FORECAST)).toEqual({
      label: "Every rack and SU complete",
      reached: false,
      current_pace: "Nov 7",
      slowing_tail: "Jan 13",
      current_pace_year: "",
      slowing_tail_year: "2027",
    });
  });

  it("reads only a forecast dataset from the static page", () => {
    expect(readEmbeddedForecastFor(JSON.stringify(FORECAST))?.meta.cluster).toBe("Nscale NC");
    expect(readEmbeddedForecastFor("null")).toBeNull();
    expect(readEmbeddedForecastFor('{"meta":{},"summary":{}}')).toBeNull();
    expect(readEmbeddedForecastFor("{not json")).toBeNull();
  });
});
