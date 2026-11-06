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
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import { Banner, Button, Flex, Select, Skeleton, Text, TextInput } from "@nvidia/foundations-react-core";
import { FileDown, RefreshCw, Search } from "lucide-react";
import { PageHeader } from "../../../components/layout/PageHeader";
import { CONTENT_MAX_WIDTH } from "../../../components/layout/contentWidth";
import { HANDOVER_REPORTS_PATH as HANDOVER_PATH } from "../../../routes";
import { HandoverRunsTable } from "../components/HandoverRunsTable";
import { matchesQuery } from "../lib/handoverModel";
import { downloadHandoverReport, fetchHandoverRuns } from "../services/handoverService";
import type { HandoverRunsResponse } from "../types";

/** While runs are being summarized the table refreshes this often; otherwise only on demand. */
const SUMMARIZING_POLL_MS = 5_000;

/** Multi-rack runs to hand racks over on: pick runs, view one, download the report. */
export function HandoverReportsView() {
  const navigate = useNavigate();
  const [data, setData] = useState<HandoverRunsResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [su, setSu] = useState("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [downloading, setDownloading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchHandoverRuns());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const summarizing = Boolean(data?.backfill.running) || Boolean(data?.runs.some((r) => r.summary_state === "pending"));
  useEffect(() => {
    if (!summarizing) return;
    const id = window.setTimeout(() => void load(), SUMMARIZING_POLL_MS);
    return () => window.clearTimeout(id);
  }, [summarizing, data, load]);

  const runs = useMemo(
    () => (data?.runs ?? []).filter((r) => (su === "all" || r.scalable_units.includes(su)) && matchesQuery(r, query)),
    [data, su, query],
  );

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const onReport = async () => {
    setDownloading(true);
    try {
      await downloadHandoverReport([...selected]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDownloading(false);
    }
  };

  const site = data?.site;
  const suItems = [
    { value: "all", children: "All scalable units" },
    ...(data?.scalable_units ?? []).map((u) => ({ value: u, children: u })),
  ];

  return (
    <Box sx={{ maxWidth: CONTENT_MAX_WIDTH.wide, mx: "auto", p: 4 }}>
      <PageHeader
        contentId="handoverReports"
        title={site?.cluster ? `${site.cluster} · Handover reports` : "Handover reports"}
        description="Multi-rack NCCL and LLM runs, with what each measured. Select the runs that hand racks over and download their report."
        actions={
          <Flex gap="2">
            <Button kind="secondary" color="neutral" size="small" onClick={() => void load()} disabled={loading}>
              <RefreshCw size={16} aria-hidden /> Refresh
            </Button>
            <Button kind="primary" size="small" onClick={() => void onReport()} disabled={!selected.size || downloading}>
              <FileDown size={16} aria-hidden />{" "}
              {downloading ? "Building report…" : selected.size ? `Report for ${selected.size} selected` : "Select runs for a report"}
            </Button>
          </Flex>
        }
      />
      {error ? (
        <Banner status={data ? "warning" : "error"} kind="inline" style={{ marginBottom: 16 }}>
          {data ? `Showing the last good data: ${error}` : error}
        </Banner>
      ) : null}
      {data?.backfill.running ? (
        <Banner status="info" kind="inline" style={{ marginBottom: 16 }} data-testid="handover-backfill">
          {`Summarizing finished runs from their logs${data.backfill.total ? ` (${data.backfill.done} of ${data.backfill.total} logs)` : ""}…`}
        </Banner>
      ) : null}
      {data ? (
        <>
          <Flex gap="3" align="center" wrap="wrap" style={{ marginBottom: 12 }}>
            <div style={{ minWidth: 200 }}>
              <Select aria-label="Scalable unit" items={suItems} value={su} onValueChange={(v: string) => setSu(v || "all")} />
            </div>
            <div style={{ minWidth: 260, flex: "1 1 260px" }}>
              <TextInput
                aria-label="Search runs"
                placeholder="Search racks, job, model…"
                value={query}
                onValueChange={(v: string) => setQuery(v)}
                slotStart={<Search size={16} aria-hidden />}
              />
            </div>
            <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }} data-testid="handover-shown">
              {runs.length} of {data.runs.length} runs
            </Text>
          </Flex>
          <HandoverRunsTable
            runs={runs}
            selected={selected}
            filterKey={`${su}\u0000${query}`}
            onToggle={toggle}
            onView={(id) => navigate(`${HANDOVER_PATH}/${encodeURIComponent(id)}`)}
          />
        </>
      ) : (
        <Flex direction="col" gap="3">
          <Skeleton style={{ height: 48 }} />
          <Skeleton style={{ height: 420 }} />
        </Flex>
      )}
    </Box>
  );
}
