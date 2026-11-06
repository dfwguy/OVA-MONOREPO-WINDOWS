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
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// Artifact Distribution: where the catalog stands on the fleet, and the campaigns that move it.
//
// The page is built on the four things distribution is made of -- the catalog (what exists), a task
// (one image), a roster (which nodes) and a campaign (task + roster + plan, launched as a run) -- and
// answers two questions in order: what is happening (campaigns), and where things are (the status
// strip and the coverage map). The catalog appears read-only, as a report with per-image actions;
// it is authored on the Catalog page. There is no separate SU scope: a roster already says which
// nodes, and SU is how the map is grouped. Fleet-wide maintenance (eligibility, audit, pushing the
// catalog file) sits in one menu, because it is occasional rather than the page's purpose.
//
// Button policy is this app's bordered-only rule: the primary CTA is solid brand, everything
// routine is bordered neutral, and anything destructive is solid danger.
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Banner,
  Button,
  Card,
  Dropdown,
  Flex,
  FormField,
  Modal,
  ModalCloseButton,
  ProgressBar,
  Select,
  Skeleton,
  Tag,
  Text,
} from "@nvidia/foundations-react-core";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import { Plus, RefreshCw, Rocket, Settings as SettingsIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { NodeHeatmap } from "../components/fleet/NodeHeatmap";
import { CatalogTable } from "../components/fleet/CatalogTable";
import { CampaignsTable } from "../components/campaign/CampaignsTable";
import { NewCampaignWizard } from "../components/campaign/NewCampaignWizard";
import { OperationLogDialog } from "../components/OperationLogDialog";
import { useFleetStatus } from "../hooks/useFleetStatus";
import { getCampaigns, getRosters, launchCampaign, startOperation } from "../services/fleetService";
import type { CampaignEdit, RolloutStrategy, RosterEdit } from "../services/fleetService";
import { getSettings, provision } from "../services/settingsService";
import { ApiError } from "../lib/apiFetch";
import { COVERAGE_LABEL, coverageToneOf, integrityExceptions, integrityToneOf, toneCounts } from "../lib/fleetHeatmap";
import type { CoverageTone } from "../lib/fleetHeatmap";
import type { Operation, OperationAction } from "../types/fleet";

/** The Select value for the whole fleet (no named roster) in the map filter. */
const WHOLE_FLEET = "__whole_fleet__";

/** Fleet maintenance, named for what each does. They act on the whole fleet (the default inventory). */
const MAINTENANCE: { action: OperationAction; label: string }[] = [
  { action: "preflight", label: "Check eligibility" },
  { action: "verify", label: "Audit fleet" },
  { action: "sync", label: "Push catalog to nodes" },
];

/** A status tile: a figure, what it counts, and an optional way to see those nodes on the map. */
function Tile({ label, value, detail, onShow }: { label: string; value: string; detail: string; onShow?: () => void }) {
  return (
    <Card role="group" aria-label={label}>
      <Flex direction="column" gap="1">
        <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>{label}</Text>
        <Text kind="title/lg">{value}</Text>
        <Text kind="body/regular/sm" style={{ color: "var(--text-color-subtle)" }}>{detail}</Text>
        {onShow ? (
          <Flex>
            <Button kind="secondary" color="neutral" size="tiny" onClick={onShow}>Show on map</Button>
          </Flex>
        ) : null}
      </Flex>
    </Card>
  );
}

export default function ArtifactFleetView() {
  const { status, error, loading, unauthenticated, refresh } = useFleetStatus();
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [provisionBusy, setProvisionBusy] = useState(false);
  const [logOp, setLogOp] = useState<Operation | null>(null);
  const [rosters, setRosters] = useState<RosterEdit[]>([]);
  const [campaigns, setCampaigns] = useState<CampaignEdit[]>([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardImage, setWizardImage] = useState<string | undefined>(undefined);
  // Bumped per opening so the wizard remounts with fresh state.
  const [wizardKey, setWizardKey] = useState(0);
  const [confirmLaunch, setConfirmLaunch] = useState<CampaignEdit | null>(null);
  const [launching, setLaunching] = useState(false);
  // The coverage map's filter: a roster (blank = whole fleet) and a coverage tone (null = all).
  const [mapRoster, setMapRoster] = useState("");
  const [mapTone, setMapTone] = useState<CoverageTone | null>(null);
  const [rolloutDefaults, setRolloutDefaults] = useState<{ strategy: RolloutStrategy; stages: string[]; waveSize: number } | null>(null);

  useEffect(() => {
    let live = true;
    void getRosters()
      .then((doc) => { if (live) setRosters(doc.rosters); })
      .catch(() => { if (live) setRosters([]); });
    void getCampaigns()
      .then((doc) => { if (live) setCampaigns(doc.campaigns); })
      .catch(() => { if (live) setCampaigns([]); });
    // The wave plan a campaign inherits, so the wizard can draw "Cluster default" as what it is.
    void getSettings()
      .then((s) => {
        if (live) setRolloutDefaults({ strategy: s.rollout_strategy, stages: s.rollout_stages ?? [], waveSize: s.rollout_wave_size });
      })
      .catch(() => { if (live) setRolloutDefaults(null); });
    return () => { live = false; };
  }, []);
  const navigate = useNavigate();

  // Enabled-but-bare clusters report `provisioned: false`: the catalog still lists the shipped
  // images, but there is no Dragonfly instance, so operations would 501 and the fleet is empty.
  const notProvisioned = status?.provisioned === false;
  const images = status?.catalog.images ?? [];
  const nodes = useMemo(() => status?.coverage.nodes ?? [], [status]);
  const requiredCount = status?.coverage.required_count ?? 0;
  const operations = useMemo(() => status?.operations ?? [], [status]);

  const running = useMemo(() => operations.find((operation) => operation.state === "running") ?? null, [operations]);
  // One reason every mutating control shares, so they agree on when they are available.
  const blocked = notProvisioned
    ? "this cluster's P2P instance is not provisioned"
    : running
      ? `a ${running.action} operation is running`
      : null;

  const counts = useMemo(() => toneCounts(nodes, requiredCount), [nodes, requiredCount]);
  const exceptions = useMemo(() => integrityExceptions(nodes), [nodes]);

  const mapNodes = useMemo(() => {
    const roster = rosters.find((r) => r.name === mapRoster);
    const inRoster = roster ? new Set(roster.nodes) : null;
    return nodes.filter(
      (node) => (!inRoster || inRoster.has(node.node)) && (!mapTone || coverageToneOf(node, requiredCount) === mapTone),
    );
  }, [nodes, rosters, mapRoster, mapTone, requiredCount]);

  const reportStartError = useCallback((reason: unknown, what: string) => {
    // 409 is the server's single-mutation lock, which is a normal answer an operator needs to read.
    if (reason instanceof ApiError && reason.status === 409) {
      setActionError("Another fleet operation is already running. Wait for it to finish.");
      return;
    }
    setActionError(reason instanceof Error ? reason.message : `${what} failed to start`);
  }, []);

  const runOperation = useCallback(
    async (action: OperationAction, label: string, operationImages: string[] = []) => {
      setActionError(null);
      setNotice(null);
      try {
        const operation = await startOperation({ action, sus: [], images: operationImages, roster: "" });
        setNotice(`${label} started on the whole fleet. Operation ${operation.id}.`);
        await refresh();
      } catch (reason) {
        reportStartError(reason, label);
      }
    },
    [refresh, reportStartError],
  );

  const onLaunch = useCallback(async () => {
    if (!confirmLaunch) return;
    setLaunching(true);
    setActionError(null);
    setNotice(null);
    try {
      const operation = await launchCampaign(confirmLaunch);
      setNotice(`Campaign ${confirmLaunch.name} launched. Operation ${operation.id}.`);
      setConfirmLaunch(null);
      await refresh();
    } catch (reason) {
      setConfirmLaunch(null);
      reportStartError(reason, `Campaign ${confirmLaunch.name}`);
    } finally {
      setLaunching(false);
    }
  }, [confirmLaunch, refresh, reportStartError]);

  // A manual refresh with visible feedback: `loading` only covers the first fetch, so without this
  // the button fires silently and reads as dead.
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      setRefreshing(false);
    }
  }, [refresh]);

  // Provisioning is the one fleet action available on a bare cluster: it starts the reconcile
  // workflow that stands up this cluster's Dragonfly instance. A 400 carries `provisioning_blockers`
  // -- the settings are incomplete -- which is a instruction to the operator, not a failure.
  const onProvision = useCallback(async () => {
    setActionError(null);
    setNotice(null);
    setProvisionBusy(true);
    try {
      const res = await provision();
      setNotice(`Provisioning started (run ${res.run_id}). Track it under Tools → Workflows; this page updates when the instance comes up.`);
      await refresh();
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 400) {
        const blockers =
          reason.body && typeof reason.body === "object" && "provisioning_blockers" in reason.body
            ? ((reason.body as { provisioning_blockers?: unknown }).provisioning_blockers ?? [])
            : [];
        const list = Array.isArray(blockers) && blockers.length ? `: ${blockers.join(", ")}` : "";
        setActionError(`P2P settings are incomplete${list}. Finish them in Dragonfly Settings, then provision.`);
        return;
      }
      setActionError(reason instanceof Error ? reason.message : "Failed to start provisioning");
    } finally {
      setProvisionBusy(false);
    }
  }, [refresh]);

  const openWizard = (image?: string) => {
    setWizardImage(image);
    setWizardKey((k) => k + 1);
    setWizardOpen(true);
  };
  const showOnMap = (tone: CoverageTone) => {
    setMapTone(tone);
    document.getElementById("coverage-map")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  if (loading) {
    return (
      <Flex direction="column" gap="3" style={{ padding: 24 }}>
        <Skeleton style={{ height: 48 }} />
        <Skeleton style={{ height: 160 }} />
        <Skeleton style={{ height: 320 }} />
      </Flex>
    );
  }

  const confirmRosterSize = confirmLaunch
    ? confirmLaunch.roster
      ? rosters.find((r) => r.name === confirmLaunch.roster)?.nodes.length ?? 0
      : nodes.length
    : 0;
  const onOrigin = images.filter((image) => image.canonical_present).length;

  return (
    <Flex direction="column" gap="3" style={{ padding: 24, maxWidth: 1880, margin: "0 auto" }}>
      <Flex justify="between" align="start" wrap="wrap" gap="2">
        <Flex direction="column" gap="1">
          <Text kind="body/bold/sm" style={{ color: "var(--text-color-brand)" }}>
            NVIS CONTROL PLANE
          </Text>
          <Text kind="display/sm">Artifact Distribution</Text>
          <Text kind="body/regular/md" style={{ color: "var(--text-color-secondary)" }}>
            Catalog images delivered to the fleet by campaigns: a task (one image), a roster (which
            nodes) and a wave plan.
          </Text>
        </Flex>
        <Flex gap="2" wrap="wrap" align="center">
          <Button kind="secondary" color="neutral" size="small" disabled={refreshing} onClick={() => void onRefresh()}>
            <RefreshCw
              size={16}
              aria-hidden
              style={refreshing ? { animation: "spin 0.8s linear infinite" } : undefined}
            />
            {refreshing ? "Refreshing…" : "Refresh"}
          </Button>
          <Dropdown
            size="small"
            items={MAINTENANCE.map((m) => ({
              children: m.label,
              disabled: Boolean(blocked),
              onSelect: () => void runOperation(m.action, m.label),
            }))}
          >
            Maintenance
          </Dropdown>
          <Button kind="primary" color="brand" size="small" disabled={notProvisioned} onClick={() => openWizard()}>
            <Plus size={16} aria-hidden />
            New campaign
          </Button>
        </Flex>
      </Flex>

      {unauthenticated ? (
        <Banner status="error" kind="inline">
          Session expired, or this account does not hold the root role. Sign in again to continue.
        </Banner>
      ) : null}
      {error && !unauthenticated ? (
        <Banner status="error" kind="inline">
          {error}
        </Banner>
      ) : null}
      {actionError ? (
        <Banner status="warning" kind="inline">
          {actionError}
        </Banner>
      ) : null}
      {notice ? (
        <Banner status="success" kind="inline">
          {notice}
        </Banner>
      ) : null}
      {running ? (
        <Banner status="info" kind="inline">
          {`A ${running.action} operation${running.campaign ? ` (campaign ${running.campaign})` : ""} is running since ${running.started_at}. Launching and maintenance stay locked until it finishes.`}
        </Banner>
      ) : null}

      {notProvisioned ? (
        <Card>
          <Flex direction="column" gap="3">
            <Flex align="center" gap="2">
              <Rocket size={20} aria-hidden style={{ color: "var(--text-color-brand)" }} />
              <Text kind="title/md">This cluster&rsquo;s P2P instance is not provisioned yet</Text>
            </Flex>
            <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
              The catalog below lists the shipped validation images, but there is no Dragonfly
              instance to persist or distribute them, so the tiles read greenfield and campaigns
              cannot launch. Provisioning runs the reconcile workflow that stands up the control
              plane on this cluster&rsquo;s app server; this page fills in once it is up.
            </Text>
            <Flex gap="2" wrap="wrap" align="center">
              <Button
                kind="primary"
                color="brand"
                size="small"
                disabled={provisionBusy}
                onClick={() => void onProvision()}
              >
                <Rocket size={16} aria-hidden />
                {provisionBusy ? "Starting…" : "Provision P2P instance"}
              </Button>
              <Button
                kind="secondary"
                color="neutral"
                size="small"
                onClick={() => navigate("/p2p/settings")}
              >
                <SettingsIcon size={16} aria-hidden />
                Open Dragonfly Settings
              </Button>
            </Flex>
          </Flex>
        </Card>
      ) : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 200px), 1fr))",
          gap: 12,
        }}
      >
        <Tile
          label="Catalog"
          value={`${images.length} images`}
          detail={`${onOrigin} on the origin, ready to distribute`}
        />
        <Tile
          label="Complete"
          value={`${counts.complete.toLocaleString()} / ${nodes.length.toLocaleString()}`}
          detail="nodes holding every required image, verified"
          onShow={() => showOnMap("complete")}
        />
        <Tile
          label="Incomplete"
          value={counts.incomplete.toLocaleString()}
          detail="nodes missing an image or holding one unverified"
          onShow={() => showOnMap("incomplete")}
        />
        <Tile
          label="Unavailable"
          value={counts.unavailable.toLocaleString()}
          detail="nodes that did not answer the last audit"
          onShow={() => showOnMap("unavailable")}
        />
        <Tile
          label="Object store"
          value={status?.object_store_healthy ? "Healthy" : "Unavailable"}
          detail="where Persist puts images for the seeds to serve"
        />
      </div>

      {status?.sync ? (
        <Card>
          <Flex direction="column" gap="2">
            <Flex justify="between" align="center" wrap="wrap" gap="2">
              <Flex direction="column" gap="1">
                <Text kind="title/md">Catalog file on the nodes</Text>
                <Text kind="mono/sm" style={{ color: "var(--text-color-secondary)" }}>
                  {status.sync.id} · updated {status.sync.updated_at}
                </Text>
              </Flex>
              <Tag
                color={
                  status.sync.state === "running"
                    ? "blue"
                    : status.sync.deferred > 0
                      ? "yellow"
                      : "green"
                }
                kind="solid"
                readOnly
                density="compact"
              >
                {status.sync.state.replaceAll("_", " ")}
              </Tag>
            </Flex>
            <ProgressBar
              value={status.sync.percent}
              aria-label={`Catalog sync wave progress: ${status.sync.percent}% complete`}
            />
            <Text kind="body/regular/sm">
              {`${status.sync.complete.toLocaleString()} complete · ${status.sync.pending.toLocaleString()} pending · ${status.sync.deferred.toLocaleString()} deferred · ${status.sync.percent}%`}
            </Text>
            {status.sync.deferred > 0 ? (
              <Text kind="body/regular/sm" style={{ color: "var(--text-color-subtle)" }}>
                Deferred nodes carry a terminal reason and are not retried by this wave. Review them
                before calling the rollout complete.
              </Text>
            ) : null}
          </Flex>
        </Card>
      ) : null}

      <Card>
        <Flex direction="column" gap="3">
          <Flex justify="between" align="center" wrap="wrap" gap="2">
            <Flex direction="column" gap="1">
              <Text kind="title/md">Campaigns</Text>
              <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
                Each campaign distributes one image to one roster with its own wave plan.
              </Text>
            </Flex>
            <Flex gap="2" wrap="wrap">
              <Button kind="secondary" color="neutral" size="small" onClick={() => navigate("/p2p/campaigns")}>
                Edit campaigns
              </Button>
              <Button kind="primary" color="brand" size="small" disabled={notProvisioned} onClick={() => openWizard()}>
                <Plus size={16} aria-hidden />
                New campaign
              </Button>
            </Flex>
          </Flex>
          <CampaignsTable
            campaigns={campaigns}
            rosters={rosters}
            fleetSize={nodes.length}
            operations={operations}
            blocked={blocked}
            onLaunch={(campaign) => setConfirmLaunch(campaign)}
            onShowLog={setLogOp}
          />
        </Flex>
      </Card>

      <div id="coverage-map">
        <Flex direction="column" gap="2">
          <Flex align="end" gap="3" wrap="wrap">
            <FormField slotLabel="Coverage map shows" style={{ minWidth: 260 }}>
              <Select
                aria-label="Coverage map roster"
                items={[
                  { value: WHOLE_FLEET, children: "Whole fleet" },
                  ...rosters.map((r) => ({ value: r.name, children: `Roster: ${r.name}` })),
                ]}
                value={mapRoster || WHOLE_FLEET}
                onValueChange={(v: string) => setMapRoster(v === WHOLE_FLEET ? "" : v)}
              />
            </FormField>
            {mapTone ? (
              <Flex align="center" gap="2">
                <Tag color="blue" kind="outline" readOnly density="compact">{`Only ${COVERAGE_LABEL[mapTone].toLowerCase()} nodes`}</Tag>
                <Button kind="secondary" color="neutral" size="tiny" onClick={() => setMapTone(null)}>Show all</Button>
              </Flex>
            ) : null}
          </Flex>
          <NodeHeatmap
            nodes={mapNodes}
            requiredCount={requiredCount}
            generatedAt={status?.coverage.generated_at ?? null}
          />
        </Flex>
      </div>

      <Card id="catalog">
        <Flex direction="column" gap="3">
          <Flex justify="between" align="center" wrap="wrap" gap="2">
            <Flex direction="column" gap="1">
              <Text kind="title/md">Catalog</Text>
              <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
                What can be distributed, and where each image stands on the fleet. Edited on the Catalog page.
              </Text>
            </Flex>
            <Button kind="secondary" color="neutral" size="small" onClick={() => navigate("/p2p/catalog")}>
              Edit catalog
            </Button>
          </Flex>
          <CatalogTable
            images={images}
            nodes={nodes}
            blocked={blocked}
            onDistribute={(filename) => openWizard(filename)}
            onPersist={(filename) => void runOperation("persist", `Persist ${filename}`, [filename])}
          />
          {status?.catalog_exact_duplicates.length ? (
            <Text kind="body/regular/sm" style={{ color: "var(--text-color-subtle)" }}>
              {`Exact content duplicates in the catalog: ${status.catalog_exact_duplicates.map((set) => set.join(" = ")).join("; ")}. Files of equal size with different digests are not duplicates.`}
            </Text>
          ) : null}
        </Flex>
      </Card>

      {exceptions.length ? (
        <Card>
          <Flex direction="column" gap="2">
            <Flex justify="between" align="center" wrap="wrap" gap="2">
              <Text kind="title/md">Integrity exceptions</Text>
              <Tag color="red" kind="solid" readOnly density="compact">
                {`${exceptions.length.toLocaleString()} node${exceptions.length === 1 ? "" : "s"}`}
              </Tag>
            </Flex>
            <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
              Nodes holding a wrong-sized file, or content that has never been hashed. These can
              read as complete on count alone, which is why they are listed rather than left for a
              hover.
            </Text>
            <TableContainer style={{ maxHeight: 280 }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>Node</TableCell>
                    <TableCell align="right">SU</TableCell>
                    <TableCell>Finding</TableCell>
                    <TableCell align="right">Verified</TableCell>
                    <TableCell align="right">Wrong size</TableCell>
                    <TableCell align="right">Unhashed</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {exceptions.slice(0, 200).map((node) => (
                    <TableRow key={node.node} hover>
                      <TableCell>
                        <Text kind="mono/sm">{node.node}</Text>
                      </TableCell>
                      <TableCell align="right">{node.su}</TableCell>
                      <TableCell>
                        <Tag
                          color={integrityToneOf(node) === "corrupt" ? "red" : "yellow"}
                          kind="solid"
                          readOnly
                          density="compact"
                        >
                          {integrityToneOf(node) === "corrupt" ? "wrong size" : "unhashed"}
                        </Tag>
                      </TableCell>
                      <TableCell align="right">
                        {node.verified}/{requiredCount}
                      </TableCell>
                      <TableCell align="right">{node.bad_size}</TableCell>
                      <TableCell align="right">{node.unverified}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
            {exceptions.length > 200 ? (
              <Text kind="body/regular/sm" style={{ color: "var(--text-color-subtle)" }}>
                {`Showing the first 200 of ${exceptions.length.toLocaleString()}.`}
              </Text>
            ) : null}
          </Flex>
        </Card>
      ) : null}

      <Card>
        <Flex direction="column" gap="2">
          <Text kind="title/md">Recent operations</Text>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Started</TableCell>
                  <TableCell>Action</TableCell>
                  <TableCell>Campaign</TableCell>
                  <TableCell>Target</TableCell>
                  <TableCell>State</TableCell>
                  <TableCell>Log</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {operations.map((operation) => (
                  <TableRow key={operation.id} hover>
                    <TableCell>
                      <Text kind="mono/sm">{operation.started_at}</Text>
                    </TableCell>
                    <TableCell>{operation.action}</TableCell>
                    <TableCell>{operation.campaign || "—"}</TableCell>
                    <TableCell>
                      {`${operation.roster || "whole fleet"}${operation.images.length ? ` · ${operation.images.join(", ")}` : ""}`}
                    </TableCell>
                    <TableCell>
                      <Tag
                        color={
                          operation.state === "succeeded"
                            ? "green"
                            : operation.state === "failed"
                              ? "red"
                              : "blue"
                        }
                        kind="solid"
                        readOnly
                        density="compact"
                      >
                        {operation.state}
                      </Tag>
                    </TableCell>
                    <TableCell>
                      <Button
                        kind="secondary"
                        color="neutral"
                        size="tiny"
                        onClick={() => setLogOp(operation)}
                      >
                        Open log
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Flex>
      </Card>

      <NewCampaignWizard
        key={wizardKey}
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        images={images}
        nodes={nodes}
        rosters={rosters}
        campaigns={campaigns}
        initialImage={wizardImage}
        rolloutDefaults={rolloutDefaults}
        launchBlocked={blocked}
        onDone={({ campaign, operation, campaigns: saved }) => {
          setCampaigns(saved);
          setActionError(null);
          setNotice(
            operation
              ? `Campaign ${campaign.name} saved and launched. Operation ${operation.id}.`
              : `Campaign ${campaign.name} saved. Launch it from the Campaigns table.`,
          );
          if (operation) void refresh();
        }}
      />

      <Modal
        open={confirmLaunch !== null}
        onOpenChange={(o) => { if (!o && !launching) setConfirmLaunch(null); }}
        modal
        style={{ width: "480px", maxWidth: "90vw" }}
        slotHeading={confirmLaunch ? `Launch ${confirmLaunch.name}?` : "Launch campaign"}
        slotFooter={
          <>
            <ModalCloseButton kind="secondary" disabled={launching}>Cancel</ModalCloseButton>
            <Button kind="primary" color="brand" disabled={launching || Boolean(blocked)} onClick={() => void onLaunch()}>
              {launching ? "Launching…" : "Launch"}
            </Button>
          </>
        }
      >
        {confirmLaunch ? (
          <Text kind="body/regular/md">
            {`Distributes ${confirmLaunch.image} to ${confirmLaunch.roster || "the whole fleet"} (${confirmRosterSize.toLocaleString()} nodes). It runs as one fleet operation; launching and maintenance stay locked until it finishes.`}
          </Text>
        ) : null}
      </Modal>

      <OperationLogDialog open={logOp !== null} onClose={() => setLogOp(null)} operation={logOp} />
    </Flex>
  );
}
