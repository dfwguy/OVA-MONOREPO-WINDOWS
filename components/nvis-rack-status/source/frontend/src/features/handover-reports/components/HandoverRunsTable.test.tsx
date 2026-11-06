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
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { LLM_RUN, NCCL_RUN } from "../__fixtures__/handover";
import type { HandoverRun } from "../types";
import { HandoverRunsTable, type HandoverRunsTableProps } from "./HandoverRunsTable";

/** Run *i*: job 300000+i, i GPUs, created i minutes after midnight, so every column orders the same way. */
const run = (i: number, over: Partial<HandoverRun> = {}): HandoverRun => ({
  ...NCCL_RUN,
  activity_id: `run-${i}`,
  scheduler_job_ids: [String(300000 + i)],
  created_at: new Date(Date.UTC(2026, 9, 28, 0, i)).toISOString(),
  gpus: i,
  ...over,
});
/** Newest first, the way the API sends them. */
const many = (n: number) => Array.from({ length: n }, (_, i) => run(n - i));

const renderTable = (runs: HandoverRun[], props: Partial<HandoverRunsTableProps> = {}) => {
  const all: HandoverRunsTableProps = { runs, selected: new Set(), onToggle: vi.fn(), onView: vi.fn(), ...props };
  const view = render(<HandoverRunsTable {...all} />);
  return { ...view, rerenderWith: (next: Partial<HandoverRunsTableProps>) => view.rerender(<HandoverRunsTable {...all} {...next} />) };
};

const table = () => screen.getByRole("table", { name: "Multi-rack runs" });
/** The Job column of each rendered row, in order. */
const jobs = () =>
  within(table())
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.querySelectorAll("td")[2]?.textContent ?? "");
const header = (name: string) => within(table()).getAllByRole("columnheader").find((h) => h.textContent === name)!;

describe("HandoverRunsTable", () => {
  describe("racks", () => {
    it("names a short rack list in full, with no tooltip to hover", () => {
      renderTable([NCCL_RUN]);
      expect(screen.getByText("U2, W19")).toBeInTheDocument();
      expect(screen.getByText("SU20, SU27")).toBeInTheDocument();
      expect(screen.queryByTestId(`racks-${NCCL_RUN.activity_id}`)).not.toBeInTheDocument();
    });

    it("trims a long rack list to the first four and puts the whole list on hover", () => {
      const racks = ["Q19", "V5", "W23", "W6", "X8", "Q22"];
      const sus = ["SU21", "SU24", "SU27", "SU28", "SU32"];
      renderTable([{ ...NCCL_RUN, racks, scalable_units: sus }]);
      expect(screen.getByText("Q19, V5, W23, W6, …")).toBeInTheDocument();
      expect(screen.getByText("SU21, SU24, SU27, SU28, …")).toBeInTheDocument();
      expect(screen.getByTestId(`racks-${NCCL_RUN.activity_id}`)).toHaveAttribute(
        "aria-label",
        "6 racks: Q19, V5, W23, W6, X8, Q22. 5 scalable units: SU21, SU24, SU27, SU28, SU32",
      );
    });
  });

  describe("pagination", () => {
    it("shows 25 runs a page by default and offers 10, 25, 50 and 100", () => {
      renderTable(many(60));
      expect(jobs()).toHaveLength(25);
      expect(jobs()[0]).toBe("300060");
      expect(screen.getByText(/1–25 of 60 runs/)).toBeInTheDocument();
      fireEvent.click(screen.getByLabelText("Go to next page"));
      expect(jobs()[0]).toBe("300035");
      expect(screen.getByText(/26–50 of 60 runs/)).toBeInTheDocument();
    });

    it("draws no pager when every run fits on one page", () => {
      renderTable([NCCL_RUN, LLM_RUN]);
      expect(screen.queryByLabelText("Go to next page")).not.toBeInTheDocument();
    });

    it("keeps its page when a refresh hands it the same runs again", () => {
      /** The view polls every 5 s while runs summarize; each poll is a new array. */
      const { rerenderWith } = renderTable(many(60));
      fireEvent.click(screen.getByLabelText("Go to next page"));
      rerenderWith({ runs: many(60) });
      expect(jobs()[0]).toBe("300035");
    });

    it("goes back to page 1 when the filters change", () => {
      const { rerenderWith } = renderTable(many(60), { filterKey: "all" });
      fireEvent.click(screen.getByLabelText("Go to next page"));
      rerenderWith({ runs: many(60), filterKey: "SU27" });
      expect(jobs()[0]).toBe("300060");
    });
  });

  describe("sorting", () => {
    it("sorts by GPUs ascending, then descending, then back to the API's order", () => {
      renderTable([run(2), run(9), run(5)]);
      fireEvent.click(header("GPUs"));
      expect(jobs()).toEqual(["300002", "300005", "300009"]);
      expect(header("GPUs")).toHaveAttribute("aria-sort", "ascending");
      fireEvent.click(header("GPUs"));
      expect(jobs()).toEqual(["300009", "300005", "300002"]);
      expect(header("GPUs")).toHaveAttribute("aria-sort", "descending");
      fireEvent.click(header("GPUs"));
      expect(jobs()).toEqual(["300002", "300009", "300005"]);
      expect(header("GPUs")).toHaveAttribute("aria-sort", "none");
    });

    it("sorts across every page, not just the one on screen, and returns to page 1", () => {
      renderTable(many(60));
      fireEvent.click(screen.getByLabelText("Go to next page"));
      fireEvent.click(header("Date (UTC)"));
      expect(jobs()[0]).toBe("300001"); // the oldest of all 60, not of page 2
    });

    it("keeps runs that did not measure a column at the bottom both ways", () => {
      const unmeasured = run(7, { collectives: {} });
      renderTable([unmeasured, run(1), run(3)]);
      const ar = header("AR @2 GB (GB/s)");
      fireEvent.click(ar);
      expect(jobs().at(-1)).toBe("300007");
      fireEvent.click(ar);
      expect(jobs().at(-1)).toBe("300007");
    });

    it("does not make the checkbox or View columns sortable", () => {
      renderTable([NCCL_RUN]);
      const unlabelled = within(table())
        .getAllByRole("columnheader")
        .filter((h) => h.textContent === "");
      expect(unlabelled).toHaveLength(2);
      unlabelled.forEach((h) => expect(h).not.toHaveAttribute("aria-sort"));
    });
  });
});
