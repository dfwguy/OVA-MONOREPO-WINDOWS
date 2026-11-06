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
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NodeSelector, type NodeInfo } from "./NodeSelector";

const nodes: NodeInfo[] = [
  { id: "sys1-gso1-p-phy-gpu19-su19", hostname: "sys1-gso1-p-phy-gpu19-su19", label: "U20-ct01", placement: "U20:11", status: "up", ip: "10.10.171.244" },
  { id: "p5-r01-ct01", status: "unknown" },
];

describe("NodeSelector", () => {
  it("shows the placement and the hostname in separate columns", () => {
    render(<NodeSelector nodes={nodes} selected={new Set()} onSelectionChange={vi.fn()} onOpenTerminal={vi.fn()} />);
    expect(screen.getByRole("columnheader", { name: "Hostname" })).toBeTruthy();
    const cell = screen.getByText("U20-ct01");
    expect(cell.getAttribute("title")).toBe("Placed at U20:11");
    const row = cell.closest("tr")!;
    expect(within(row).getByText("sys1-gso1-p-phy-gpu19-su19")).toBeTruthy();
    expect(within(row).getByText("UP")).toBeTruthy();
    expect(within(row).getByText("10.10.171.244")).toBeTruthy();
    expect(within(row).getByRole("button", { name: /terminal/i })).toBeTruthy();
  });

  it("falls back to the id for both columns on a legacy node", () => {
    render(<NodeSelector nodes={nodes} selected={new Set()} onSelectionChange={vi.fn()} />);
    const row = screen.getAllByText("p5-r01-ct01")[0].closest("tr")!;
    expect(within(row).getAllByText("p5-r01-ct01")).toHaveLength(2);
  });

  it("shows each node's own Stage 1 and Stage 2 when the server sends them", () => {
    const host = "sys1-gso1-p-phy-gpu19-su19";
    render(
      <NodeSelector
        nodes={nodes}
        selected={new Set()}
        onSelectionChange={vi.fn()}
        stage2Source="bringup:llm-pretrain-solo"
        nodeStages={{
          [host]: {
            node: host,
            rack: "U20",
            stage1: { state: "done", job_id: "119310" },
            stage2: { state: "fail", status: "FAIL", reason: "loss diverged" },
          },
        }}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Stages" })).toBeTruthy();
    const row = screen.getByText("U20-ct01").closest("tr")!;
    expect(within(row).getByLabelText("Stage 1 — single-node NCCL: pass (job 119310)")).toBeTruthy();
    expect(
      within(row).getByLabelText(
        "Stage 2 — single-node LLM (bringup:llm-pretrain-solo): fail (FAIL: loss diverged)",
      ),
    ).toBeTruthy();
    // A node the server has no answer for has not started either stage.
    const legacy = screen.getAllByText("p5-r01-ct01")[0].closest("tr")!;
    expect(within(legacy).getByLabelText(/Stage 1 — single-node NCCL: not started/)).toBeTruthy();
  });

  it("says why a node's Stage 1 failed", () => {
    const host = "sys1-gso1-p-phy-gpu19-su19";
    render(
      <NodeSelector
        nodes={nodes}
        selected={new Set()}
        onSelectionChange={vi.fn()}
        nodeStages={{
          [host]: {
            node: host,
            rack: "U20",
            stage1: { state: "fail", job_id: "125831", reason: "NVLink fabric not initialized (CUDA: system not yet initialized)" },
            stage2: { state: "pending" },
          },
        }}
      />,
    );
    const row = screen.getByText("U20-ct01").closest("tr")!;
    expect(
      within(row).getByLabelText(
        "Stage 1 — single-node NCCL: fail (job 125831: NVLink fabric not initialized (CUDA: system not yet initialized))",
      ),
    ).toBeTruthy();
  });

  it("leaves the Stages column out when the server sends no stages", () => {
    render(<NodeSelector nodes={nodes} selected={new Set()} onSelectionChange={vi.fn()} />);
    expect(screen.queryByRole("columnheader", { name: "Stages" })).toBeNull();
  });

  // Nscale NC, 2026-10-21: the floor view's scheduler mode showed drained trays while the rack page
  // read all green, because its only status column is BCM's ("up" = powered and reachable).
  it("shows the scheduler's status next to the cluster manager's, named after each source", () => {
    const rack: NodeInfo[] = [
      { id: "sys1-gso1-p-phy-gpu35-su20", label: "U3-ct01", status: "up", schedulerStatus: "drained", schedulerState: "drain" },
      { id: "sys1-gso1-p-phy-gpu36-su20", label: "U3-ct02", status: "up", schedulerStatus: "idle", schedulerState: "idle" },
    ];
    render(
      <NodeSelector
        nodes={rack}
        selected={new Set()}
        onSelectionChange={vi.fn()}
        nodeSources={{ orchestrator: "bcm", scheduler: "slurm" }}
      />,
    );
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers.indexOf("Scheduler (Slurm)")).toBe(headers.indexOf("Status") + 1);
    const drained = screen.getByText("U3-ct01").closest("tr")!;
    expect(within(drained).getByText("UP")).toBeTruthy();       // BCM: powered and reachable
    expect(within(drained).getByText("DRAINED")).toBeTruthy();  // Slurm: takes no work, same tag kind as UP
    expect(drained.querySelector("[data-scheduler-status]")!.getAttribute("data-scheduler-status")).toBe("drained");
    const idle = screen.getByText("U3-ct02").closest("tr")!;
    expect(within(idle).getByText("IDLE")).toBeTruthy();
    // Slurm's own word is kept for hover (the tooltip is the cell's accessible label).
    expect(within(drained).getByLabelText("Slurm: Drained (drain)")).toBeTruthy();
  });

  it("leaves the Scheduler column out when the server sends no scheduler view", () => {
    render(<NodeSelector nodes={nodes} selected={new Set()} onSelectionChange={vi.fn()} />);
    expect(screen.queryByRole("columnheader", { name: /Scheduler/ })).toBeNull();
  });
});
