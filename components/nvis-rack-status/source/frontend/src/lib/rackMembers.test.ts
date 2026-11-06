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
import { rackMembers } from "./rackNodesFromInventory";
import { powerSpecTokensFromNodeIds, validationFamilyBody } from "./rackCommandBodies";
import type { NodeInventoryEntry } from "../types/api";

// Beacon: saved racks F41/F42 hold dgx-b300-*; no hostname names its rack.
const inventory: NodeInventoryEntry[] = [
  { id: "dgx-b300-01", rack: "F41", rack_unit: "2", status: "up", ip: "10.184.154.130" },
  { id: "dgx-b300-02", rack: "F41", rack_unit: "36", status: "down", ip: "10.184.154.133" },
  { id: "dgx-b300-03", rack: "F42", rack_unit: "2", status: "up", ip: "10.184.154.136" },
  { id: "dgx-b300-04", rack: "F42", rack_unit: "36", status: "up", ip: "10.184.154.139" },
  { id: "unassigned-compute", rack: null, status: "unknown", ip: "" },
];
const legacyRow = { ct_down_unk: "UP:F41-ct[01-04]" };

describe("rackMembers", () => {
  it("takes a rack's members and their state from the inventory, whatever the tray text implies", () => {
    const nodes = rackMembers("f41", { row: legacyRow, inventory, mappingMode: "translate", traysPerRack: 4 });
    expect(nodes.map((n) => [n.id, n.status, n.ip])).toEqual([
      ["dgx-b300-01", "up", "10.184.154.130"],
      ["dgx-b300-02", "down", "10.184.154.133"],
    ]);
  });

  it("does not turn rack capacity or physical U positions into nodes", () => {
    expect(rackMembers("F41", { row: legacyRow, inventory, mappingMode: "translate", traysPerRack: 36 })).toHaveLength(2);
  });

  it.each(["translate", "pool"] as const)("never invents <rack>-ctNN hosts in %s mode", (mappingMode) => {
    for (const inv of [[], null, undefined]) {
      expect(rackMembers("F41", { row: legacyRow, inventory: inv, mappingMode, traysPerRack: 4 })).toEqual([]);
    }
  });

  it("gives a saved empty rack no nodes", () => {
    expect(rackMembers("Empty-Rack", { row: { ct_down_unk: "-" }, inventory, mappingMode: "translate", traysPerRack: 4 }))
      .toEqual([]);
  });

  it("keeps the template expansion where the hostname names the rack", () => {
    expect(rackMembers("F41", { row: { ct_down_unk: "-" }, inventory: null, mappingMode: "direct", traysPerRack: 4 })
      .map((n) => n.id)).toEqual(["F41-ct01", "F41-ct02", "F41-ct03", "F41-ct04"]);
  });

  it("keeps it for an older server that reports no mapping mode", () => {
    expect(rackMembers("F41", { row: { ct_down_unk: "-" }, traysPerRack: 2 }).map((n) => n.id))
      .toEqual(["F41-ct01", "F41-ct02"]);
  });

  it("hands real hostnames to the validation and power command bodies", () => {
    const selected = new Set(rackMembers("F41", { inventory, mappingMode: "translate" }).map((n) => n.id));
    expect(validationFamilyBody("F41", undefined, selected)).toEqual({
      rack: "F41", target: "dgx-b300-01,dgx-b300-02",
    });
    expect(powerSpecTokensFromNodeIds("F41", selected)).toEqual(["dgx-b300-01", "dgx-b300-02"]);
  });
});
