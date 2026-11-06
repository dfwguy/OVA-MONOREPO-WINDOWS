/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { CampaignEdit } from "../services/fleetService";
import type { CatalogImage, FleetStatus, NodeCoverage } from "../types/fleet";
import ArtifactFleetView from "./ArtifactFleetView";

const fleetHook = vi.hoisted(() => ({
  value: {
    status: null as FleetStatus | null,
    error: null as string | null,
    loading: false,
    unauthenticated: false,
    refresh: vi.fn().mockResolvedValue(undefined),
  },
}));
vi.mock("../hooks/useFleetStatus", () => ({ useFleetStatus: () => fleetHook.value }));

const settings = vi.hoisted(() => ({ provision: vi.fn(), getSettings: vi.fn() }));
vi.mock("../services/settingsService", () => settings);
const fleetService = vi.hoisted(() => ({
  startOperation: vi.fn(),
  getRosters: vi.fn(),
  getCampaigns: vi.fn(),
  saveCampaigns: vi.fn(),
  launchCampaign: vi.fn(),
}));
vi.mock("../services/fleetService", () => fleetService);

const IMG = "nvidia+nemo+26.04.01-arm.sqsh";

function image(filename: string, order: number): CatalogImage {
  return {
    order, name: `Image ${order}`, filename, bytes: 42e9, sha256: "a".repeat(64),
    required_by: ["nemo-26.04.01"], canonical_present: true, persistent_import: null,
  };
}

function node(name: string, su: number, held: boolean): NodeCoverage {
  return {
    node: name, su, state: held ? "complete" : "incomplete", present: held ? 1 : 0, verified: held ? 1 : 0,
    unverified: 0, missing: held ? 0 : 1, bad_size: 0, active: 0, images: { [IMG]: held ? "ready" : "missing" },
    observed_at: null,
  };
}

function status(provisioned: boolean, nodes: NodeCoverage[] = []): FleetStatus {
  return {
    provisioned,
    catalog: { canonical_directory: "/d", images: [image(IMG, 1)] },
    object_store_healthy: false,
    fleet: [],
    coverage: { generated_at: null, required_count: 1, required_images: [IMG], by_su: [], nodes },
    sync: null,
    catalog_exact_duplicates: [],
    preflight_generated_at: null,
    operations: [],
  };
}

// NC's shape: SUs past 14 with gaps, and a node the producer could not place.
const FLEET = [node("a-su1", 1, true), node("b-su20", 20, false), node("c-su37", 37, false), node("d", 0, false)];

function renderView(campaigns: CampaignEdit[] = []) {
  fleetService.getRosters.mockResolvedValue({ ok: true, cluster_id: "c1", rosters: [] });
  fleetService.getCampaigns.mockResolvedValue({ ok: true, cluster_id: "c1", campaigns });
  settings.getSettings.mockResolvedValue({ rollout_strategy: "rack-staged", rollout_stages: ["1", "50%", "100%"], rollout_wave_size: 25 });
  return render(
    <MemoryRouter>
      <ArtifactFleetView />
    </MemoryRouter>,
  );
}

beforeAll(() => {
  // jsdom lays nothing out, so it has no scrollIntoView; "Show on map" scrolls to the map.
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ArtifactFleetView provisioning gate", () => {
  it("shows the provision gate and keeps campaigns from starting on a bare cluster", () => {
    fleetHook.value.status = status(false);
    renderView();
    expect(screen.getByText(/not provisioned yet/i)).toBeInTheDocument();
    for (const button of screen.getAllByRole("button", { name: /New campaign/i })) expect(button).toBeDisabled();
  });

  it("starts provisioning when the operator clicks Provision", () => {
    settings.provision.mockResolvedValue({ ok: true, run_id: "run-123", poll: "/api/workflow-runs/run-123" });
    fleetHook.value.status = status(false);
    renderView();
    fireEvent.click(screen.getByRole("button", { name: /Provision P2P instance/i }));
    expect(settings.provision).toHaveBeenCalledTimes(1);
  });

  it("hides the gate and enables New campaign once provisioned", () => {
    fleetHook.value.status = status(true);
    renderView();
    expect(screen.queryByText(/not provisioned yet/i)).not.toBeInTheDocument();
    for (const button of screen.getAllByRole("button", { name: /New campaign/i })) expect(button).toBeEnabled();
  });
});

