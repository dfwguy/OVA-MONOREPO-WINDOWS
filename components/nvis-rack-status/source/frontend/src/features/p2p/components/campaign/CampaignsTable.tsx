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
// The saved campaigns and how each last ran: the Artifact Distribution page's main section.
// Author: Rafael M. Koike
//
// A campaign holds no run state, so "last run" is read from the operations it tagged with its name.
import { Button, Flex, StatusMessage, Table, Tag, Text } from "@nvidia/foundations-react-core";
import { lastRun, strategyLabel } from "../../lib/campaigns";
import type { CampaignEdit, RosterEdit } from "../../services/fleetService";
import type { Operation } from "../../types/fleet";

const RUN_TAG: Record<Operation["state"], "blue" | "green" | "red"> = {
  running: "blue",
  succeeded: "green",
  failed: "red",
};

export type CampaignsTableProps = {
  campaigns: CampaignEdit[];
  rosters: RosterEdit[];
  /** The whole fleet's node count, for a campaign with no named roster. */
  fleetSize: number;
  operations: Operation[];
  /** Why launching is unavailable (an operation running, no instance), or null. */
  blocked: string | null;
  onLaunch: (campaign: CampaignEdit) => void;
  onShowLog: (operation: Operation) => void;
};

export function CampaignsTable({ campaigns, rosters, fleetSize, operations, blocked, onLaunch, onShowLog }: CampaignsTableProps) {
  if (!campaigns.length) {
    return (
      <StatusMessage
        size="small"
        slotHeading="No campaigns yet"
        slotSubheading="A campaign pairs a catalog image with a roster and a wave plan. Start one with New campaign."
      />
    );
  }
  const rosterSize = (name: string) =>
    name ? rosters.find((r) => r.name === name)?.nodes.length ?? 0 : fleetSize;

  const rows = campaigns.map((campaign) => {
    const run = lastRun(operations, campaign.name);
    return {
      id: campaign.name,
      cells: [
        {
          children: (
            <Flex direction="column" gap="1">
              <Text kind="body/bold/sm">{campaign.name}</Text>
              {campaign.description ? (
                <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>{campaign.description}</Text>
              ) : null}
            </Flex>
          ),
        },
        { children: <Text kind="mono/sm">{campaign.image}</Text> },
        `${campaign.roster || "Whole fleet"} · ${rosterSize(campaign.roster).toLocaleString()} nodes`,
        strategyLabel(campaign.strategy),
        {
          children: run ? (
            <Flex align="center" gap="2" wrap="wrap">
              <Tag color={RUN_TAG[run.state]} kind="solid" readOnly density="compact">{run.state}</Tag>
              <Text kind="mono/sm" style={{ color: "var(--text-color-secondary)" }}>{run.started_at}</Text>
            </Flex>
          ) : (
            <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>never run</Text>
          ),
        },
        {
          children: (
            <Flex gap="2" style={{ whiteSpace: "nowrap" }}>
              <Button
                kind="secondary"
                color="neutral"
                size="tiny"
                disabled={Boolean(blocked)}
                title={blocked ?? `Launch ${campaign.name}`}
                onClick={() => onLaunch(campaign)}
              >
                Launch
              </Button>
              {run ? (
                <Button kind="secondary" color="neutral" size="tiny" onClick={() => onShowLog(run)}>
                  Log
                </Button>
              ) : null}
            </Flex>
          ),
        },
      ],
    };
  });

  return (
    <div style={{ overflowX: "auto", maxWidth: "100%" }}>
    <Table
      aria-label="Campaigns"
      layout="auto"
      density="compact"
      hoverableRows
      columns={["Campaign", "Task", "Roster", "Plan", "Last run", "Actions"]}
      rows={rows}
    />
    </div>
  );
}
