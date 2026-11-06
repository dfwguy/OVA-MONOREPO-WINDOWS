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
import { Banner, Button, Flex, Tag, Text } from "@nvidia/foundations-react-core";
import { RefreshCw } from "lucide-react";
import { fetchClusterPaths, type ClusterPathRow, type ClusterPaths } from "../services/clusterPathsService";

const SOURCE: Record<ClusterPathRow["source"], { label: string; color: "green" | "blue" | "yellow" | "gray" | "teal" }> = {
  root: { label: "from root", color: "green" },
  override: { label: "override", color: "blue" },
  environment: { label: "environment — move onto the record", color: "yellow" },
  unset: { label: "not set", color: "gray" },
  p2p: { label: "P2P", color: "teal" },
};

function Status({ row }: { row: ClusterPathRow }) {
  if (row.exists === undefined) return null;
  if (!row.exists) return <Tag color="red" kind="outline" readOnly density="compact">missing</Tag>;
  return row.writable ? (
    <Tag color="green" kind="outline" readOnly density="compact">ok</Tag>
  ) : (
    <Tag color="yellow" kind="outline" readOnly density="compact">read-only</Tag>
  );
}

function Row({ row }: { row: ClusterPathRow }) {
  const s = SOURCE[row.source];
  return (
    <div
      data-testid={`path-${row.key}`}
      style={{ display: "grid", gridTemplateColumns: "minmax(140px, 200px) 1fr auto auto", gap: 12, alignItems: "baseline" }}
    >
      <Text kind="body/bold/sm" title={row.purpose}>{row.label}</Text>
      <Text kind="mono/sm" style={{ overflowWrap: "anywhere", color: row.path ? undefined : "var(--text-color-subtle)" }}>
        {row.path || "—"}
      </Text>
      <Tag color={s.color} kind="outline" readOnly density="compact">{s.label}</Tag>
      <Status row={row} />
    </div>
  );
}

/**
 * Where the active cluster keeps its things: its root, every path derived from it, and the two image
 * paths that are P2P's. "Check on cluster" asks the execution host whether each folder exists and is
 * writable. Shows the saved record, so save the editor before checking a change.
 */
export function ClusterPathsPanel() {
  const [data, setData] = useState<ClusterPaths | null>(null);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  const load = useCallback(async (check: boolean) => {
    setChecking(check);
    try {
      setData(await fetchClusterPaths(check));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  return (
    <Flex direction="col" gap="2" data-testid="cluster-paths">
      <Flex justify="between" align="center" gap="2" wrap="wrap">
        <Text kind="body/bold/md">Where this cluster keeps its things</Text>
        <Button kind="secondary" color="neutral" size="small" onClick={() => void load(true)} disabled={checking}>
          <RefreshCw size={14} aria-hidden /> {checking ? "Checking…" : "Check on cluster"}
        </Button>
      </Flex>
      {error ? <Banner status="error" kind="inline">{error}</Banner> : null}
      {data?.check_error ? <Banner status="warning" kind="inline">Could not check: {data.check_error}</Banner> : null}
      {data ? (
        <>
          <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
            Root: <code>{data.root || "not set"}</code>
            {data.checked_on ? ` · checked on the ${data.checked_on}` : ""}
          </Text>
          {data.paths.map((row) => <Row key={row.key} row={row} />)}
          <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)", marginTop: 4 }}>
            Images are outside the root: P2P keeps the origin on the app server and delivers to each node's own cache, which is
            the only copy a job runs. Not checked from the execution host.
          </Text>
          {data.exceptions.map((row) => <Row key={row.key} row={row} />)}
        </>
      ) : null}
    </Flex>
  );
}
