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
import { Flex, Text } from "@nvidia/foundations-react-core";
import { barColumns } from "../../../lib/rackTopology";
import type { FloorPlanUnit } from "../types";

const USED = "var(--color-green-500, #76b900)";
const IDLE = "var(--color-gray-300, #d0d0d0)";
const muted = { color: "var(--text-color-secondary)" } as const;

function Swatch({ color }: { color: string }) {
  return <span aria-hidden style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: color }} />;
}

/**
 * The scalable units a run used, drawn whole as on the Racks floor view: every rack in floor order,
 * every node in tray order, green when the run held it and gray when it did not.
 */
export function HandoverFloorPlan({ plan }: { plan: FloorPlanUnit[] }) {
  const nodes = plan.flatMap((su) => su.racks.flatMap((r) => r.nodes));
  const used = nodes.filter((n) => n.used).length;
  return (
    <Flex direction="col" gap="3" data-testid="handover-floor-plan">
      {plan.map((su) => (
        <div key={su.su}>
          <Text kind="label/bold/sm" style={{ display: "block", marginBottom: 6 }}>{su.su}</Text>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(112px, 1fr))", gap: 8 }}>
            {su.racks.map((rack) => (
              <div
                key={rack.rack}
                data-testid={`floor-rack-${rack.rack}`}
                style={{ border: "1px solid var(--border-color-base)", borderRadius: 4, padding: "4px 6px" }}
              >
                <Text
                  kind={rack.in_run ? "label/bold/sm" : "body/regular/sm"}
                  style={{ display: "block", textAlign: "center", ...(rack.in_run ? {} : muted) }}
                >
                  {rack.rack}
                </Text>
                {rack.nodes.length ? (
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: `repeat(${barColumns(rack.nodes.length)}, 1fr)`,
                      gap: 2,
                      marginTop: 4,
                    }}
                  >
                    {rack.nodes.map((n) => (
                      <span
                        key={n.host}
                        title={`${n.host}: ${n.used ? "in this run" : "not in this run"}`}
                        data-used={n.used}
                        style={{ height: 9, borderRadius: 1, background: n.used ? USED : IDLE }}
                      />
                    ))}
                  </div>
                ) : (
                  <Text kind="body/regular/sm" style={{ ...muted, display: "block", textAlign: "center" }}>not placed</Text>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
      <Flex gap="4" align="center">
        <Flex gap="1" align="center"><Swatch color={USED} /><Text kind="body/regular/sm">In this run ({used} nodes)</Text></Flex>
        <Flex gap="1" align="center"><Swatch color={IDLE} /><Text kind="body/regular/sm">Not in this run ({nodes.length - used} nodes)</Text></Flex>
      </Flex>
    </Flex>
  );
}
