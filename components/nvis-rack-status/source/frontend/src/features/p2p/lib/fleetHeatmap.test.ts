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
import {
  COVERAGE_FILL,
  COVERAGE_LABEL,
  COVERAGE_MEANING,
  INTEGRITY_BORDER,
  INTEGRITY_LABEL,
  INTEGRITY_MEANING,
  integrityBorderWidth,
  presentSus,
  suLabel,
} from "./fleetHeatmap";

describe("presentSus", () => {
  it("offers the SUs the snapshot holds, gaps and all, in order", () => {
    // NC's shape: SU3 and SU13 do not exist, and the fleet runs past SU14 to SU37.
    const nodes = [37, 1, 20, 1, 14, 2, 20].map((su) => ({ su }));
    expect(presentSus(nodes)).toEqual([1, 2, 14, 20, 37]);
  });

  it("is empty before a snapshot exists", () => {
    expect(presentSus([])).toEqual([]);
  });
});

describe("suLabel", () => {
  it("names an SU, and says when the producer could not place a node", () => {
    expect(suLabel(19)).toBe("SU19");
    expect(suLabel(0)).toBe("No SU");
  });
});

describe("the colour key", () => {
  it("names and explains every fill and every border the grid can draw", () => {
    for (const tone of Object.keys(COVERAGE_FILL) as (keyof typeof COVERAGE_FILL)[]) {
      expect(COVERAGE_LABEL[tone]).toBeTruthy();
      expect(COVERAGE_MEANING[tone]).toBeTruthy();
    }
    for (const tone of Object.keys(INTEGRITY_BORDER) as (keyof typeof INTEGRITY_BORDER)[]) {
      expect(INTEGRITY_LABEL[tone]).toBeTruthy();
      expect(INTEGRITY_MEANING[tone]).toBeTruthy();
    }
  });

  it("thickens only the wrong-size border", () => {
    expect(integrityBorderWidth("corrupt")).toBe(2);
    for (const tone of ["verified", "unverified", "unknown"] as const) expect(integrityBorderWidth(tone)).toBe(1);
  });
});
