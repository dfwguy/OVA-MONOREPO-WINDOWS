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
// New campaign: the one way to start a distribution from the Artifact Distribution page.
// Author: Rafael M. Koike
//
// A campaign is task + roster + plan, so the wizard is those three steps and a review. Each step
// shows what the fleet already holds of the chosen image, because "how many nodes will this touch"
// is the question an operator has before launching, and the snapshot already answers it. Saving
// writes the campaign next to the existing ones (the same document the Campaigns editor edits);
// "Save and launch" also enqueues it, through the same launchCampaign the editor uses.
import { useMemo, useState } from "react";
import {
  Banner,
  Button,
  Flex,
  FormField,
  Modal,
  ModalCloseButton,
  SegmentedControl,
  Select,
  Stepper,
  Text,
  TextInput,
} from "@nvidia/foundations-react-core";
import { StageLadderInput } from "../StageLadderInput";
import { WavePlanDiagram } from "./WavePlanDiagram";
import {
  PACING_FIELDS,
  STRATEGY_ITEMS,
  campaignNameProblem,
  emptyCampaign,
  holders,
  pacingOverrides,
  strategyLabel,
} from "../../lib/campaigns";
import { launchCampaign, saveCampaigns } from "../../services/fleetService";
import type { CampaignEdit, RolloutStrategy, RosterEdit } from "../../services/fleetService";
import type { CatalogImage, NodeCoverage, Operation } from "../../types/fleet";

/** The Select value for "no named roster": the cluster's default inventory, i.e. the whole fleet. */
const WHOLE_FLEET = "__whole_fleet__";

const STEPS = [
  { slotHeading: "Task", slotDescription: "The catalog image to distribute" },
  { slotHeading: "Roster", slotDescription: "The nodes that receive it" },
  { slotHeading: "Plan", slotDescription: "How the waves are paced" },
  { slotHeading: "Review", slotDescription: "Name, save, launch" },
];

export type NewCampaignWizardProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  images: CatalogImage[];
  /** The fleet snapshot's nodes: what each already holds. */
  nodes: NodeCoverage[];
  rosters: RosterEdit[];
  /** The saved campaigns; the new one is appended to them. */
  campaigns: CampaignEdit[];
  /** Pre-select this image (a catalog row's "Distribute" action). Read once: remount to change it. */
  initialImage?: string;
  /** The cluster's own wave plan, which a campaign that names none inherits (Dragonfly Settings). */
  rolloutDefaults?: { strategy: RolloutStrategy; stages: string[]; waveSize: number } | null;
  /** Why launching is not possible right now (an operation running, no instance); saving still is. */
  launchBlocked?: string | null;
  onDone: (result: { campaign: CampaignEdit; operation: Operation | null; campaigns: CampaignEdit[] }) => void;
};

function gigabytes(bytes: number): string {
  return `${(bytes / 1e9).toFixed(2)} GB`;
}

