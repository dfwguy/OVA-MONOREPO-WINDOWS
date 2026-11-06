# IREN_MKZ-16K live portable observability snapshot

This directory is a sanitized, replacement-oriented snapshot of the live
IREN_MKZ-16K observability deployment collected on 2026-09-24. It contains
configuration and source code only. It deliberately contains no metrics,
logs, traces, Parquet/lake data, Grafana database, credentials, API tokens,
private keys, passwords, live Redfish target inventory, or container volumes.

## Authoritative coverage

- Grafana `11.1.4` API export: **106 dashboards**, **3 folders**, **5 data
  sources**, **1 sanitized contact point**, zero alert rules, and zero mute
  timings.
- Folder distribution: NVIS 67, IREN_MKZ 28, IREN 16kAIC-OVA 11.
- A read-only query of the live Grafana SQLite database independently found
  106 dashboards, 3 folders, and 5 data sources. API and database dashboard
  UID sets match exactly at SHA-256
  `441aeb824ed40fa67d2a7f94324177a289307e7379a13656484a618a6697fe84`.
- The live file-provisioning tree contains only 69 of the 106 dashboards.
  Therefore `grafana-live/` (API + database reconciled) is the authoritative
  replacement set; repository/provisioning JSON alone is not complete.
- All five live datasource UID/name/type tuples match the provisioned source
  exactly. Details and hashes are under `inventory/`.

## Included surfaces

- `grafana-live/`: import-ready dashboard JSON preserving dashboard UIDs,
  folder UIDs/hierarchy, sanitized data sources, and safely exportable alert
  metadata. `provisioning/dashboards-live.yaml` is a three-provider greenfield
  provisioning alternative.
- `core/`: active Prometheus, Loki, Alloy, Grafana provisioning, Docker
  Compose, VictoriaMetrics, validation exporter, and systemd configuration.
- `exporters/`: fleet DCGM target discovery, head-node attribution, Slurm job
  collector, UFM bridge, Redfish reachability, validation exporter, and their
  active systemd units/timers.
- `datalake/`: lakewriter/reconciliation/log-collector source, schemas,
  compose files, wiring examples, tests, and service units. No lake contents.
- `node-agents/`: exact read-only capture from representative live idle node
  `example50-dh02-a01-11` for node exporter, DCGM exporter, cgroup exporter,
  drop-ins, and DCGM counters.
- `inventory/`: API/DB/provisioning reconciliation receipts, component image
  versions, source locations, file inventory, and restore proof.

Current core images are Prometheus `2.54.1`, VictoriaMetrics `1.108.1`, Loki
`3.5.12`, Alloy `1.5.1`, and Grafana `11.1.4`.

## Restore

Follow `RESTORE_ORDER.md`. The supported API path is
`restore/import_grafana.py`: it creates or updates folders by UID, creates or
updates data sources by UID, and imports dashboards with `overwrite=true`.
It is therefore safe to rerun. It reads an optional `GRAFANA_API_TOKEN` only
from process environment and never stores it.

The file-provisioning alternative mounts `grafana-live/dashboards/*` at
`/etc/grafana/live-dashboards/*` and installs
`grafana-live/provisioning/dashboards-live.yaml`.

## Intentionally inaccessible or excluded

- Grafana datasource secure values and contact-point destinations are not
  returned in portable form. The one contact point retains its schema but its
  destination is a placeholder. Resolve it from the customer secret provider.
- Grafana users, sessions, authentication configuration, and ACL identities
  are not exported.
- Prometheus declares no `rule_files`; Grafana reports zero alert rules. Loki
  has a local ruler directory configured but no rule directory is mounted by
  the active container, so there were no live Loki rule files to export.
- Redfish credentials do not exist in this deployment; authenticated sensor
  coverage is intentionally not represented as healthy. Only a target schema
  example is included, not the live BMC target list.
- Container storage, runtime target lists, generated `.prom` textfiles,
  SQLite/Parquet data, logs, caches, backups, PIDs, and timestamps are omitted.
- Node-agent configuration is an exact representative-node snapshot, not a
  4,032-node binary/config census. Fleet target discovery remains dynamic.

Verify the snapshot with:

```bash
sha256sum -c MANIFEST.sha256
./tools/verify_overlay.py
./restore/import_grafana.py --dry-run
```
