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
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Box from "@mui/material/Box";
import { Banner, Button, Flex, Skeleton } from "@nvidia/foundations-react-core";
import { ArrowLeft, FileDown } from "lucide-react";
import { PageHeader } from "../../../components/layout/PageHeader";
import { CONTENT_MAX_WIDTH } from "../../../components/layout/contentWidth";
import { HandoverRunDetail } from "../components/HandoverRunDetail";
import { RUN_TYPE_LABEL, formatWhen, jobLabel } from "../lib/handoverModel";
import { downloadHandoverReport, fetchHandoverRun, recollectNodeFacts } from "../services/handoverService";
import type { HandoverRunDetail as Detail } from "../types";
import { HANDOVER_REPORTS_PATH as HANDOVER_PATH } from "../../../routes";

const FACTS_POLL_MS = 10_000;

/** One multi-rack run's details, and its handover report. */
export function HandoverRunView() {
  const { activityId = "" } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);

  const load = useCallback(async () => {
    try {
      setRun(await fetchHandoverRun(activityId));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [activityId]);

  useEffect(() => {
    void load();
  }, [load]);

  // The node facts are read in the background once a run finishes; look again until they land.
  const collecting = run?.node_facts?.state === "collecting";
  useEffect(() => {
    if (!collecting) return undefined;
    const t = window.setTimeout(() => void load(), FACTS_POLL_MS);
    return () => window.clearTimeout(t);
  }, [collecting, load, run]);

  const onReport = async () => {
    setDownloading(true);
    try {
      await downloadHandoverReport([activityId]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDownloading(false);
    }
  };

  const title = run ? `Run ${jobLabel(run)} · ${RUN_TYPE_LABEL[run.run_type]}` : "Multi-rack run";
  const description = run
    ? `${[run.site.project, run.site.cluster].filter(Boolean).join(" / ")} · ${run.racks.join(", ")} · ${formatWhen(run.created_at)}`
    : "Loading the run's results and settings from its logs.";

  return (
    <Box sx={{ maxWidth: CONTENT_MAX_WIDTH.wide, mx: "auto", p: 4 }}>
      <PageHeader
        contentId="handoverReports"
        title={title}
        description={description}
        actions={
          <Flex gap="2">
            <Button kind="secondary" color="neutral" size="small" onClick={() => navigate(HANDOVER_PATH)}>
              <ArrowLeft size={16} aria-hidden /> All runs
            </Button>
            <Button kind="primary" size="small" onClick={() => void onReport()} disabled={!run || downloading}>
              <FileDown size={16} aria-hidden /> {downloading ? "Building report…" : "Download report"}
            </Button>
          </Flex>
        }
      />
      {error ? (
        <Banner status="error" kind="inline" style={{ marginBottom: 16 }}>
          {error}
        </Banner>
      ) : null}
      {run ? (
        <HandoverRunDetail
          run={run}
          onRecollectNodeFacts={async () => {
            await recollectNodeFacts(activityId);
            await load();
          }}
        />
      ) : error ? null : (
        <Flex direction="col" gap="3">
          <Skeleton style={{ height: 110 }} />
          <Skeleton style={{ height: 320 }} />
          <Skeleton style={{ height: 260 }} />
        </Flex>
      )}
    </Box>
  );
}