describe("ArtifactFleetView coverage map", () => {
  it("shows every SU the snapshot holds, with no separate SU scope to narrow it", () => {
    fleetHook.value.status = status(true, FLEET);
    renderView();
    expect(screen.getByText(/4 nodes across 4 SUs/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "All SUs" })).not.toBeInTheDocument();
    for (const label of ["SU1", "SU20", "SU37", "No SU"]) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
  });

  it("narrows the map to a tone from the status strip, and back", () => {
    fleetHook.value.status = status(true, FLEET);
    renderView();
    fireEvent.click(within(screen.getByRole("group", { name: "Incomplete" })).getByRole("button", { name: "Show on map" }));
    expect(screen.getByText(/3 nodes across 3 SUs/)).toBeInTheDocument();
    expect(screen.getByText("Only incomplete nodes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(screen.getByText(/4 nodes across 4 SUs/)).toBeInTheDocument();
  });

  it("explains both channels with the swatches the grid uses", () => {
    fleetHook.value.status = status(true, FLEET.slice(0, 1));
    renderView();
    const key = screen.getByRole("group", { name: "Colour key" });
    expect(key).toHaveTextContent("Fill · catalog progress");
    expect(key).toHaveTextContent("Border · content trust");
    for (const label of ["Complete", "Syncing", "Incomplete", "Unavailable",
      "Verified", "Never hashed", "Wrong size", "Not checked"]) {
      expect(key).toHaveTextContent(label);
    }
  });
});

describe("ArtifactFleetView catalog", () => {
  it("reports each image read-only, with how much of the fleet holds it", () => {
    fleetHook.value.status = status(true, FLEET);
    renderView();
    const table = screen.getByRole("table", { name: "Catalog images" });
    expect(table).toHaveTextContent(IMG);
    expect(table).toHaveTextContent("1 / 4 (25%)");
    expect(table).toHaveTextContent("not imported");
    expect(within(table).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("persists one image into the object store from its row", async () => {
    fleetService.startOperation.mockResolvedValue({ id: "op-p" });
    fleetHook.value.status = status(true, FLEET);
    renderView();
    fireEvent.click(within(screen.getByRole("table", { name: "Catalog images" })).getByRole("button", { name: "Persist" }));
    await waitFor(() => expect(fleetService.startOperation).toHaveBeenCalledTimes(1));
    expect(fleetService.startOperation.mock.calls[0][0]).toEqual({ action: "persist", sus: [], images: [IMG], roster: "" });
  });
});

describe("ArtifactFleetView new campaign wizard", () => {
  it("walks task, roster, plan and review, then saves and launches the campaign", async () => {
    const existing = { name: "old", image: IMG } as CampaignEdit;
    fleetService.saveCampaigns.mockImplementation((campaigns: CampaignEdit[]) =>
      Promise.resolve({ ok: true, cluster_id: "c1", campaigns }));
    fleetService.launchCampaign.mockResolvedValue({ id: "op-c" });
    fleetHook.value.status = status(true, FLEET);
    renderView([existing]);
    await waitFor(() => expect(screen.getByRole("table", { name: "Campaigns" })).toHaveTextContent("old"));

    // From the catalog row, so the task is already chosen.
    fireEvent.click(within(screen.getByRole("table", { name: "Catalog images" })).getByRole("button", { name: "Distribute…" }));
    const wizard = await screen.findByRole("dialog");
    expect(within(wizard).getByLabelText("New campaign progress")).toBeInTheDocument();
    expect(wizard).toHaveTextContent("1 of 4 nodes already hold it");

    fireEvent.click(within(wizard).getByRole("button", { name: "Next" }));
    expect(wizard).toHaveTextContent("4 nodes · 1 already hold");
    fireEvent.click(within(wizard).getByRole("button", { name: "Next" }));
    expect(within(wizard).getByRole("radiogroup", { name: "Wave plan" })).toBeInTheDocument();
    // The plan is drawn: the cluster's own (rack-staged) until the campaign picks another.
    expect(within(wizard).getByRole("img", { name: /Cluster default: rack-staged.*Only stage 1 pulls from the app server's seeds/ })).toBeInTheDocument();
    fireEvent.click(within(wizard).getByRole("radio", { name: "Sequential" }));
    expect(within(wizard).getByRole("img", { name: /Waves take the roster in order, 25 nodes each/ })).toBeInTheDocument();
    fireEvent.click(within(wizard).getByRole("radio", { name: "Cluster default" }));
    fireEvent.click(within(wizard).getByRole("button", { name: "Next" }));

    const save = within(wizard).getByRole("button", { name: "Save and launch" });
    expect(save).toBeDisabled();
    fireEvent.change(within(wizard).getByRole("textbox", { name: "Name" }), { target: { value: "old" } });
    expect(save).toBeDisabled(); // a duplicate name is refused, as the backend would
    fireEvent.change(within(wizard).getByRole("textbox", { name: "Name" }), { target: { value: "nemo-fleet" } });
    expect(wizard).toHaveTextContent("Roster: Whole fleet, 4 nodes, 3 to receive it");
    fireEvent.click(save);

    await waitFor(() => expect(fleetService.launchCampaign).toHaveBeenCalledTimes(1));
    const saved = fleetService.saveCampaigns.mock.calls[0][0] as CampaignEdit[];
    expect(saved.map((c) => c.name)).toEqual(["old", "nemo-fleet"]);
    expect(saved[1]).toMatchObject({ image: IMG, roster: "", strategy: "" });
    expect(fleetService.launchCampaign.mock.calls[0][0]).toMatchObject({ name: "nemo-fleet", image: IMG });
    expect(await screen.findByText(/nemo-fleet saved and launched/)).toBeInTheDocument();
  });

  it("launches a saved campaign only after confirming it", async () => {
    fleetService.launchCampaign.mockResolvedValue({ id: "op-l" });
    fleetHook.value.status = status(true, FLEET);
    renderView([{ name: "fleet-nemo", image: IMG, roster: "", strategy: "" } as CampaignEdit]);
    const table = await screen.findByRole("table", { name: "Campaigns" });
    await waitFor(() => expect(table).toHaveTextContent("fleet-nemo"));
    fireEvent.click(within(table).getByRole("button", { name: "Launch" }));
    expect(fleetService.launchCampaign).not.toHaveBeenCalled();
    const confirm = await screen.findByRole("dialog");
    expect(confirm).toHaveTextContent("the whole fleet (4 nodes)");
    fireEvent.click(within(confirm).getByRole("button", { name: "Launch" }));
    await waitFor(() => expect(fleetService.launchCampaign).toHaveBeenCalledTimes(1));
  });
});

describe("ArtifactFleetView maintenance", () => {
  it("runs fleet maintenance on the whole fleet, under the names an operator reads", async () => {
    fleetService.startOperation.mockResolvedValue({ id: "op-v" });
    fleetHook.value.status = status(true, FLEET);
    renderView();
    expect(screen.getByRole("button", { name: "Maintenance" })).toBeInTheDocument();
    // KUI's Dropdown is a native popover, which jsdom does not implement: the menu is rendered but
    // never shown, so the item is selected directly -- its onSelect is the code under test.
    fireEvent.click(screen.getByRole("menuitem", { name: "Audit fleet", hidden: true }));
    await waitFor(() => expect(fleetService.startOperation).toHaveBeenCalledTimes(1));
    expect(fleetService.startOperation.mock.calls[0][0]).toEqual({ action: "verify", sus: [], images: [], roster: "" });
    expect(screen.queryByRole("button", { name: /Install peers/i })).not.toBeInTheDocument();
  });
});
