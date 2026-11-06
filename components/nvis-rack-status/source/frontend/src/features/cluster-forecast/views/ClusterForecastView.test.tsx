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
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FORECAST } from "../__fixtures__/forecast";
import { ClusterForecastView } from "./ClusterForecastView";

const service = vi.hoisted(() => ({
  fetchClusterForecast: vi.fn(),
  downloadForecastSite: vi.fn(),
}));
vi.mock("../services/forecastService", () => service);
vi.mock("react-chartjs-2", () => ({ Line: () => null }));

afterEach(() => {
  vi.clearAllMocks();
});

describe("ClusterForecastView", () => {
  it("loads the dataset and titles the page with the cluster", async () => {
    service.fetchClusterForecast.mockResolvedValue({ ok: true, ...FORECAST });
    render(<ClusterForecastView />);
    expect(await screen.findByText("Nscale NC · Cluster forecast")).toBeInTheDocument();
    expect(screen.getByTestId("kpi-nodes")).toHaveTextContent("82");
  });

  it("says why when there is nothing to show yet", async () => {
    service.fetchClusterForecast.mockRejectedValue(new Error("node inventory is still loading; retry shortly"));
    render(<ClusterForecastView />);
    expect(await screen.findByText("node inventory is still loading; retry shortly")).toBeInTheDocument();
  });

  it("keeps the last good data when a refresh fails, and exports the static page", async () => {
    service.fetchClusterForecast.mockResolvedValueOnce({ ok: true, ...FORECAST });
    service.downloadForecastSite.mockResolvedValue(undefined);
    render(<ClusterForecastView />);
    await screen.findByTestId("kpi-nodes");

    service.fetchClusterForecast.mockRejectedValueOnce(new Error("HTTP 502"));
    fireEvent.click(screen.getByRole("button", { name: /Refresh/ }));
    expect(await screen.findByText("Showing the last good data: HTTP 502")).toBeInTheDocument();
    expect(screen.getByTestId("kpi-nodes")).toHaveTextContent("82");

    fireEvent.click(screen.getByRole("button", { name: /Download static page/ }));
    await waitFor(() => expect(service.downloadForecastSite).toHaveBeenCalledTimes(1));
  });
});