export function NewCampaignWizard({
  open, onOpenChange, images, nodes, rosters, campaigns, initialImage, rolloutDefaults, launchBlocked, onDone,
}: NewCampaignWizardProps) {
  // Every opening is a fresh campaign: the caller remounts the wizard (a new `key`) per opening, so
  // state starts here, seeded with the image the caller pointed at.
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<CampaignEdit>(() => ({ ...emptyCampaign(), image: initialImage ?? "" }));
  const [showPacing, setShowPacing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (patch: Partial<CampaignEdit>) => setDraft((d) => ({ ...d, ...patch }));
  const image = images.find((i) => i.filename === draft.image) ?? null;
  const roster = rosters.find((r) => r.name === draft.roster) ?? null;

  // The roster's nodes as the snapshot sees them; the whole fleet when no roster is named.
  const targetNodes = useMemo(() => {
    if (!roster) return nodes;
    const wanted = new Set(roster.nodes);
    return nodes.filter((n) => wanted.has(n.node));
  }, [nodes, roster]);
  const targetCount = roster ? roster.nodes.length : nodes.length;
  const alreadyHold = draft.image ? holders(targetNodes, draft.image) : 0;

  // The plan this campaign will actually run: its own choice, else the cluster's. Drawn on the Plan step.
  const planStrategy: RolloutStrategy = draft.strategy || rolloutDefaults?.strategy || "sequential";
  const planStages = draft.stages.length ? draft.stages : rolloutDefaults?.stages ?? [];
  const waveSize = draft.wave_size || rolloutDefaults?.waveSize || 0;
  const planCaption = `${draft.strategy ? "" : `Cluster default: ${strategyLabel(planStrategy).toLowerCase()}. `}${
    planStrategy === "rack-staged"
      ? "Only stage 1 pulls from the app server's seeds, one node per rack; every later stage grows each rack from its own rack-mates."
      : `Waves take the roster in order${waveSize ? `, ${waveSize} nodes each` : ""}, and every wave pulls from the app server's seeds, so the seeds carry the whole rollout.`
  }`;

  const nameProblem = campaignNameProblem(draft.name, campaigns.map((c) => c.name));
  const stepProblem = [
    draft.image ? null : "Choose the image to distribute.",
    null,
    null,
    nameProblem,
  ][step];

  async function finish(launch: boolean) {
    setBusy(true);
    setError(null);
    const campaign = { ...draft, name: draft.name.trim(), description: draft.description.trim() };
    try {
      const saved = await saveCampaigns([...campaigns, campaign]);
      const operation = launch ? await launchCampaign(campaign) : null;
      onDone({ campaign, operation, campaigns: saved.campaigns });
      onOpenChange(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The campaign could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  const imageItems = images.map((i) => ({ value: i.filename, children: `${i.name || i.filename} — ${i.filename}` }));
  const rosterItems = [
    { value: WHOLE_FLEET, children: `Whole fleet (default inventory) · ${nodes.length.toLocaleString()} nodes` },
    ...rosters.map((r) => ({ value: r.name, children: `${r.name} · ${r.nodes.length.toLocaleString()} nodes` })),
  ];
  const rosterLabel = roster ? roster.name : "Whole fleet";

  const body = [
    // 0. Task
    <Flex key="task" direction="column" gap="3">
      <FormField slotLabel="Image" slotHelp="One catalog image. The catalog is edited on the Catalog page.">
        <Select aria-label="Image" items={imageItems} value={draft.image} onValueChange={(v: string) => update({ image: v })} />
      </FormField>
      {image ? (
        <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
          {`${gigabytes(image.bytes)} · ${image.canonical_present ? "on the origin" : "NOT on the origin: nothing can serve it yet"} · ${holders(nodes, image.filename).toLocaleString()} of ${nodes.length.toLocaleString()} nodes already hold it`}
        </Text>
      ) : null}
    </Flex>,
    // 1. Roster
    <Flex key="roster" direction="column" gap="3">
      <FormField slotLabel="Roster" slotHelp="A named roster, or the whole fleet. Rosters are edited on the Rosters page.">
        <Select
          aria-label="Roster"
          items={rosterItems}
          value={draft.roster || WHOLE_FLEET}
          onValueChange={(v: string) => update({ roster: v === WHOLE_FLEET ? "" : v })}
        />
      </FormField>
      <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
        {`${targetCount.toLocaleString()} nodes · ${alreadyHold.toLocaleString()} already hold ${draft.image || "the image"} · ${Math.max(0, targetCount - alreadyHold).toLocaleString()} will receive it`}
      </Text>
    </Flex>,
    // 2. Plan
    <Flex key="plan" direction="column" gap="3">
      <FormField
        slotLabel="Wave plan"
        slotHelp="How the image spreads. The drawing shows the plan this campaign will run."
      >
        <SegmentedControl
          size="small"
          aria-label="Wave plan"
          items={STRATEGY_ITEMS}
          value={draft.strategy || "inherit"}
          onValueChange={(v: string) => update({ strategy: v === "inherit" ? "" : (v as RolloutStrategy) })}
        />
      </FormField>
      <WavePlanDiagram strategy={planStrategy} stages={planStages} caption={planCaption} />
      {draft.strategy === "rack-staged" ? (
        <StageLadderInput
          label="Stages"
          value={draft.stages}
          inherits
          placeholder="cluster default (e.g. 1, 50%, 100%)"
          help="Per-rack targets, a count or a share, ending at 100%. Blank uses the cluster's ladder."
          onChange={(stages) => update({ stages })}
        />
      ) : null}
      <Flex>
        <Button kind="secondary" color="neutral" size="small" onClick={() => setShowPacing((s) => !s)}>
          {showPacing ? "Hide pacing overrides" : "Pacing overrides"}
        </Button>
      </Flex>
      {showPacing ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 180px), 1fr))", gap: 12 }}>
          {[...PACING_FIELDS, { key: "fill_wave_size" as const, label: "Fill wave size", placeholder: "default" }].map((f) => (
            <FormField key={f.key} slotLabel={f.label}>
              <TextInput
                aria-label={f.label}
                type="number"
                min={0}
                placeholder={f.placeholder}
                value={Number(draft[f.key]) > 0 ? String(draft[f.key]) : ""}
                onValueChange={(v: string) => update({ [f.key]: Math.max(0, Number(v) || 0) } as Partial<CampaignEdit>)}
              />
            </FormField>
          ))}
        </div>
      ) : (
        <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>
          Blank fields inherit the cluster&rsquo;s rollout defaults.
        </Text>
      )}
    </Flex>,
    // 3. Review
    <Flex key="review" direction="column" gap="3">
      <FormField slotLabel="Name" required status={draft.name && nameProblem ? "error" : undefined} slotError={draft.name ? nameProblem ?? undefined : undefined}>
        <TextInput aria-label="Name" value={draft.name} onValueChange={(v: string) => update({ name: v })} />
      </FormField>
      <FormField slotLabel="Description">
        <TextInput aria-label="Description" value={draft.description} onValueChange={(v: string) => update({ description: v })} />
      </FormField>
      <Flex direction="column" gap="1" aria-label="Campaign summary">
        <Text kind="body/regular/sm">{`Task: ${image ? `${image.name || image.filename} (${image.filename})` : draft.image}`}</Text>
        <Text kind="body/regular/sm">{`Roster: ${rosterLabel}, ${targetCount.toLocaleString()} nodes, ${Math.max(0, targetCount - alreadyHold).toLocaleString()} to receive it`}</Text>
        <Text kind="body/regular/sm">
          {`Plan: ${strategyLabel(draft.strategy)}${draft.strategy === "rack-staged" && draft.stages.length ? `, stages ${draft.stages.join(" → ")}` : ""}${pacingOverrides(draft).length ? `; ${pacingOverrides(draft).join(", ")}` : "; cluster pacing"}`}
        </Text>
      </Flex>
      {launchBlocked ? (
        <Banner status="info" kind="inline">{`You can save this campaign now and launch it later: it cannot launch while ${launchBlocked}.`}</Banner>
      ) : null}
    </Flex>,
  ][step];

  const last = step === STEPS.length - 1;
  return (
    <Modal
      open={open}
      onOpenChange={(o) => { if (!busy) onOpenChange(o); }}
      modal
      style={{ width: "900px", maxWidth: "94vw" }}
      slotHeading="New campaign"
      slotFooter={
        <>
          <ModalCloseButton kind="secondary" disabled={busy}>Cancel</ModalCloseButton>
          {step > 0 ? (
            <Button kind="secondary" color="neutral" disabled={busy} onClick={() => setStep((s) => s - 1)}>Back</Button>
          ) : null}
          {last ? (
            <>
              <Button kind="secondary" color="neutral" disabled={busy || Boolean(stepProblem)} onClick={() => void finish(false)}>
                Save
              </Button>
              <Button kind="primary" color="brand" disabled={busy || Boolean(stepProblem) || Boolean(launchBlocked)} onClick={() => void finish(true)}>
                Save and launch
              </Button>
            </>
          ) : (
            <Button kind="primary" color="brand" disabled={Boolean(stepProblem)} onClick={() => setStep((s) => s + 1)}>
              Next
            </Button>
          )}
        </>
      }
    >
      <Flex direction="column" gap="4">
        <Stepper activeStep={step} aria-label="New campaign progress" items={STEPS} />
        {body}
        {stepProblem && (step !== 3 || draft.name) ? (
          <Text kind="body/regular/sm" style={{ color: "var(--text-color-secondary)" }}>{stepProblem}</Text>
        ) : null}
        {error ? <Banner status="error" kind="inline">{error}</Banner> : null}
      </Flex>
    </Modal>
  );
}
