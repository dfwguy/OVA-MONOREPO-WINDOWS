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
import { MemoryRouter } from "react-router-dom";
import { PENDING_RUN, RUNS } from "../__fixtures__/handover";
import { HandoverReportsView } from "./HandoverReportsView";

const service = vi.hoisted(() => ({
  fetchHandoverRuns: vi.fn(),
  fetchHandoverRun: vi.fn(),
  downloadHandoverReport: vi.fn(),
}));
vi.mock("../services/handoverService", () => service);
const navigate = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useNavigate: () => navigate }));

afterEach(() => {
  vi.clearAllMocks();
});

const renderView = () => render(<MemoryRouter><HandoverReportsView /></MemoryRouter>);

describe("HandoverReportsView", () => {
  it("lists the runs with what each measured, titled with the cluster", async () => {
    service.fetchHandoverRuns.mockResolvedValue(RUNS);
    renderView();
    expect(await screen.findByText("NscaleTX-NC · Handover reports")).toBeInTheDocument();
    expect(screen.getByText("221301")).toBeInTheDocument();
    expect(screen.getByText("676.1")).toBeInTheDocument();
    expect(screen.getByText("nemotronh 56b")).toBeInTheDocument();
    expect(screen.getByTestId("handover-shown")).toHaveTextContent("2 of 2 runs");
  });

  it("filters by search and opens a run", async () => {
    service.fetchHandoverRuns.mockResolvedValue(RUNS);
    renderView();
    await screen.findByText("221301");
    fireEvent.change(screen.getByRole("textbox", { name: "Search runs" }), { target: { value: "nemotron" } });
    expect(screen.getByTestId("handover-shown")).toHaveTextContent("1 of 2 runs");
    fireEvent.click(screen.getByRole("button", { name: /View/ }));
    expect(navigate).toHaveBeenCalledWith("/analytics/handover-reports/e9cdd5d8-ba9c-4211-9bc2-ae80554bfdcc");
  });

  it("builds one report over the selected runs", async () => {
    service.fetchHandoverRuns.mockResolvedValue(RUNS);
    service.downloadHandoverReport.mockResolvedValue(undefined);
    renderView();
    await screen.findByText("221301");
    const report = screen.getByRole("button", { name: /Select runs for a report/ });
    expect(report).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select run 221301" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select run 221238" }));
    fireEvent.click(screen.getByRole("button", { name: /Report for 2 selected/ }));
    await waitFor(() =>
      expect(service.downloadHandoverReport).toHaveBeenCalledWith([RUNS.runs[0].activity_id, RUNS.runs[1].activity_id]),
    );
  });

  it("shows a run being summarized and refreshes until it is done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    service.fetchHandoverRuns
      .mockResolvedValueOnce({ ...RUNS, runs: [PENDING_RUN], backfill: { running: true, done: 3, total: 10, error: "" } })
      .mockResolvedValue(RUNS);
    renderView();
    expect(await screen.findByTestId("handover-backfill")).toHaveTextContent("3 of 10 logs");
    expect(screen.getByText("summarizing…")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(5_100);
    expect(await screen.findByText("221301")).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("says why when the list cannot load", async () => {
    service.fetchHandoverRuns.mockRejectedValue(new Error("HTTP 500"));
    renderView();
    expect(await screen.findByText("HTTP 500")).toBeInTheDocument();
  });
});
