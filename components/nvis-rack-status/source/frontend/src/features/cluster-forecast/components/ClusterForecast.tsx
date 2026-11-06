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
import { Banner, Flex, Text } from "@nvidia/foundations-react-core";
import { Section } from "../../deployment-tracker/components/Section";
import type { ClusterForecastReport } from "../types";
import { SCENARIOS, formatCount, formatDay, formatRate, formatUtc, reportYear } from "../lib/forecastModel";
import { HistoryChart, ProjectionChart } from "./ForecastCharts";
import { ForecastKpis } from "./ForecastKpis";
import { ForecastMilestones } from "./ForecastMilestones";
import { ForecastUnits } from "./ForecastUnits";
import { RackBuckets } from "./RackBuckets";

const MUTED = { color: "var(--text-color-secondary)" };

function Takeaway({ report }: { report: ClusterForecastReport }) {
  const s = report.summary;
  const year = reportYear(report);
  const all = report.milestones.find((m) => m.id === "all");
  const half = report.milestones.find((m) => m.id === "units_half");
  const { phrase } = report.shape.finish;
  if (all?.reached) {
    return <Text kind="body/regular/md">Validation is done here: {phrase}.</Text>;
  }
  if (!report.pace.enough_history || !all?.current_pace) {
    return (
      <Text kind="body/regular/md">
        {formatCount(s.nodes_remaining)} of {formatCount(s.nodes)} nodes and {formatCount(s.racks - s.racks_passed)} of{" "}
        {formatCount(s.racks)} racks are still open. {report.pace.reason}
      </Text>
    );
  }
  return (
    <Text kind="body/regular/md" data-testid="forecast-takeaway">
      At the current pace {phrase} by <b>{formatDay(all.current_pace, year)}</b>. If repairs keep slowing as they have,
      {half ? (
        <>
          {" "}half the SUs finish by <b>{formatDay(half.slowing_tail, year)}</b> and the last one around{" "}
        </>
      ) : (
        " the last of it lands around "
      )}
      <b>{formatDay(all.slowing_tail, year)}</b>. Validation capacity is not the limit; node repairs are.
    </Text>
  );
}

/**
 * The forecast body, shared by the in-app view and the published static page. Each shell draws its
 * own header; everything below it is this component, so the two cannot drift apart.
 */
export function ClusterForecast({ report }: { report: ClusterForecastReport }) {
  const { summary: s, pace, meta, shape } = report;
  const onboarding = s.onboarding;
  const groups = (n: number) => (shape.has_units ? `scalable unit${n === 1 ? "" : "s"}` : `group${n === 1 ? "" : "s"}`);
  const check = meta.sampling?.last_check;
  return (
    <Flex direction="col" gap="4">
      {meta.stage2_loading ? (
        <Banner status="info">
          Stage 2 verdicts were still loading when this was generated, so fewer nodes may show as
          passed than have. Refresh in a minute.
        </Banner>
      ) : null}

      <Takeaway report={report} />

      <ForecastKpis report={report} />

      <Section
        title="When it finishes"
        caption={shape.has_racks ? `each rack date adds ${meta.rack_run_days} day for its rack runs` : undefined}
      >
        <ForecastMilestones report={report} />
      </Section>

      <Section title="Nodes still to pass" caption="projected from today under both scenarios">
        <ProjectionChart report={report} />
      </Section>

      <Section
        title={`By ${shape.group_label.toLowerCase()}`}
        caption={shape.has_racks ? "open one to see the racks it is waiting on" : undefined}
      >
        <ForecastUnits report={report} />
      </Section>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 420px), 1fr))", gap: 16 }}>
        <Section title="Nodes passed" caption="since sampling began; imported history dashed">
          <HistoryChart report={report} measure="nodes" />
        </Section>
        {shape.has_racks ? (
          <Section title="Racks passed" caption="rack Stage 2 over the whole rack">
            <HistoryChart report={report} measure="racks" />
          </Section>
        ) : null}
      </div>

      {shape.has_racks ? (
        <Section title="What the open racks are waiting on" caption="a rack runs only when all its nodes have passed and are up">
          <RackBuckets buckets={report.rack_buckets} />
        </Section>
      ) : null}

      {onboarding.units ? (
        <Section title="Not started yet">
          <Text kind="body/regular/md">
            {onboarding.units} {groups(onboarding.units)} ({formatCount(onboarding.nodes)} nodes
            {shape.has_racks ? `, ${formatCount(onboarding.racks)} racks` : ""}) {onboarding.units === 1 ? "is" : "are"} placed in the cluster but no node
            has run a stage yet, so {onboarding.units === 1 ? "it has" : "they have"} no date. Each joins the forecast with its
            first node stage.
          </Text>
        </Section>
      ) : null}

      <Section title="How the forecast works">
        <Flex direction="col" gap="2">
          <Text kind="body/regular/md">
            {pace.enough_history && pace.days ? (
              <>
                From {formatUtc(pace.from ?? "")} to now, the nodes still open went from{" "}
                {formatCount(pace.remaining_from ?? 0)} to {formatCount(pace.remaining_to)}: {formatRate(pace.nodes_per_day)}{" "}
                nodes a day, and a backlog half-life of {formatRate(pace.half_life_days)} days. Racks passed{" "}
                {formatRate(pace.racks_per_day)} a day.
                {pace.baseline_source === "import" ? " The baseline is imported history." : ""}
              </>
            ) : (
              pace.reason
            )}
          </Text>
          <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", columnGap: 16, rowGap: 6, margin: 0 }}>
            {SCENARIOS.map((sc) => (
              <div key={sc.key} style={{ display: "contents" }}>
                <dt>
                  <Text kind="body/bold/sm" style={{ color: sc.text }}>
                    {sc.label}
                  </Text>
                </dt>
                <dd style={{ margin: 0 }}>
                  <Text kind="body/regular/sm">{meta.scenarios[sc.key]}</Text>
                </dd>
              </div>
            ))}
            {Object.entries(meta.definitions).map(([term, text]) => (
              <div key={term} style={{ display: "contents" }}>
                <dt>
                  <Text kind="body/bold/sm">{term.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}</Text>
                </dt>
                <dd style={{ margin: 0 }}>
                  <Text kind="body/regular/sm">{text}</Text>
                </dd>
              </div>
            ))}
          </dl>
          <Text kind="body/regular/sm" style={MUTED}>
            Not modelled: nodes that fail again after passing, and any change in repair capacity. Doubling the repair rate roughly
            halves every remaining interval.
          </Text>
          {meta.stage2_available === false ? (
            <Text kind="body/regular/sm" style={MUTED} data-testid="forecast-no-stage2">
              This cluster names no Stage 2 source (Projects & Clusters › cluster › Bring-up home), so a node passes on
              Stage 1 alone.
            </Text>
          ) : null}
          {check ? (
            <Text kind="body/regular/sm" style={MUTED} data-testid="forecast-last-check">
              Sampler, last check {formatUtc(check.at)}: {check.outcome} Rack Status samples only the active cluster, so a
              cluster that was not active has no samples for that time.
            </Text>
          ) : null}
          <Text kind="body/regular/sm" style={MUTED}>
            Cluster snapshot {formatUtc(meta.snapshot_at)}
            {meta.sampling
              ? meta.sampling.interval_sec
                ? ` · sampled every ${Math.round(meta.sampling.interval_sec / 60)} min, last ${formatUtc(meta.sampling.last_sample_at ?? "")}`
                : " · sampling is off"
              : ""}
          </Text>
        </Flex>
      </Section>
    </Flex>
  );
}
