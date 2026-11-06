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
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Paper from "@mui/material/Paper";
import Checkbox from "@mui/material/Checkbox";
import Box from "@mui/material/Box";
import Link from "@mui/material/Link";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import { Tag, Text, Button } from "@nvidia/foundations-react-core";
import { Terminal, TrendingUp } from "lucide-react";
import type { NodeIssueRollup, NodeSources, NodeStageInfo, NodeStagesRow, SchedulerNodeStatus } from "../../types/api";
import { stageSourceLabel, stageStateColor, stageStateLabel } from "../../lib/validationStages";
import { SCHEDULER_STATUS, SCHEDULER_TAG_COLOR, sourceName } from "../../lib/nodeStatus";

/** Build https URL for BMC / RedFish UI; bracket bare IPv6 literals only. */
function redfishHttpsHref(host: string): string | null {
  const h = host.trim();
  if (!h || /[\s/@#?\\]/.test(h)) return null;
  if (h.startsWith("[")) return `https://${h}`;
  const colons = (h.match(/:/g) || []).length;
  if (colons >= 2 || h.includes("::")) return `https://[${h}]`;
  return `https://${h}`;
}

export interface NodeInfo {
  /** Selection and action target. For an inventory-backed rack this is the real hostname. */
  id: string;
  /** The cluster manager's view (BCM): powered and reachable, installing, or down. */
  status: "up" | "down" | "inst" | "unknown";
  /**
   * The scheduler's view (Slurm), in the shared vocabulary. Kept apart from ``status`` because on
   * Nscale NC most of the fleet is up to BCM and drained to Slurm: a rack whose Status column reads
   * all green can still take no work. Absent on servers that do not send it.
   */
  schedulerStatus?: SchedulerNodeStatus;
  /** The scheduler's raw state as it spelled it (Slurm ``drain``, ``mix-``); shown on hover. */
  schedulerState?: string;
  ip?: string;
  /** Resolvable compute hostname (Slurm/DNS), shown in its own column. Defaults to ``id``. */
  hostname?: string;
  /** The node's tray id in the rack, e.g. ``U20-ct01``. Defaults to ``id``. */
  label?: string;
  /** Where the cluster manager placed it, e.g. BCM's ``U20:11``; shown on hover. */
  placement?: string;
  /** The server's tray number within the rack (natural hostname order); absent when unplaced. */
  tray?: number;
}

interface NodeSelectorProps {
  nodes: NodeInfo[];
  selected: Set<string>;
  onSelectionChange: (selected: Set<string>) => void;
  onOpenTerminal?: (nodeId: string) => void;
  issueNodes?: Record<string, NodeIssueRollup>;
  onOpenIssues?: (nodeId: string) => void;
  /** Per-node Stage 1 / Stage 2 (``/api/node-stages``), keyed by hostname. */
  nodeStages?: Record<string, NodeStagesRow>;
  /** Where Stage 2 comes from, e.g. ``bringup:llm-pretrain-solo``; shown on hover. */
  stage2Source?: string;
  /** Who answered for each status column (``/api/status`` ``node_sources``), named in the headers. */
  nodeSources?: NodeSources;
}

/** A node's two stages: single-node NCCL (Stage 1) and single-node LLM training (Stage 2). */
export function NodeStageTags({ stages, stage2Source }: { stages?: NodeStagesRow; stage2Source?: string }) {
  const cells: { short: string; label: string; info?: NodeStageInfo; detail: (i: NodeStageInfo) => string }[] = [
    {
      short: "S1 NCCL",
      label: "Stage 1 — single-node NCCL",
      info: stages?.stage1,
      detail: (i) => {
        const parts = [stageSourceLabel(i.source), i.job_id ? `job ${i.job_id}` : "", i.reason ?? ""].filter(Boolean);
        return parts.length ? ` (${parts.join(": ")})` : "";
      },
    },
    {
      short: "S2 LLM",
      label: `Stage 2 — single-node LLM${stage2Source ? ` (${stage2Source})` : ""}`,
      info: stages?.stage2,
      detail: (i) => (i.status ? ` (${i.status}${i.reason ? `: ${i.reason}` : ""})` : ""),
    },
  ];
  return (
    <Box sx={{ display: "flex", gap: 0.5 }}>
      {cells.map((c) => {
        const state = c.info?.state ?? "pending";
        const known = state !== "unknown";
        return (
          <Tooltip
            key={c.short}
            title={`${c.label}: ${known ? stageStateLabel(state) : "loading"}${c.info && known ? c.detail(c.info) : ""}`}
            enterDelay={350}
            arrow
          >
            <span style={{ display: "inline-flex", cursor: "default" }}>
              <Tag color={known ? stageStateColor(state) : "gray"} kind="outline" readOnly density="compact">
                {c.short}
              </Tag>
            </span>
          </Tooltip>
        );
      })}
    </Box>
  );
}

function statusLabel(status: NodeInfo["status"]) {
  switch (status) {
    case "up": return "UP";
    case "down": return "DOWN";
    case "inst": return "INST";
    default: return "?";
  }
}

/**
 * The scheduler's view of one node, as the same kind of tag as the Status column beside it: the
 * label is the floor view's (``SCHEDULER_STATUS``), the colour its tag equivalent.
 */
function SchedulerStatusCell({ node, schedulerName }: { node: NodeInfo; schedulerName: string }) {
  const status = node.schedulerStatus ?? "unknown";
  const label = SCHEDULER_STATUS[status].label;
  const raw = node.schedulerState ? ` (${node.schedulerState})` : "";
  return (
    <Tooltip title={`${schedulerName || "Scheduler"}: ${label}${raw}`} enterDelay={350} arrow>
      <span style={{ display: "inline-flex", cursor: "default" }} data-scheduler-status={status}>
        <Tag color={SCHEDULER_TAG_COLOR[status]} kind="solid" readOnly density="compact">
          {label.toUpperCase()}
        </Tag>
      </span>
    </Tooltip>
  );
}

function RedfishIpCell({ ip }: { ip?: string }) {
  const trimmed = ip?.trim();
  if (!trimmed) {
    return <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>—</Text>;
  }
  const href = redfishHttpsHref(trimmed);
  if (!href) {
    return <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>{trimmed}</Text>;
  }
  return (
    <Link
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      underline="always"
      title={`RedFish BMC — ${href}`}
      onClick={(e) => e.stopPropagation()}
      sx={{
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
        fontSize: 13,
        fontWeight: 500,
        color: "primary.main",
        cursor: "pointer",
      }}
    >
      {trimmed}
    </Link>
  );
}

export function NodeSelector({
  nodes,
  selected,
  onSelectionChange,
  onOpenTerminal,
  issueNodes,
  onOpenIssues,
  nodeStages,
  stage2Source,
  nodeSources,
}: NodeSelectorProps) {
  const allSelected = nodes.length > 0 && selected.size === nodes.length;
  // Only when the server sent a scheduler view: an empty column would read as "every node unknown".
  const showScheduler = nodes.some((n) => n.schedulerStatus !== undefined);
  const orchestratorName = sourceName(nodeSources, "orchestrator");
  const schedulerName = sourceName(nodeSources, "scheduler");
  const someSelected = selected.size > 0 && selected.size < nodes.length;

  const handleToggleAll = () => {
    if (allSelected) {
      onSelectionChange(new Set());
    } else {
      onSelectionChange(new Set(nodes.map((n) => n.id)));
    }
  };

  const handleToggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    onSelectionChange(next);
  };

  const selectDown = () => {
    onSelectionChange(new Set(nodes.filter((n) => n.status === "down").map((n) => n.id)));
  };

  const selectUp = () => {
    onSelectionChange(new Set(nodes.filter((n) => n.status === "up").map((n) => n.id)));
  };

  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1.5 }}>
        <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
          {selected.size} of {nodes.length} nodes selected
        </Text>
        <Button kind="secondary" size="small" onClick={handleToggleAll}>
          {allSelected ? "Clear all" : "Select all"}
        </Button>
        <Button kind="secondary" size="small" onClick={selectDown}>
          Down only
        </Button>
        <Button kind="secondary" size="small" onClick={selectUp}>
          Up only
        </Button>
      </Box>

      <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 360 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox
                  indeterminate={someSelected}
                  checked={allSelected}
                  onChange={handleToggleAll}
                />
              </TableCell>
              <TableCell>Node</TableCell>
              <TableCell>Hostname</TableCell>
              <TableCell title={orchestratorName ? `From ${orchestratorName}: powered, installing or down` : undefined}>
                Status
              </TableCell>
              {showScheduler && (
                <TableCell title={schedulerName ? `From ${schedulerName}: whether the node can take work` : undefined}>
                  {schedulerName ? `Scheduler (${schedulerName})` : "Scheduler"}
                </TableCell>
              )}
              {nodeStages && <TableCell>Stages</TableCell>}
              {(issueNodes || onOpenIssues) && <TableCell>Issue trend</TableCell>}
              <TableCell>RedFish IP</TableCell>
              {onOpenTerminal && <TableCell align="center">Actions</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {nodes.map((node) => (
              <TableRow
                key={node.id}
                hover
                onClick={() => handleToggle(node.id)}
                sx={{ cursor: "pointer" }}
              >
                <TableCell padding="checkbox">
                  <Checkbox checked={selected.has(node.id)} />
                </TableCell>
                <TableCell>
                  <Text
                    kind="body/regular/md"
                    style={{ fontFamily: "monospace" }}
                    title={node.placement ? `Placed at ${node.placement}` : undefined}
                  >
                    {node.label ?? node.id}
                  </Text>
                </TableCell>
                <TableCell>
                  <Text kind="body/regular/sm" style={{ fontFamily: "monospace" }}>
                    {node.hostname ?? node.id}
                  </Text>
                </TableCell>
                <TableCell>
                  <Tag
                    color={node.status === "up" ? "green" : node.status === "down" ? "red" : node.status === "inst" ? "blue" : "gray"}
                    kind="solid"
                    readOnly
                    density="compact"
                  >
                    {statusLabel(node.status)}
                  </Tag>
                </TableCell>
                {showScheduler && (
                  <TableCell>
                    <SchedulerStatusCell node={node} schedulerName={schedulerName} />
                  </TableCell>
                )}
                {nodeStages && (
                  <TableCell>
                    <NodeStageTags stages={nodeStages[node.hostname ?? node.id]} stage2Source={stage2Source} />
                  </TableCell>
                )}
                {(issueNodes || onOpenIssues) && (
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    {issueNodes?.[node.id] && (
                      <Button
                        kind="secondary"
                        size="small"
                        onClick={() => onOpenIssues?.(node.id)}
                        title={`Open all issue history for ${node.id}`}
                      >
                        <TrendingUp size={14} />
                        ▲{issueNodes[node.id].issue_count}
                        {issueNodes[node.id].drained ? " ✖" : ""}
                        {issueNodes[node.id].nccl ? " ⚑" : ""}
                        {issueNodes[node.id].maintenance ? " ▦" : ""}
                      </Button>
                    )}
                  </TableCell>
                )}
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <RedfishIpCell ip={node.ip} />
                </TableCell>
                {onOpenTerminal && (
                  <TableCell align="center" onClick={(e) => e.stopPropagation()}>
                    {node.status === "up" && (
                      <Tooltip title={`Open terminal to ${node.id}`}>
                        <IconButton size="small" onClick={() => onOpenTerminal(node.id)}>
                          <Terminal size={16} />
                        </IconButton>
                      </Tooltip>
                    )}
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}
