# 16K core observability deployment

This is the sanitized 16K deployment layer derived from the 8K handoff.

- Host ports: Grafana 3001, Prometheus 9090, existing VictoriaMetrics 8428,
  Loki 3100, Alloy UI 12345, metrics ingest 9099, log ingest 9098.
- VictoriaMetrics is the pre-existing `nvis-victoria-metrics` service. This
  compose file does not own, replace, restart, or reconfigure it.
- Prometheus keeps the five local core endpoints as its core scrape set. Alloy
  accepts push traffic but has no pull discovery or fleet collectors.
- One explicit live-node canary is enabled for `example50-dh01-a01-15`: its
  pre-existing node_exporter (`9100`), DCGM exporter (`9400`), and cgroup
  exporter (`9306`) are scraped read-only. No agent was installed or changed.
  Targets use its currently resolved management IP `192.0.2.5`, while the
  stable `node` and `instance` labels retain the hostname.
  The target labels come from `IREN_MKZ-16K-Inventory/generated/nodes.csv`
  generated at `2026-08-22T07:18:31Z`: logical rack `example50-dh01-a01`, physical
  rack `WH1A1`, slot `15`, partition `defq`, state `idle`, 144 CPUs,
  1,902,269 MiB memory, and four B300 GPUs. The inventory state is stored as
  `inventory_state` to make clear that it is generation-time metadata.
- The canary node has no Alloy endpoint on `12345`, so Prometheus does not
  target one. This canary must not be expanded into fleet discovery without an
  explicit rollout decision.
- No 8K scrape inventories, recovery node lists, secrets, databases, or raw
  runtime data are included.
- Loki is pinned to 3.5.12 instead of the handoff's 3.1.0. The older image has
  a known single-binary owned-stream ring bug that emits an error every 30s.
- System configuration is under `/opt/observability/iren_mkz`; persistent new
  state is under `/cluster/observability/iren_mkz`.

## Single-node canary validation — 2026-08-22

The hostname resolved on the host but not through Docker's embedded DNS, so the
three scrape addresses use the independently verified management IP
`192.0.2.5`. The semantic `node` and `instance` labels remain
`example50-dh01-a01-15`.

The post-fix observation ran from `07:34:49` through an independent final check
at `07:50:51 UTC` (16 minutes 2 seconds):

- `node-exporter`, `dcgm-exporter`, and `cgroup-exporter` stayed `UP` at every
  checkpoint in both Prometheus and the external VictoriaMetrics.
- A 15-minute range query returned 30 samples for `node_uname_info`, 30 samples
  for each of four `DCGM_FI_DEV_GPU_UTIL` GPU series, and 30 samples for
  `cgroup_exporter_build_info` in each store.
- `min_over_time(up[15m])` was `1` for all three jobs in both stores.
- The canary produced 8,148 samples per scrape cycle and the 15-minute increase
  in `prometheus_remote_storage_samples_failed_total` was `0`.
- The final VictoriaMetrics inventory contained 7,992 node-exporter series,
  121 DCGM series, and 50 cgroup-exporter series (8,163 total); GPU temperature
  cardinality was exactly four, matching the four B300 GPUs.
- Final target errors were empty, Prometheus had zero container restarts, and
  the node remained live Slurm state `idle` with four B300 GPUs.
- Prometheus, Loki, Grafana, and Alloy logged zero error-level lines during the
  observation window.

No agent, service, or configuration was changed on the canary node. No Alloy,
fleet, fabric, UFM, or additional node targets were enabled.
