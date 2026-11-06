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
import Box from "@mui/material/Box";
import { Banner, Button, Flex, Skeleton } from "@nvidia/foundations-react-core";
import { Download, RefreshCw } from "lucide-react";
import { PageHeader } from "../../../components/layout/PageHeader";
import { CONTENT_MAX_WIDTH } from "../../../components/layout/contentWidth";
import { ClusterForecast } from "../components/ClusterForecast";
import { forecastSubtitle } from "../lib/forecastModel";
import { downloadForecastSite, fetchClusterForecast } from "../services/forecastService";
import type { ClusterForecastReport } from "../types";

/** The forecast moves with the hourly samples; a few minutes is as fresh as it needs to be. */
const REFRESH_MS = 300_000;

/** The live forecast inside Rack Status, and the place its static snapshot is exported from. */
export function ClusterForecastView() {
  const [report, setReport] = useState<ClusterForecastReport | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await fetchClusterForecast());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const onExport = async () => {
    setExporting(true);
    try {
      await downloadForecastSite();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  };

  return (
    <Box sx={{ maxWidth: CONTENT_MAX_WIDTH.wide, mx: "auto", p: 4 }}>
      <PageHeader
        contentId="clusterForecast"
        title={report?.meta.cluster ? `${report.meta.cluster} · Cluster forecast` : "Cluster forecast"}
        description={report ? forecastSubtitle(report) : "When validation finishes, node by node, rack by rack and SU by SU."}
        actions={
          <Flex gap="2">
            <Button kind="secondary" color="neutral" size="small" onClick={() => void load()} disabled={loading}>
              <RefreshCw size={16} aria-hidden /> Refresh
            </Button>
            <Button kind="secondary" color="neutral" size="small" onClick={() => void onExport()} disabled={exporting || !report}>
              <Download size={16} aria-hidden /> {exporting ? "Exporting…" : "Download static page"}
            </Button>
          </Flex>
        }
      />
      {error ? (
        <Banner status={report ? "warning" : "error"} kind="inline" style={{ marginBottom: 16 }}>
          {report ? `Showing the last good data: ${error}` : error}
        </Banner>
      ) : null}
      {report ? (
        <ClusterForecast report={report} />
      ) : (
        <Flex direction="col" gap="3">
          <Skeleton style={{ height: 110 }} />
          <Skeleton style={{ height: 280 }} />
          <Skeleton style={{ height: 420 }} />
        </Flex>
      )}
    </Box>
  );
}
