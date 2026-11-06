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
import type { ReactNode } from "react";
import { Card, Flex, Text } from "@nvidia/foundations-react-core";

/**
 * One titled card of a fleet report. Shared by the deployment tracker and the cluster forecast so
 * the two read as one family of pages, in the app and when published.
 */
export function Section({ title, caption, children }: { title: string; caption?: string; children: ReactNode }) {
  return (
    <Card>
      <Flex direction="col" gap="3">
        <Flex align="baseline" gap="2" wrap="wrap">
          <Text kind="title/sm">{title}</Text>
          {caption ? (
            <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
              {caption}
            </Text>
          ) : null}
        </Flex>
        {children}
      </Flex>
    </Card>
  );
}
