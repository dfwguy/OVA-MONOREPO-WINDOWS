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
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeExplorer } from "./ScopeExplorer";
import type { RackStatusResponse } from "../../types/api";

const { live, context } = vi.hoisted(() => ({
  live: { data: null as RackStatusResponse | null, loading: false, error: null, reachable: true },
  context: {
    activeCluster: { geometry: { trays_per_rack: 4 } },
    activePlatform: null,
  },
}));
vi.mock("../../hooks/useRackStatus", () => ({ useRackStatus: () => live }));
vi.mock("../../context/ActiveClusterContext", () => ({ useActiveCluster: () => context }));

beforeEach(() => {
  live.data = {
    ok: true, returncode: 0, updated_at: "", log_dir: "", script: "", stderr: "", legend: "",
    footnotes: [], comments: {}, physical_rf0: {}, native_workers: { mode: "native" },
    summary: { done: 0, fail: 0, ongoing: 0, pending: 2 },
    snapshot: {
      id: "test", state: "fresh", cluster_id: "beacon", log_root: "", configuration_generation: 1,
      last_attempt_at: null, last_success_at: null, age_seconds: 0, last_error: null,
    },
    rows: ["F41", "F42"].map(rack => ({ rack, ct_down_unk: "-", sinfo: "up=2", nemo: "pending", last_job: "-" })),
    rack_mapping_mode: "translate",
    nodes: [1, 2, 3, 4].map(index => ({
      id: `dgx-b300-0${index}`, rack: index <= 2 ? "F41" : "F42", status: "up", ip: "",
    })),
  };
});

function explorer() {
  return <ScopeExplorer>{(hosts, _summary, selection) => <>
    <output aria-label="Selected hosts">{hosts.join(",")}</output>
    <output aria-label="Node totals">{selection.totalUp}/{selection.totalTrays}</output>
  </>}</ScopeExplorer>;
}

describe("scope tree rack inventory", () => {
  it("scopes to the four discovered nodes rather than eight generated tray names", () => {
    render(explorer());
    expect(screen.getByLabelText("Node totals")).toHaveTextContent("4/4");
    expect(screen.getByLabelText("Selected hosts")).toHaveTextContent("dgx-b300-01,dgx-b300-02,dgx-b300-03,dgx-b300-04");
    expect(screen.queryByText("F41-ct01")).not.toBeInTheDocument();
  });

  it("prunes the selection when the provider inventory reports no members", () => {
    const { rerender } = render(explorer());
    live.data = { ...live.data!, nodes: [] };
    rerender(explorer());
    expect(screen.getByLabelText("Node totals")).toHaveTextContent("0/0");
    expect(screen.getByLabelText("Selected hosts")).toBeEmptyDOMElement();
  });

  it("keeps the template trays where the hostname names the rack", () => {
    live.data = { ...live.data!, rack_mapping_mode: "direct", nodes: undefined };
    render(explorer());
    expect(screen.getByLabelText("Node totals")).toHaveTextContent("0/8");
  });
});
