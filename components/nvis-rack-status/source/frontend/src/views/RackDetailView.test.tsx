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
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { RackDetailView } from "./RackDetailView";
import type { NodeInventoryEntry } from "../types/api";

const { context } = vi.hoisted(() => ({
  context: {
    activeCluster: { geometry: { trays_per_rack: 4 } },
    activePlatform: null,
  },
}));
vi.mock("../context/ActiveClusterContext", () => ({ useActiveCluster: () => context }));
vi.mock("../context/RackCommandProvider", () => ({
  RackCommandProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("../components/rack/RackOverview", () => ({ RackOverview: () => null }));
vi.mock("../components/rack/RackLastOutputDot", () => ({ RackLastOutputDot: () => null }));
vi.mock("../components/rack/RackPendingTags", () => ({ RackPendingTags: () => null }));
vi.mock("../components/rack/ValidationTab", () => ({
  ValidationTab: ({ selectedNodes, disabled }: { selectedNodes: Set<string>; disabled: boolean }) => (
    <button disabled={disabled}>Validate {Array.from(selectedNodes).join(",")}</button>
  ),
}));
vi.mock("../components/rack/HardwareTab", () => ({ HardwareTab: () => null }));
vi.mock("../components/rack/NetworkingTab", () => ({ NetworkingTab: () => null }));
vi.mock("../components/rack/ServicesTab", () => ({ ServicesTab: () => null }));
vi.mock("../components/rack/NodeIssueHistoryDialog", () => ({ NodeIssueHistoryDialog: () => null }));
vi.mock("../components/rack/WebTerminalDialog", () => ({
  default: ({ target }: { target: string }) => <div role="dialog">Terminal {target}</div>,
}));
vi.mock("../services/nodeStagesService", () => ({
  fetchNodeStages: vi.fn().mockResolvedValue({ ok: true, nodes: [] }),
}));
vi.mock("../services/nodeIssuesService", () => ({
  fetchPostRunNodeReport: vi.fn().mockResolvedValue({
    nodes: [], generated_at: "", summary: { nodes: 0, drained_nodes: 0, flagged_nodes: 0 },
  }),
}));

const inventory: NodeInventoryEntry[] = [
  { id: "dgx-b300-01", rack: "F41", rack_unit: "2", status: "up", ip: "10.184.154.130" },
  { id: "dgx-b300-02", rack: "F41", rack_unit: "36", status: "up", ip: "10.184.154.133" },
  { id: "dgx-b300-03", rack: "F42", rack_unit: "2", status: "up", ip: "10.184.154.136" },
  { id: "dgx-b300-04", rack: "F42", rack_unit: "36", status: "up", ip: "10.184.154.139" },
];

function detail(
  rack = "F41",
  nodeInventory: NodeInventoryEntry[] | null = inventory,
  mode: "direct" | "translate" = "translate",
  inventoryError?: string,
) {
  return <RackDetailView
    rack={rack}
    row={{ rack, ct_down_unk: "-", sinfo: "up=2", nemo: "pending", last_job: "-" }}
    comment=""
    physicalRf0={{}}
    inventory={nodeInventory}
    inventoryError={inventoryError}
    rackMappingMode={mode}
    onBack={() => undefined}
  />;
}

describe("Rack Detail provider inventory", () => {
  it("shows and selects only the two real Beacon nodes assigned to the chosen rack", () => {
    render(detail());
    expect(screen.getAllByText("dgx-b300-01").length).toBeGreaterThan(0);
    expect(screen.getAllByText("dgx-b300-02").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("dgx-b300-03")).toHaveLength(0);
    expect(screen.queryAllByText("F41-ct01")).toHaveLength(0);
    expect(screen.getByText("2 of 2 nodes selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Validate dgx-b300-01,dgx-b300-02" })).toBeEnabled();
    expect(screen.getByRole("link", { name: "10.184.154.130" })).toHaveAttribute("href", "https://10.184.154.130");
  });

  it("opens a terminal using the discovered hostname", async () => {
    render(detail());
    fireEvent.click(screen.getByRole("button", { name: "Open terminal to dgx-b300-02" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Terminal dgx-b300-02");
  });

  it("updates membership and selection when navigating to the other rack", () => {
    const { rerender } = render(detail());
    rerender(detail("F42"));
    expect(screen.getAllByText("dgx-b300-03").length).toBeGreaterThan(0);
    expect(screen.getAllByText("dgx-b300-04").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("dgx-b300-01")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Validate dgx-b300-03,dgx-b300-04" })).toBeEnabled();
  });

  it.each([
    { label: "empty", nodes: [] },
    { label: "unavailable", nodes: null },
  ])("clears selection and disables actions when inventory becomes $label", ({ nodes }) => {
    const { rerender } = render(detail());
    rerender(detail("F41", nodes));
    expect(screen.getByText("0 of 0 nodes selected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Validate" })).toBeDisabled();
    expect(screen.queryAllByText("F41-ct01")).toHaveLength(0);
  });

  it("says why the members are unknown when the inventory is unavailable", () => {
    render(detail("F41", null, "translate", "BCM node inventory failed: BCM offline"));
    expect(screen.getByText("BCM node inventory failed: BCM offline")).toBeInTheDocument();
  });

  it("keeps the template expansion where the hostname names the rack", () => {
    render(detail("F41", null, "direct"));
    expect(screen.getByText("4 of 4 nodes selected")).toBeInTheDocument();
    expect(screen.getAllByText("F41-ct01").length).toBeGreaterThan(0);
    expect(screen.getAllByText("F41-ct04").length).toBeGreaterThan(0);
  });
});
