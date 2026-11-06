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
import { Flex, Text } from "@nvidia/foundations-react-core";
import type { ForecastBucket } from "../types";
import { OPEN_COLOR, PASSED_COLOR, TRACK_COLOR, formatCount } from "../lib/forecastModel";

/**
 * Open racks grouped by how many nodes they still wait on, as the tracker's step bars. A rack
 * missing none is ready for its rack runs now and is drawn in the passed colour.
 */
export function RackBuckets({ buckets }: { buckets: ForecastBucket[] }) {
  const most = Math.max(1, ...buckets.map((b) => b.racks));
  return (
    <Flex direction="col" gap="2" role="list" aria-label="Open racks by nodes missing">
      {buckets.map((b) => (
        <div
          key={b.label}
          role="listitem"
          data-testid={`bucket-${b.label}`}
          style={{ display: "grid", gridTemplateColumns: "88px 1fr 150px", alignItems: "center", gap: 12 }}
        >
          <Text kind="body/bold/sm">{b.label === "0" ? "Ready" : `${b.label} missing`}</Text>
          <div style={{ height: 10, borderRadius: 5, background: TRACK_COLOR, overflow: "hidden" }}>
            <div
              style={{
                width: `${(100 * b.racks) / most}%`,
                height: "100%",
                background: b.min === 0 ? PASSED_COLOR : OPEN_COLOR,
                opacity: b.min === 0 ? 1 : 0.35 + Math.min(0.65, b.min / 10),
              }}
            />
          </div>
          <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)", textAlign: "right" }}>
            {formatCount(b.racks)} rack{b.racks === 1 ? "" : "s"}
            {b.nodes_missing ? ` · ${formatCount(b.nodes_missing)} nodes` : ""}
          </Text>
        </div>
      ))}
    </Flex>
  );
}
