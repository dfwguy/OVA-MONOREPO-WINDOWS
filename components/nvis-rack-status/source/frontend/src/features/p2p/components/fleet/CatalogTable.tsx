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
// The catalog, read-only, with where each image stands on the fleet.
// Author: Rafael M. Koike
//
// The catalog is authored on the Catalog page; here it is a report, one row per image: who needs
// it, how many nodes hold it verified, whether the origin can serve it, whether the object store
// holds it. The two row actions are the two things an operator does with an image from here:
// distribute it (a new campaign, pre-filled) and persist it into the object store the seeds serve.
import { Button, Flex, ProgressBar, Table, Tag, Text } from "@nvidia/foundations-react-core";
import { holders } from "../../lib/campaigns";
import type { CatalogImage, NodeCoverage } from "../../types/fleet";

export type CatalogTableProps = {
  images: CatalogImage[];
  nodes: NodeCoverage[];
  /** Why the mutating row actions are unavailable (an operation running, no instance), or null. */
  blocked: string | null;
  onDistribute: (filename: string) => void;
  onPersist: (filename: string) => void;
};

function gigabytes(bytes: number): string {
  return `${(bytes / 1e9).toFixed(2)} GB`;
}

export function CatalogTable({ images, nodes, blocked, onDistribute, onPersist }: CatalogTableProps) {
  const total = nodes.length;
  const rows = [...images]
    .sort((a, b) => a.order - b.order)
    .map((image) => {
      const held = holders(nodes, image.filename);
      const percent = total ? Math.round((held / total) * 100) : 0;
      const imported = Boolean(image.persistent_import?.length);
      return {
        id: image.filename,
        cells: [
          {
            children: (
              <Flex direction="column" gap="1">
                <Text kind="body/bold/sm">{image.name || image.filename}</Text>
                <Text kind="mono/sm" style={{ color: "var(--text-color-secondary)" }}>{image.filename}</Text>
              </Flex>
            ),
          },
          {
            children: (
              <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)", display: "block", maxWidth: 260 }}>
                {image.required_by?.length ? image.required_by.join(", ") : "—"}
              </Text>
            ),
          },
          gigabytes(image.bytes),
          {
            children: (
              <Flex direction="column" gap="1" style={{ minWidth: 120 }}>
                <Text kind="mono/sm">{`${held.toLocaleString()} / ${total.toLocaleString()} (${percent}%)`}</Text>
                <ProgressBar size="small" value={percent} aria-label={`${image.filename}: ${percent}% of the fleet holds it verified`} />
              </Flex>
            ),
          },
          {
            children: (
              <Tag color={image.canonical_present ? "green" : "yellow"} kind="outline" readOnly density="compact">
                {image.canonical_present ? "present" : "missing"}
              </Tag>
            ),
          },
          {
            children: (
              <Tag color={imported ? "green" : "gray"} kind="outline" readOnly density="compact">
                {imported ? "imported" : "not imported"}
              </Tag>
            ),
          },
          {
            children: (
              <Flex gap="2" style={{ whiteSpace: "nowrap" }}>
                <Button
                  kind="secondary"
                  color="neutral"
                  size="tiny"
                  disabled={!image.canonical_present}
                  title={image.canonical_present ? "Start a campaign for this image" : "Not on the origin, so nothing can serve it"}
                  onClick={() => onDistribute(image.filename)}
                >
                  Distribute…
                </Button>
                <Button
                  kind="secondary"
                  color="neutral"
                  size="tiny"
                  disabled={Boolean(blocked) || !image.canonical_present}
                  title={blocked ?? "Load this image into the object store the seeds serve from"}
                  onClick={() => onPersist(image.filename)}
                >
                  Persist
                </Button>
              </Flex>
            ),
          },
        ],
      };
    });

  // Seven columns do not fit a phone or a narrow pane; the table scrolls inside its card instead of
  // pushing the page sideways.
  return (
    <div style={{ overflowX: "auto", maxWidth: "100%" }}>
    <Table
      aria-label="Catalog images"
      layout="auto"
      density="compact"
      hoverableRows
      columns={["Image", "Required by", "Size", "On the fleet (verified)", "Origin", "Object store", "Actions"]}
      rows={rows}
    />
    </div>
  );
}
