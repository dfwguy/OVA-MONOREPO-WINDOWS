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
import { useCallback, useState, type ReactNode } from "react";
import { Button, Checkbox, Flex, Spinner, StatusMessage, Table, Tag, Text, Tooltip } from "@nvidia/foundations-react-core";
import { ArrowDown, ArrowUp, Eye } from "lucide-react";
import { TablePager } from "../../../components/TablePager";
import { useSortedPagedRows } from "../../../hooks/useSortedPagedRows";
import {
  COLLECTIVE_SHORT,
  RUN_TYPE_LABEL,
  formatGbps,
  formatWhen,
  jobLabel,
  modelLabel,
} from "../lib/handoverModel";
import type { Collective, HandoverRun } from "../types";

/** The three collectives the run table compares; the detail view shows every one the run swept. */
const TABLE_COLLECTIVES: Collective[] = ["all_reduce", "alltoall", "all_gather"];

/**
 * Racks (and scalable units) named in the cell before it trims to "…". A 1024-GPU run spans 16
 * racks, and printing all of them pushed the measurement columns off the screen; the full list is
 * one hover away.
 */
const RACKS_SHOWN = 4;

const OUTCOME_COLOR: Record<string, "green" | "red" | "blue" | "gray"> = {
  passed: "green",
  failed: "red",
  error: "red",
  timeout: "red",
  running: "blue",
  submitted: "blue",
  collecting: "blue",
};

const muted = { color: "var(--text-color-secondary)" } as const;
const numeric = { fontVariantNumeric: "tabular-nums" } as const;

export type HandoverRunsTableProps = {
  runs: HandoverRun[];
  selected: ReadonlySet<string>;
  onToggle: (activityId: string) => void;
  onView: (activityId: string) => void;
  /**
   * Changes whenever the caller's filters change, sending the table back to page 1. Polling hands
   * the table a new `runs` array every few seconds while runs summarize, so the array itself
   * cannot be the signal: the user would be thrown off their page on every refresh.
   */
  filterKey?: string;
};

type RowHandlers = Pick<HandoverRunsTableProps, "selected" | "onToggle" | "onView">;

/**
 * One column: its header, how a row renders in it, and the text it sorts by. Kept together so the
 * header, the cell and the sort can never disagree about which column is which.
 */
type Column = {
  header: string;
  cell: (run: HandoverRun, handlers: RowHandlers) => ReactNode;
  /** Raw text for {@link useSortedPagedRows}; absent for the checkbox and action columns. */
  sortText?: (run: HandoverRun) => string;
};

/** A number as sortable text; blank sorts last in both directions. */
const num = (value: number | null | undefined) => (typeof value === "number" && Number.isFinite(value) ? String(value) : "");

const typeText = (run: HandoverRun) =>
  run.summary_state === "running" ? "running" : run.summary_state === "pending" ? "summarizing…" : RUN_TYPE_LABEL[run.run_type];

function metricCell(run: HandoverRun, coll: Collective): ReactNode {
  const c = run.collectives[coll];
  if (run.summary_state === "pending") return <Spinner size="small" aria-label="Summarizing" />;
  if (!c) return <Text kind="body/regular/sm" style={muted}>—</Text>;
  return (
    <span title={`Peak ${formatGbps(c.busbw_peak_gbps)} GB/s`} style={numeric}>
      {formatGbps(c.busbw_2g_gbps ?? null)}
    </span>
  );
}

/** The first few names, then "…" when there are more. */
function trimmed(names: string[]): string {
  return names.length > RACKS_SHOWN ? `${names.slice(0, RACKS_SHOWN).join(", ")}, …` : names.join(", ");
}

/** Racks over their scalable units; a long list trims to "…" and shows in full on hover. */
function RacksCell({ run }: { run: HandoverRun }) {
  const { racks, scalable_units: sus } = run;
  const body = (
    <Flex direction="column" gap="1">
      <Text kind="body/regular/sm" style={{ whiteSpace: "nowrap" }}>{trimmed(racks)}</Text>
      {sus.length ? (
        <Text kind="body/regular/sm" style={{ ...muted, whiteSpace: "nowrap" }}>{trimmed(sus)}</Text>
      ) : null}
    </Flex>
  );
  if (racks.length <= RACKS_SHOWN && sus.length <= RACKS_SHOWN) return body;
  const full = [
    `${racks.length} racks: ${racks.join(", ")}`,
    sus.length ? `${sus.length} scalable units: ${sus.join(", ")}` : "",
  ].filter(Boolean);
  return (
    <Tooltip
      side="bottom"
      align="start"
      slotContent={<span style={{ whiteSpace: "pre-line", maxWidth: 360, display: "block" }}>{full.join("\n")}</span>}
    >
      <span tabIndex={0} aria-label={full.join(". ")} data-testid={`racks-${run.activity_id}`} style={{ cursor: "help" }}>
        {body}
      </span>
    </Tooltip>
  );
}

