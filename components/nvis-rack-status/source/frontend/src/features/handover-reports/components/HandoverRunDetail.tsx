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
import { useState, type ReactNode } from "react";
import { Button, Card, CodeSnippet, Flex, Table, Text } from "@nvidia/foundations-react-core";
import { RefreshCw } from "lucide-react";
import { usePagedRows } from "../../../hooks/usePagedRows";
import { TablePager } from "../../../components/TablePager";
import {
  BRINGUP_HEADS,
  COLLECTIVES,
  COLLECTIVE_LABEL,
  PRODUCT,
  commandBlock,
  formatGbps,
  formatPct,
  formatSize,
  formatSuRacks,
  formatWhen,
  modelLabel,
  shortNodelist,
} from "../lib/handoverModel";
import type { HandoverRunDetail as Detail, NodeRow } from "../types";
import { LlmStepsChart, NcclBandCharts } from "./HandoverCharts";
import { HandoverFloorPlan } from "./HandoverFloorPlan";

const muted = { color: "var(--text-color-secondary)" } as const;

function Section({ title, children, note }: { title: string; children: ReactNode; note?: string }) {
  return (
    <section style={{ marginTop: 28 }}>
      <Text kind="title/sm" style={{ display: "block", marginBottom: 8 }}>{title}</Text>
      {children}
      {note ? <Text kind="body/regular/sm" style={{ ...muted, display: "block", marginTop: 6 }}>{note}</Text> : null}
    </section>
  );
}

function KeyValues({ label, rows, mono = false }: { label: string; rows: [string, ReactNode][]; mono?: boolean }) {
  return (
    <Table
      aria-label={label}
      layout="auto"
      density="compact"
      columns={["Setting", "Value"]}
      rows={rows.map(([k, v]) => ({
        id: k,
        cells: [k, { children: mono ? <Text kind="mono/sm" style={{ wordBreak: "break-all" }}>{v}</Text> : v }],
      }))}
    />
  );
}

interface Tile {
  key: string;
  label: string;
  value: string;
  caption: string;
}

function Tiles({ tiles }: { tiles: Tile[] }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 12 }}>
      {tiles.map((t) => (
        <Card key={t.key} style={{ borderLeft: "4px solid var(--border-color-base)" }}>
          <Flex direction="col" gap="1">
            <Text kind="label/regular/sm" style={{ ...muted, textTransform: "uppercase", letterSpacing: "0.06em" }}>
              {t.label}
            </Text>
            <Text kind="display/sm" data-testid={`handover-kpi-${t.key}`}>{t.value}</Text>
            <Text kind="body/regular/sm" style={muted}>{t.caption}</Text>
          </Flex>
        </Card>
      ))}
    </div>
  );
}

const NODE_FACTS_NOTE: Record<Detail["node_facts"]["state"], string> = {
  ready: "",
  collecting: "Reading each node's bring-up results; the table fills in when that finishes.",
  not_collected: "Bring-up results are read once the run finishes.",
  none: "",
};

/** A bring-up cell: the bandwidth when the job measured one, else its status word. */
function bringupCell(value: string | undefined) {
  if (!value) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(1) : value;
}

