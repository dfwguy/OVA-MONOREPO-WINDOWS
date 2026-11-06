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
import { describe, expect, it } from "vitest";
import { LLM_RUN, NCCL_RUN } from "../__fixtures__/handover";
import {
  bandPoints,
  commandBlock,
  formatGbps,
  formatPct,
  formatSize,
  formatSuRacks,
  formatWhen,
  jobLabel,
  matchesQuery,
  modelLabel,
  shortNodelist,
} from "./handoverModel";

describe("handoverModel", () => {
  it("prints a size nccl-tests rounded to divide across ranks as the size it stands for", () => {
    expect(formatSize(17179869180)).toBe("16 GB");
    expect(formatSize(2 * 1024 ** 3)).toBe("2 GB");
    expect(formatSize(1536 * 1024 ** 2)).toBe("1.5 GB");
    expect(formatSize(null)).toBe("—");
  });

  it("formats bandwidth and time, with a dash for what was not measured", () => {
    expect(formatGbps(176.854)).toBe("176.9");
    expect(formatGbps(null)).toBe("—");
    expect(formatWhen("2026-10-24T19:27:34+00:00")).toBe("2026-10-24 19:27 UTC");
  });

  it("keeps a curve's points from 2 GB to 16 GB, rounded sizes included", () => {
    const GIB = 1024 ** 3;
    const pts = [1, 2, 4, 8, 16, 32].map((g) => ({ size_bytes: g * GIB, busbw_gbps: g }));
    pts[4] = { size_bytes: 17179869180, busbw_gbps: 16 };
    expect(bandPoints(pts).map((p) => p.busbw_gbps)).toEqual([2, 4, 8, 16]);
    expect(bandPoints(undefined)).toEqual([]);
  });

  it("writes a collective's program as its exports then its command", () => {
    const block = commandBlock({
      collective: "alltoall",
      source: "stated",
      env: { NCCL_BUFFSIZE: "8388608", UCX_TLS: "" },
      ld_library_path: "/opt/nccl/lib",
      command: "mpirun -np 8 alltoall_perf",
    });
    expect(block.split("\n")).toEqual([
      "# All-to-all (stated)",
      "export LD_LIBRARY_PATH=/opt/nccl/lib",
      "export NCCL_BUFFSIZE=8388608",
      "export UCX_TLS=<not recorded>",
      "mpirun -np 8 alltoall_perf",
    ]);
  });

  it("prints a share of the ceiling and the racks per scalable unit", () => {
    expect(formatPct(74.5)).toBe("74.5%");
    expect(formatPct(null)).toBe("—");
    expect(formatSuRacks({ SU20: 6, SU23: 2 })).toBe("SU20 x6, SU23 x2");
    expect(formatSuRacks({})).toBe("—");
  });

  it("summarizes the launcher's node list, which the nodes table already gives", () => {
    expect(shortNodelist("./run.sh --nodelist a,b,c U2 U3")).toBe("./run.sh --nodelist <3 nodes, see Nodes> U2 U3");
    expect(shortNodelist("./run.sh U2")).toBe("./run.sh U2");
  });

  it("labels the model and the job", () => {
    expect(modelLabel(LLM_RUN)).toBe("nemotronh 56b");
    expect(modelLabel(NCCL_RUN)).toBe("—");
    expect(jobLabel(NCCL_RUN)).toBe("221301");
    expect(jobLabel({ ...NCCL_RUN, scheduler_job_ids: [] })).toBe("3989e310");
  });

  it("matches every search term against racks, SUs, jobs and the model", () => {
    expect(matchesQuery(LLM_RUN, "su26 nemotron")).toBe(true);
    expect(matchesQuery(NCCL_RUN, "U2 221301")).toBe(true);
    expect(matchesQuery(NCCL_RUN, "nemotron")).toBe(false);
    expect(matchesQuery(NCCL_RUN, "  ")).toBe(true);
  });
});