const COLUMNS: Column[] = [
  {
    header: "",
    cell: (run, { selected, onToggle }) => (
      <Checkbox
        checked={selected.has(run.activity_id)}
        onCheckedChange={() => onToggle(run.activity_id)}
        attributes={{ CheckboxInput: { "aria-label": `Select run ${jobLabel(run)}` } }}
      />
    ),
  },
  {
    header: "Date (UTC)",
    cell: (run) => <Text kind="mono/sm">{formatWhen(run.created_at).replace(" UTC", "")}</Text>,
    sortText: (run) => run.created_at ?? "",
  },
  { header: "Job", cell: (run) => <Text kind="mono/sm">{jobLabel(run)}</Text>, sortText: jobLabel },
  {
    header: "Type",
    cell: (run) =>
      run.summary_state === "running" ? (
        <Tag color="blue" kind="outline" readOnly density="compact">running</Tag>
      ) : run.summary_state === "pending" ? (
        <Text kind="body/regular/sm" style={muted}>summarizing…</Text>
      ) : (
        RUN_TYPE_LABEL[run.run_type]
      ),
    sortText: typeText,
  },
  { header: "Racks", cell: (run) => <RacksCell run={run} />, sortText: (run) => run.racks.join(", ") },
  { header: "GPUs", cell: (run) => <span style={numeric}>{run.gpus ?? "—"}</span>, sortText: (run) => num(run.gpus) },
  ...TABLE_COLLECTIVES.map(
    (coll): Column => ({
      header: `${COLLECTIVE_SHORT[coll]} @2 GB (GB/s)`,
      cell: (run) => metricCell(run, coll),
      sortText: (run) => num(run.collectives[coll]?.busbw_2g_gbps),
    }),
  ),
  { header: "LLM model", cell: modelLabel, sortText: (run) => (run.llm ? modelLabel(run).replace("—", "") : "") },
  {
    header: "TFLOP/s per GPU",
    cell: (run) => <span style={numeric}>{formatGbps(run.llm?.tflops_per_gpu)}</span>,
    sortText: (run) => num(run.llm?.tflops_per_gpu),
  },
  {
    header: "Step time (s)",
    cell: (run) => (
      <span style={numeric}>{typeof run.llm?.step_time_s === "number" ? run.llm.step_time_s.toFixed(2) : "—"}</span>
    ),
    sortText: (run) => num(run.llm?.step_time_s),
  },
  {
    header: "Outcome",
    cell: (run) => (
      <Tag color={OUTCOME_COLOR[run.outcome] ?? "gray"} kind="outline" readOnly density="compact">
        {run.outcome}
      </Tag>
    ),
    sortText: (run) => run.outcome,
  },
  {
    header: "",
    cell: (run, { onView }) => (
      <Button kind="secondary" color="neutral" size="tiny" onClick={() => onView(run.activity_id)}>
        <Eye size={14} aria-hidden /> View
      </Button>
    ),
  },
];

/** Module-level so it is referentially stable, as useSortedPagedRows requires. */
const sortTextAt = (run: HandoverRun, col: number) => COLUMNS[col]?.sortText?.(run) ?? "";

/** Header label with the active sort's direction arrow beside it. */
function SortHeader({ label, dir }: { label: string; dir: "asc" | "desc" | null }) {
  return (
    <Flex align="center" style={{ gap: 4, whiteSpace: "nowrap", cursor: "pointer" }}>
      <span>{label}</span>
      {dir === "asc" ? <ArrowUp size={12} aria-hidden /> : dir === "desc" ? <ArrowDown size={12} aria-hidden /> : null}
    </Flex>
  );
}

/** Multi-rack runs to hand racks over on: what each ran on and what it measured. */
export function HandoverRunsTable({ runs, selected, onToggle, onView, filterKey = "" }: HandoverRunsTableProps) {
  const page = useSortedPagedRows(runs, sortTextAt);

  // A filter change is a new question, so it starts on page 1. Adjusted during render (React's
  // pattern for state derived from a prop change) rather than in an effect, so the table never
  // paints one frame on the old page.
  const [seenFilterKey, setSeenFilterKey] = useState(filterKey);
  if (seenFilterKey !== filterKey) {
    setSeenFilterKey(filterKey);
    page.setPage(1);
  }

  const { toggleSort } = page;
  const onColumnSelect = useCallback(({ columnIndex }: { columnIndex: number }) => toggleSort(columnIndex), [toggleSort]);

  if (!runs.length) {
    return (
      <StatusMessage
        size="small"
        slotHeading="No multi-rack runs"
        slotSubheading="Runs launched from Multirack operations (NCCL or NeMo across racks) appear here once submitted."
      />
    );
  }

  const handlers: RowHandlers = { selected, onToggle, onView };
  const columns = COLUMNS.map((col, i) => {
    if (!col.sortText) return { children: col.header };
    const dir = page.sortCol === i ? page.sortDir : null;
    return {
      children: <SortHeader label={col.header} dir={dir} />,
      onColumnSelect,
      attributes: {
        TableHeaderCell: {
          "aria-sort": dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none",
          title: `Sort by ${col.header} — click again to reverse, a third time to restore the original order`,
        } as const,
      },
    };
  });
  const rows = page.visible.map((run) => ({
    id: run.activity_id,
    selected: selected.has(run.activity_id),
    cells: COLUMNS.map((col) => ({ children: col.cell(run, handlers) })),
  }));

  return (
    <>
      <div style={{ overflowX: "auto", maxWidth: "100%" }}>
        <Table aria-label="Multi-rack runs" layout="auto" density="compact" hoverableRows columns={columns} rows={rows} />
      </div>
      <TablePager {...page} noun="runs" />
    </>
  );
}