/** Every node the run held, with its address and its own bring-up NCCL figures. */
function NodesTable({ run, onRecollect }: { run: Detail; onRecollect?: () => Promise<void> }) {
  const paged = usePagedRows<NodeRow>(run.node_rows, 25);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const recollect = async () => {
    if (!onRecollect) return;
    setBusy(true);
    setError("");
    try {
      await onRecollect();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const facts = run.node_facts;
  const jobs = Object.keys(BRINGUP_HEADS);
  const when = facts.collected_at ? ` Collected ${formatWhen(facts.collected_at)}.` : "";
  const notes = [
    NODE_FACTS_NOTE[facts.state],
    "NCCL columns are each node's own bring-up result (bus bandwidth in GB/s, NVLink and RoCE); bring-up runs no per-node all-gather.",
    facts.bringup_error ? `Bring-up results unavailable: ${facts.bringup_error}` : "",
  ].filter(Boolean);
  return (
    <Section title={`Nodes (${run.node_rows.length})`} note={`${notes.join(" ")}${when}`}>
      {onRecollect && facts.state === "ready" ? (
        <Flex gap="2" align="center" style={{ marginBottom: 8 }}>
          <Button kind="secondary" color="neutral" size="small" onClick={() => void recollect()} disabled={busy}>
            <RefreshCw size={14} aria-hidden /> Collect node facts again
          </Button>
          <Text kind="body/regular/sm" style={muted}>
            {error || "Reads each node's latest bring-up results again, replacing these."}
          </Text>
        </Flex>
      ) : null}
      {run.floor_plan?.length ? (
        <div style={{ marginBottom: 16 }}>
          <HandoverFloorPlan plan={run.floor_plan} />
        </div>
      ) : null}
      <Table
        aria-label="Nodes"
        layout="auto"
        density="compact"
        columns={["Node", "Rack", "IP", "AR (GB/s)", "A2A (GB/s)", "AG", "AR RoCE", "A2A RoCE"]}
        rows={paged.visible.map((n) => ({
          id: n.host,
          cells: [
            { children: <Text kind="mono/sm">{n.host}</Text> },
            n.rack || "—",
            n.ip || "—",
            ...jobs.slice(0, 2).map((j) => bringupCell(n.bringup[j])),
            "—",
            ...jobs.slice(2).map((j) => bringupCell(n.bringup[j])),
          ],
        }))}
      />
      <TablePager {...paged} noun="nodes" />
    </Section>
  );
}

/** One multi-rack run in full: what it measured, the curves, and what it ran with. */
export function HandoverRunDetail({ run, onRecollectNodeFacts }: { run: Detail; onRecollectNodeFacts?: () => Promise<void> }) {
  const a2a = run.collectives.alltoall;
  const ar = run.collectives.all_reduce;
  const llm = run.llm;
  const ceiling = run.alltoall_ceiling;
  // An LLM job's NCCL sweep is its preflight, with the training job's settings: labelled as such.
  const preflight = run.run_type === "both";
  const tiles: Tile[] = [
    { key: "gpus", label: "GPUs", value: String(run.gpus ?? "—"), caption: `${run.nodes ?? "—"} nodes on ${run.racks.length} racks` },
    { key: "a2a", label: preflight ? "Preflight all-to-all @2 GB" : "All-to-all @2 GB", value: formatGbps(a2a?.busbw_2g_gbps), caption: `GB/s · peak ${formatGbps(a2a?.busbw_peak_gbps)}` },
    ...(ceiling
      ? [{ key: "a2a-ceiling", label: "All-to-all of ceiling", value: formatPct(ceiling.pct_2g), caption: `@2 GB · ceiling ${formatGbps(ceiling.ceiling_gbps)} GB/s` }]
      : []),
    { key: "ar", label: preflight ? "Preflight all-reduce @2 GB" : "All-reduce @2 GB", value: formatGbps(ar?.busbw_2g_gbps), caption: `GB/s · peak ${formatGbps(ar?.busbw_peak_gbps)}` },
  ];
  if (llm) {
    tiles.push(
      { key: "tflops", label: "Model TFLOP/s per GPU", value: formatGbps(llm.tflops_per_gpu), caption: modelLabel(run) },
      {
        key: "step",
        label: "Step time",
        value: typeof llm.step_time_s === "number" ? `${llm.step_time_s.toFixed(2)} s` : "—",
        caption: typeof llm.step_time_s === "number" && llm.step_time_s > 0 ? `${(1 / llm.step_time_s).toFixed(3)} steps/s` : "",
      },
    );
  }

  const stated = run.settings.stated;
  const facts: [string, ReactNode][] = (
    [
      ["NCCL version", stated.nccl_version],
      ["Collectives", stated.collectives.join(" ")],
      ["Message sizes", stated.sizes],
      ["Rounds", stated.rounds == null ? "" : String(stated.rounds)],
      ["Model arguments", stated.model_args],
      ["Training arguments", stated.extra_args],
    ] as [string, string][]
  ).filter(([, v]) => Boolean(v));
  const perCollective = Object.entries(stated.per_collective).flatMap(([coll, env]) =>
    Object.entries(env).map(([k, v]) => ({ coll, k, v })),
  );
  const launchEnv = Object.entries(run.settings.launch_env).filter(([k]) => !k.startsWith("NVIS_NCCL_ENV_"));
  const statedEnv = Object.entries(stated.env);
  const nccl = COLLECTIVES.filter((c) => run.collectives[c]);

  return (
    <div>
      <Tiles tiles={tiles} />

      <Section title="Run">
        <KeyValues
          label="Run"
          rows={[
            ["Racks", run.racks.map((r) => (run.rack_su[r] ? `${r} (${run.rack_su[r]})` : r)).join(", ")],
            ["Scheduler jobs", run.scheduler_job_ids.join(", ") || "—"],
            ["Started", formatWhen(run.job_started_at || run.created_at)],
            ["Finished", formatWhen(run.job_ended_at || run.finished_at)],
            ["Tool", run.tool],
            ["Outcome", run.outcome],
            ["Operator", run.operator || "—"],
            ["Activity", run.activity_id],
          ]}
        />
        {run.error_summary ? (
          <Text kind="body/regular/sm" style={{ ...muted, display: "block", marginTop: 6 }}>Issue: {run.error_summary}</Text>
        ) : null}
      </Section>

      {nccl.length ? (
        <Section
          title={preflight ? "NCCL preflight (inside the LLM job)" : "NCCL results"}
          note={
            preflight
              ? "This LLM job swept NCCL before training, inside its container and with the training job's NCCL settings rather than the tuned NCCL test's, so these figures are lower by design. Out-of-place bus bandwidth, 2 GB to 16 GB."
              : "Out-of-place bus bandwidth; each chart draws the best sweep of its collective from 2 GB to 16 GB."
          }
        >
          <Table
            aria-label="NCCL results"
            layout="auto"
            density="compact"
            columns={["Collective", "Bus bandwidth @2 GB (GB/s)", "Peak bus bandwidth (GB/s)", "Largest message"]}
            rows={nccl.map((c) => {
              const v = run.collectives[c]!;
              return {
                id: c,
                cells: [COLLECTIVE_LABEL[c], formatGbps(v.busbw_2g_gbps), formatGbps(v.busbw_peak_gbps), formatSize(v.max_size_bytes)],
              };
            })}
          />
          <div style={{ marginTop: 16 }}>
            <NcclBandCharts curves={run.nccl_curves} />
          </div>
        </Section>
      ) : null}

      {ceiling ? (
        <Section
          title="All-to-all against its ceiling"
          note={
            "In all-to-all every GPU sends an equal share of its buffer to every other GPU. The share for its own rack travels over NVLink; " +
            "the rest leaves through the GPU's network interface and sets the pace. With N GPUs, R per rack and B the bus bandwidth one GPU " +
            "drives through its interface, ceiling = B × (N − 1) / (N − R). B is the median of the nodes' own bring-up all-to-all with NVLink " +
            "off. The ceiling falls as a run grows, since more of every GPU's traffic leaves its rack. Racks in one scalable unit share its " +
            "leaf switches, so how a run is spread across units can change the share of the ceiling it reaches."
          }
        >
          <KeyValues
            label="All-to-all against its ceiling"
            rows={[
              ["Ceiling", `${formatGbps(ceiling.ceiling_gbps)} GB/s = ${formatGbps(ceiling.nic_gbps)} × (${run.gpus} − 1) / (${run.gpus} − ${ceiling.gpus_per_rack})`],
              ["Achieved @2 GB", `${formatGbps(ceiling.busbw_2g_gbps)} GB/s, ${formatPct(ceiling.pct_2g)} of ceiling`],
              ["Achieved at peak", `${formatGbps(ceiling.busbw_peak_gbps)} GB/s, ${formatPct(ceiling.pct_peak)} of ceiling`],
              ["NIC rate (B)", `${formatGbps(ceiling.nic_gbps)} GB/s, median of ${ceiling.nic_nodes} nodes; slowest ${formatGbps(ceiling.nic_min_gbps)} (${ceiling.nic_min_host})`],
              ["Racks by SU", formatSuRacks(ceiling.su_racks)],
            ]}
          />
        </Section>
      ) : null}

      {run.node_rows.length ? <NodesTable run={run} onRecollect={onRecollectNodeFacts} /> : null}

      {llm ? (
        <Section title="LLM training" note="Means over the measured window; the chart includes the warm-up steps.">
          <KeyValues
            label="LLM training"
            rows={[
              ["Model", modelLabel(run)],
              ["Precision", llm.dtype || "—"],
              ["Global batch", String(llm.global_batch ?? "—")],
              ["Steps", `${llm.steps ?? "—"} of ${llm.declared_steps ?? "—"}${llm.finished ? " (finished)" : ""}`],
              ["Model TFLOP/s per GPU", formatGbps(llm.tflops_per_gpu)],
              ["MFU", typeof llm.mfu_percent === "number" ? `${llm.mfu_percent.toFixed(1)}%` : "—"],
            ]}
          />
          <div style={{ marginTop: 16 }}>
            <LlmStepsChart steps={run.llm_steps} />
          </div>
        </Section>
      ) : null}

      {facts.length ? (
        <Section title="Configuration">
          <KeyValues label="Configuration" rows={facts} mono />
        </Section>
      ) : null}

      {perCollective.length ? (
        <Section title="Per-collective NCCL settings">
          <Table
            aria-label="Per-collective NCCL settings"
            layout="auto"
            density="compact"
            columns={["Collective", "Variable", "Value"]}
            rows={perCollective.map(({ coll, k, v }) => ({
              id: `${coll}-${k}`,
              cells: [COLLECTIVE_LABEL[coll as keyof typeof COLLECTIVE_LABEL] ?? coll, { children: <Text kind="mono/sm">{k}</Text> }, { children: <Text kind="mono/sm">{v}</Text> }],
            }))}
          />
        </Section>
      ) : null}

      <Section
        title="Environment (as launched)"
        note={launchEnv.length ? "What the launch handed its job, secrets withheld." : `This run was launched before ${PRODUCT} kept the launch environment; the job's own statement of it is below.`}
      >
        {launchEnv.length ? <KeyValues label="Environment as launched" rows={launchEnv} mono /> : null}
      </Section>

      {statedEnv.length ? (
        <Section title="Environment (as stated by the job)" note="Variables the launchers printed in the job log, for every rank.">
          <KeyValues label="Environment as stated" rows={statedEnv} mono />
        </Section>
      ) : null}

      {run.nccl_commands.length ? (
        <Section
          title="NCCL test commands"
          note={
            "Run from one node with nccl-tests and HPC-X on every node. The hosts file lists each node of the table above as one " +
            "`<node> slots=<GPUs per node>` line. " +
            (run.nccl_commands.some((c) => c.source === "reconstructed")
              ? "This run predates jobs printing their exact command, so it is rebuilt from the job's settings; <not recorded> marks values its log did not keep."
              : "Each command is exactly as the job printed it.")
          }
        >
          <Flex direction="col" gap="3">
            {run.nccl_commands.map((c) => (
              <CodeSnippet key={c.collective} language="bash" value={commandBlock(c)} />
            ))}
          </Flex>
        </Section>
      ) : null}

      {run.command.launcher || run.command.submitted.length ? (
        <Section title={`Launched through ${PRODUCT}`}>
          <CodeSnippet
            language="bash"
            value={[shortNodelist(run.command.launcher), ...run.command.submitted.map((s) => `# submitted: ${s}`)].filter(Boolean).join("\n")}
          />
        </Section>
      ) : null}
    </div>
  );
}
