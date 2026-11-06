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
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClusterPaths } from "../services/clusterPathsService";
import { ClusterPathsPanel } from "./ClusterPathsPanel";

const service = vi.hoisted(() => ({ fetchClusterPaths: vi.fn() }));
vi.mock("../services/clusterPathsService", () => service);

const PATHS: ClusterPaths = {
  ok: true,
  cluster: { id: "default", name: "Nscale-NC" },
  root: "/home/cmods",
  paths: [
    { key: "scripts", label: "Rack Status scripts", path: "/home/cmods/nvis-rack-status", source: "root", env: [], purpose: "", field: "connection.remote_base_path" },
    { key: "logs", label: "Job logs", path: "/home/cmods/nvis/logs", source: "root", env: [], purpose: "", field: "connection.log_dir" },
    { key: "bug_reports", label: "Reports", path: "/srv/reports", source: "override", env: [], purpose: "", field: "connection.bug_report_dir" },
    { key: "workspace", label: "Workspace", path: "/old/workspace", source: "environment", env: [], purpose: "", field: "connection.workspace_dir" },
  ],
  exceptions: [
    { key: "images_node", label: "Node image cache (P2P destination)", path: "/opt/containers", source: "p2p", env: [], purpose: "", field: "connection.node_container_dir" },
  ],
};

afterEach(() => vi.clearAllMocks());

describe("ClusterPathsPanel", () => {
  it("lists the root, every path with where it came from, and the image exceptions", async () => {
    service.fetchClusterPaths.mockResolvedValue(PATHS);
    render(<ClusterPathsPanel />);
    expect(await screen.findByText("/home/cmods")).toBeInTheDocument();
    expect(screen.getByTestId("path-scripts")).toHaveTextContent("from root");
    expect(screen.getByTestId("path-bug_reports")).toHaveTextContent("override");
    // A value only the environment gives is the thing to move onto the record, and says so.
    expect(screen.getByTestId("path-workspace")).toHaveTextContent("move onto the record");
    expect(screen.getByTestId("path-images_node")).toHaveTextContent("P2P");
    expect(service.fetchClusterPaths).toHaveBeenCalledWith(false);
  });

  it("checks the folders on the cluster when asked, and shows which are missing or read-only", async () => {
    service.fetchClusterPaths.mockResolvedValueOnce(PATHS);
    render(<ClusterPathsPanel />);
    await screen.findByText("/home/cmods");
    service.fetchClusterPaths.mockResolvedValueOnce({
      ...PATHS,
      checked_on: "execution host",
      paths: [
        { ...PATHS.paths[0], exists: true, writable: true },
        { ...PATHS.paths[1], exists: false, writable: false },
        { ...PATHS.paths[2], exists: true, writable: false },
        PATHS.paths[3],
      ],
    });
    fireEvent.click(screen.getByRole("button", { name: /check on cluster/i }));
    await waitFor(() => expect(service.fetchClusterPaths).toHaveBeenLastCalledWith(true));
    expect(await screen.findByText(/checked on the execution host/)).toBeInTheDocument();
    expect(screen.getByTestId("path-scripts")).toHaveTextContent("ok");
    expect(screen.getByTestId("path-logs")).toHaveTextContent("missing");
    expect(screen.getByTestId("path-bug_reports")).toHaveTextContent("read-only");
  });
});
