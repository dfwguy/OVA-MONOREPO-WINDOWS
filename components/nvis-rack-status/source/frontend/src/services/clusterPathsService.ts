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
/**
 * Where a cluster keeps its things (`GET /api/cluster-paths`, `backend/cluster_paths.py`).
 *
 * One root per cluster, and every on-host path derived from it. The layout -- which suffix each
 * path takes under the root -- is the backend's, fetched rather than retyped here, so the editor's
 * "= <root>/..." hints can never disagree with what the scripts are actually given.
 */
import { useEffect, useState } from "react";
import { apiFetch } from "../lib/apiFetch";

export interface PathLayoutEntry {
  key: string;
  label: string;
  suffix: string;
  /** The record field that overrides it, as `section.field` (e.g. `connection.log_dir`). */
  field: string;
  env: string[];
  purpose: string;
}

export interface ClusterPathRow {
  key: string;
  label: string;
  path: string;
  /** override | root | environment (deprecated: set the root) | unset | p2p (the image exceptions). */
  source: "override" | "root" | "environment" | "unset" | "p2p";
  env: string[];
  purpose: string;
  field: string;
  exists?: boolean;
  writable?: boolean;
}

export interface ClusterPaths {
  ok: true;
  cluster: { id: string; name: string };
  root: string;
  paths: ClusterPathRow[];
  exceptions: ClusterPathRow[];
  checked_on?: string;
  check_error?: string;
}

async function getJson<T>(url: string): Promise<T> {
  const res = await apiFetch(url, { cache: "no-store" });
  const body = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string };
  if (!res.ok || body.ok === false) throw new Error(body.error || `HTTP ${res.status}`);
  return body as T;
}

export async function fetchPathLayout(): Promise<PathLayoutEntry[]> {
  return (await getJson<{ layout: PathLayoutEntry[] }>("/api/cluster-paths/layout")).layout;
}

/** The active cluster's paths; `check` also asks the execution host whether each exists and is writable. */
export function fetchClusterPaths(check = false): Promise<ClusterPaths> {
  return getJson<ClusterPaths>(`/api/cluster-paths${check ? "?check=1" : ""}`);
}

/** The layout, loaded once per mount. Empty until it arrives, or if it cannot be read. */
export function usePathLayout(): PathLayoutEntry[] {
  const [layout, setLayout] = useState<PathLayoutEntry[]>([]);
  useEffect(() => {
    let live = true;
    fetchPathLayout()
      .then((l) => {
        if (live) setLayout(l);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  return layout;
}

/** `<root>/<suffix>` for one layout key, or "" when there is no root or no such key. */
export function derivedPath(layout: PathLayoutEntry[], root: string, key: string): string {
  const base = root.trim().replace(/\/+$/, "");
  const entry = layout.find((e) => e.key === key);
  return base && entry ? `${base}/${entry.suffix}` : "";
}
