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
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { DETAIL } from "../__fixtures__/handover";
import { HandoverRunView } from "./HandoverRunView";

const service = vi.hoisted(() => ({
  fetchHandoverRuns: vi.fn(),
  fetchHandoverRun: vi.fn(),
  downloadHandoverReport: vi.fn(),
  recollectNodeFacts: vi.fn(),
}));
vi.mock("../services/handoverService", () => service);
vi.mock("react-chartjs-2", () => ({ Line: () => null }));

afterEach(() => {
  vi.clearAllMocks();
});

const renderAt = (id: string) =>
  render(
    <MemoryRouter initialEntries={[`/analytics/handover-reports/${id}`]}>
      <Routes>
        <Route path="/analytics/handover-reports/:activityId" element={<HandoverRunView />} />
      </Routes>
    </MemoryRouter>,
  );

describe("HandoverRunView", () => {
  it("shows the run's results, settings and command", async () => {
    service.fetchHandoverRun.mockResolvedValue(DETAIL);
    renderAt(DETAIL.activity_id);
    expect(await screen.findByText("Run 221238 · LLM + NCCL preflight")).toBeInTheDocument();
    expect(service.fetchHandoverRun).toHaveBeenCalledWith(DETAIL.activity_id);
    expect(screen.getByTestId("handover-kpi-gpus")).toHaveTextContent("144");
    expect(screen.getByTestId("handover-kpi-tflops")).toHaveTextContent("1980.0");
    expect(screen.getByText("R4 (SU26), W24 (SU27)")).toBeInTheDocument();
    // The job's own end, not when the launcher returned seconds after submitting it.
    expect(screen.getByText("2026-10-24 19:40 UTC")).toBeInTheDocument();
    expect(screen.getByText("NCCL_IB_QPS_PER_CONNECTION")).toBeInTheDocument();
    expect(screen.getByText("[REDACTED]")).toBeInTheDocument();
    expect(screen.getByText("roce_vf_r")).toBeInTheDocument();
  });

  it("tables the nodes with their address and bring-up NCCL figures", async () => {
    service.fetchHandoverRun.mockResolvedValue(DETAIL);
    renderAt(DETAIL.activity_id);
    const table = await screen.findByRole("table", { name: "Nodes" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent("gpu1-su26");
    expect(rows[1]).toHaveTextContent("192.0.2.26");
    expect(within(table).queryByText("GPU VBIOS")).not.toBeInTheDocument();
    expect(rows[1]).toHaveTextContent("219.6");
    expect(rows[1]).toHaveTextContent("NOT_RUN");
    expect(screen.getByText("Nodes (2)")).toBeInTheDocument();
  });

  it("draws the run's scalable units whole, its nodes green and the rest gray", async () => {
    service.fetchHandoverRun.mockResolvedValue(DETAIL);
    renderAt(DETAIL.activity_id);
    const plan = await screen.findByTestId("handover-floor-plan");
    expect(within(plan).getByText("SU26")).toBeInTheDocument();
    const r4 = within(plan).getByTestId("floor-rack-R4");
    expect(r4.querySelectorAll('[data-used="true"]')).toHaveLength(1);
    expect(r4.querySelectorAll('[data-used="false"]')).toHaveLength(1);
    expect(within(plan).getByTestId("floor-rack-R3").querySelectorAll('[data-used="true"]')).toHaveLength(0);
    expect(within(plan).getByText("In this run (1 nodes)")).toBeInTheDocument();
    expect(within(plan).getByText("Not in this run (2 nodes)")).toBeInTheDocument();
  });

  it("draws one chart per acceptance collective, saying which were not measured", async () => {
    service.fetchHandoverRun.mockResolvedValue(DETAIL);
    renderAt(DETAIL.activity_id);
    await screen.findByTestId("nccl-band-all_gather");
    expect(screen.getByTestId("nccl-band-all_reduce")).toHaveTextContent("Not measured from 2 GB to 16 GB");
    expect(screen.getByTestId("nccl-band-alltoall")).toHaveTextContent("Not measured from 2 GB to 16 GB");
    expect(screen.getByTestId("nccl-band-all_gather")).not.toHaveTextContent("Not measured");
  });

  it("shows the NCCL test command itself, and the launcher with its node list summarized", async () => {
    service.fetchHandoverRun.mockResolvedValue(DETAIL);
    renderAt(DETAIL.activity_id);
    expect(await screen.findByText("NCCL test commands")).toBeInTheDocument();
    expect(screen.getByText(/all_gather_perf -b 2G -e 16G/)).toBeInTheDocument();
    expect(screen.getByText(/export UCX_TLS=<not recorded>/)).toBeInTheDocument();
    expect(screen.getByText(/rebuilt from the job's settings/)).toBeInTheDocument();
    expect(screen.getByText("Launched through NVIS Rack Status")).toBeInTheDocument();
    expect(screen.getByText(/--nodelist <2 nodes, see Nodes>/)).toBeInTheDocument();
  });

  it("looks again while the node facts are being collected", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      service.fetchHandoverRun
        .mockResolvedValueOnce({ ...DETAIL, node_facts: { ...DETAIL.node_facts, state: "collecting" } })
        .mockResolvedValue(DETAIL);
      renderAt(DETAIL.activity_id);
      expect(await screen.findByText(/table fills in when that finishes/)).toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(10_000);
      await waitFor(() => expect(service.fetchHandoverRun).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(screen.queryByText(/table fills in when that finishes/)).not.toBeInTheDocument());
    } finally {
      vi.useRealTimers();
    }
  });

  it("collects the node facts again on request, then shows them being collected", async () => {
    service.fetchHandoverRun
      .mockResolvedValueOnce(DETAIL)
      .mockResolvedValue({ ...DETAIL, node_facts: { ...DETAIL.node_facts, state: "collecting" } });
    service.recollectNodeFacts.mockResolvedValue(undefined);
    renderAt(DETAIL.activity_id);
    fireEvent.click(await screen.findByRole("button", { name: /Collect node facts again/ }));
    await waitFor(() => expect(service.recollectNodeFacts).toHaveBeenCalledWith(DETAIL.activity_id));
    expect(await screen.findByText(/table fills in when that finishes/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Collect node facts again/ })).not.toBeInTheDocument();
  });

  it("says why the node facts could not be collected again", async () => {
    service.fetchHandoverRun.mockResolvedValue(DETAIL);
    service.recollectNodeFacts.mockRejectedValue(new Error("this run recorded no node list"));
    renderAt(DETAIL.activity_id);
    fireEvent.click(await screen.findByRole("button", { name: /Collect node facts again/ }));
    expect(await screen.findByText("this run recorded no node list")).toBeInTheDocument();
  });

  it("labels an LLM job's NCCL sweep as its preflight, not as NCCL results", async () => {
    service.fetchHandoverRun.mockResolvedValue({ ...DETAIL, alltoall_ceiling: null });
    renderAt(DETAIL.activity_id);
    expect(await screen.findByText("NCCL preflight (inside the LLM job)")).toBeInTheDocument();
    expect(screen.queryByText("NCCL results")).not.toBeInTheDocument();
    expect(screen.getByText("Preflight all-reduce @2 GB")).toBeInTheDocument();
  });

  it("puts all-to-all against its ceiling, with how the ceiling is derived", async () => {
    service.fetchHandoverRun.mockResolvedValue({ ...DETAIL, run_type: "nccl" });
    renderAt(DETAIL.activity_id);
    expect(await screen.findByTestId("handover-kpi-a2a-ceiling")).toHaveTextContent("74.5%");
    const table = screen.getByRole("table", { name: "All-to-all against its ceiling" });
    expect(table).toHaveTextContent("108.9 GB/s = 95.5 × (144 − 1) / (144 − 64)");
    expect(table).toHaveTextContent("81.1 GB/s, 74.5% of ceiling");
    expect(table).toHaveTextContent("slowest 83.9 (gpu1-su26)");
    expect(table).toHaveTextContent("SU26 x1, SU27 x1");
  });

  it("leaves the ceiling out when bring-up never measured the NICs", async () => {
    service.fetchHandoverRun.mockResolvedValue({ ...DETAIL, alltoall_ceiling: null });
    renderAt(DETAIL.activity_id);
    await screen.findByText("Nodes (2)");
    expect(screen.queryByTestId("handover-kpi-a2a-ceiling")).not.toBeInTheDocument();
    expect(screen.queryByText("All-to-all against its ceiling")).not.toBeInTheDocument();
  });

  it("downloads the report for this run", async () => {
    service.fetchHandoverRun.mockResolvedValue(DETAIL);
    service.downloadHandoverReport.mockResolvedValue(undefined);
    renderAt(DETAIL.activity_id);
    fireEvent.click(await screen.findByRole("button", { name: /Download report/ }));
    await waitFor(() => expect(service.downloadHandoverReport).toHaveBeenCalledWith([DETAIL.activity_id]));
  });

  it("says when the run is not there", async () => {
    service.fetchHandoverRun.mockRejectedValue(new Error("no such multi-rack run"));
    renderAt("gone");
    expect(await screen.findByText("no such multi-rack run")).toBeInTheDocument();
  });
});
