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
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { FORECAST } from "../__fixtures__/forecast";
import { StaticForecastPage } from "../static/StaticForecastPage";
import { ClusterForecast } from "./ClusterForecast";

// Canvas charts do not render in jsdom; the page around them is what is under test.
vi.mock("react-chartjs-2", () => ({ Line: () => null }));

describe("ClusterForecast", () => {
  it("leads with where it stands and when it finishes under each scenario", () => {
    render(<ClusterForecast report={FORECAST} />);
    expect(screen.getByTestId("kpi-nodes")).toHaveTextContent("82");
    expect(screen.getByTestId("kpi-racks")).toHaveTextContent("3");
    // SU20 validated plus SU19 handed over: a delivered SU counts, as it does on the tracker.
    expect(screen.getByTestId("kpi-units")).toHaveTextContent("2");
    expect(screen.getByText("of 4 · 1 handed over")).toBeInTheDocument();
    expect(screen.getByTestId("kpi-remaining")).toHaveTextContent("26");
    expect(screen.getByTestId("kpi-pace")).toHaveTextContent("2.0");
    expect(screen.getByTestId("kpi-finish_current")).toHaveTextContent("Nov 7");
    expect(screen.getByTestId("kpi-finish_tail")).toHaveTextContent(/^Jan 13$/);
    expect(screen.getByText("2027 · every rack and SU complete")).toBeInTheDocument();
    expect(screen.getByTestId("forecast-takeaway")).toHaveTextContent("half the SUs finish by Nov 10");
  });

  it("marks a reached milestone instead of dating it", () => {
    render(<ClusterForecast report={FORECAST} />);
    expect(screen.getByTestId("milestone-unit_first")).toHaveTextContent("Reached");
    const every = screen.getByTestId("milestone-nodes_all");
    expect(every).toHaveTextContent("Nov 5");
    // The slowing tail never reaches zero, so "every node" has no date under it.
    expect(every).toHaveTextContent("Not projected");
  });

  it("lists units validating first, and opens one to the racks it waits on", () => {
    render(<ClusterForecast report={FORECAST} />);
    const table = screen.getByRole("table", { name: "Scalable units" });
    const rows = within(table).getAllByTestId(/^unit-/).map((r) => r.getAttribute("data-testid"));
    expect(rows).toEqual(["unit-su20", "unit-su21", "unit-su22", "unit-su1", "unit-su19"]);
    expect(screen.getByTestId("unit-su20")).toHaveTextContent("Complete");
    expect(screen.getByTestId("unit-su1")).toHaveTextContent("Not started");
    expect(screen.getByTestId("unit-su19")).toHaveTextContent("Handed over");

    expect(within(table).queryByText("Q8 · 18")).not.toBeInTheDocument();
    fireEvent.click(within(table).getByRole("button", { name: "Expand SU22" }));
    expect(within(table).getByText("Q8 · 18")).toBeInTheDocument();
    expect(within(table).getByText("Q9 · 7")).toBeInTheDocument();
    // Units not validating have nothing to open.
    expect(within(table).queryByRole("button", { name: "Expand SU1" })).not.toBeInTheDocument();
  });

  it("says why there are no dates rather than inventing them", () => {
    const thin = {
      ...FORECAST,
      pace: { ...FORECAST.pace, enough_history: false, reason: "No sample from 1 to 7 days ago covers today's 108 nodes." },
      milestones: FORECAST.milestones.map((m) => ({ ...m, current_pace: null, slowing_tail: null })),
      projection: [],
    };
    render(<ClusterForecast report={thin} />);
    expect(screen.getAllByText(/No sample from 1 to 7 days ago/).length).toBeGreaterThan(0);
    expect(screen.getByTestId("kpi-pace")).toHaveTextContent("—");
    expect(screen.queryByTestId("forecast-takeaway")).not.toBeInTheDocument();
  });

  it("says what the sampler did last, and that only the active cluster is sampled", () => {
    render(<ClusterForecast report={FORECAST} />);
    expect(screen.getByTestId("forecast-last-check")).toHaveTextContent("Not due yet.");
    expect(screen.getByTestId("forecast-last-check")).toHaveTextContent("samples only the active cluster");
    expect(screen.queryByTestId("forecast-no-stage2")).not.toBeInTheDocument();
  });

  it("forecasts a pool by its nodes alone: no rack or SU tiles, sections or columns", () => {
    const pool = {
      ...FORECAST,
      meta: { ...FORECAST.meta, stage2_available: false, rack_run_days: 0 },
      shape: {
        has_racks: false,
        has_units: false,
        group_label: "Group",
        finish: { label: "Every node passed", phrase: "every node has passed" },
      },
      units: [{ ...FORECAST.units[1], unit: "__unplaced", label: "Pool", kind: "pool" as const, racks: 0, racks_passed: 0, open_racks: [] }],
      milestones: FORECAST.milestones.filter((m) => m.id.startsWith("nodes_95") || m.id === "all"),
      rack_buckets: [],
    };
    render(<ClusterForecast report={pool} />);
    expect(screen.queryByTestId("kpi-racks")).not.toBeInTheDocument();
    expect(screen.queryByTestId("kpi-units")).not.toBeInTheDocument();
    expect(screen.getByText("By group")).toBeInTheDocument();
    expect(screen.queryByText("Racks passed")).not.toBeInTheDocument();
    expect(screen.queryByText("What the open racks are waiting on")).not.toBeInTheDocument();
    expect(screen.getByTestId("forecast-takeaway")).toHaveTextContent("At the current pace every node has passed by Nov 7");
    expect(screen.getByTestId("forecast-takeaway")).toHaveTextContent("the last of it lands around Jan 13, 2027");
    // No Stage 2 source on this cluster, and the page says what that means.
    expect(screen.getByTestId("forecast-no-stage2")).toHaveTextContent("a node passes on Stage 1 alone");
  });

  it("names the units that have not started and leaves them undated", () => {
    render(<ClusterForecast report={FORECAST} />);
    expect(screen.getByText(/1 scalable unit \(36 nodes, 2 racks\) is placed in the cluster/)).toBeInTheDocument();
  });

  it("publishes the same body under a static header, and an empty state without data", () => {
    render(<StaticForecastPage report={FORECAST} />);
    expect(screen.getByText("Nscale NC · Cluster Forecast")).toBeInTheDocument();
    expect(screen.getByTestId("kpi-nodes")).toHaveTextContent("82");

    render(<StaticForecastPage report={null} />);
    expect(screen.getByText("No forecast data in this page")).toBeInTheDocument();
  });
});
