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
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AddTerminalDialog } from "./AddTerminalDialog";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("../../lib/apiFetch", () => ({ apiFetch }));

const nodes = [
  { id: "dgx-b300-01", rack: "F41", status: "up", ip: "" },
  { id: "dgx-b300-02", rack: "F41", status: "up", ip: "" },
  { id: "dgx-b300-03", rack: "F42", status: "up", ip: "" },
  { id: "dgx-b300-04", rack: "F42", status: "up", ip: "" },
];

function respond(body: object) {
  apiFetch.mockResolvedValue(new Response(JSON.stringify({
    rows: ["F41", "F42"].map(rack => ({ rack, ct_down_unk: "-" })), ...body,
  }), { status: 200 }));
}

beforeEach(() => respond({ rack_mapping_mode: "translate", nodes }));

describe("terminal picker rack inventory", () => {
  it("lists four real compute hosts in total and opens the selected hostname", async () => {
    const onAdd = vi.fn();
    render(<AddTerminalDialog open onClose={() => undefined} onAdd={onAdd} traysPerRack={4} />);
    expect(await screen.findByText("4 nodes")).toBeInTheDocument();
    for (const node of nodes) expect(screen.getByText(node.id)).toBeInTheDocument();
    expect(screen.queryByText("F41-ct01")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^dgx-b300-03\s*up$/ }));
    expect(onAdd).toHaveBeenCalledWith({ target: "dgx-b300-03", mode: "node", label: "dgx-b300-03" });
  });

  it("keeps the template list where the hostname names the rack", async () => {
    respond({ rack_mapping_mode: "direct" });
    render(<AddTerminalDialog open onClose={() => undefined} onAdd={() => undefined} traysPerRack={4} />);
    expect(await screen.findByText("8 nodes")).toBeInTheDocument();
    expect(screen.getByText("F41-ct01")).toBeInTheDocument();
  });
});
