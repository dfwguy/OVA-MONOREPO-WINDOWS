# IREN_MKZ Parquet data lake — quickstart

Full design: `../design/datalake_parquet.md`. This lane runs **in parallel with**
VictoriaMetrics; it is fed by fanning the existing remote_write/Loki-push streams
to `nvis-lakewriter` and adds **zero** scrape load to the fleet.

## Components
| file | role |
|---|---|
| `lakewriter.py` | receives remote_write (`:9410/api/v1/write`), Loki push (`:9410/loki/api/v1/push`) + OTLP logs (`:9410/v1/logs`) → Parquet landing; WAL spool + self-metrics `:9410/metrics` |
| `lake_fabric_poller.py` | pulls ufm-telemetry CSV (`<ufm>:9001`) → `fabric_phy` Parquet (keeps PHY out of TSDB) |
| `lake_compact.py` | hourly landing→curated compaction + daily rollup/retention |
| `lake_common.py` | shared Arrow buffer/flush + node→su/rack identity mapping |
| `schema.py` | single source of truth for all 7 table schemas + partition keys + sort keys |
| `pb_minimal.py` | dependency-free protobuf wire decoders (remote_write + Loki push) — makes the binary feeds work with **no protoc/build step** |
| `compose.datalake.yml` | `nvis-lakewriter` + `nvis-lake-fabric` (restart=always, cpu-capped) |
| `wiring/` | fan-out snippets: Prometheus `remote_write`, on-node Alloy, otel collector |
| `systemd/` | boot bring-up + compaction timers (reboot survival) |

## Partitioned schema (cluster/su/rack/date/hour)
All tables land Hive-partitioned on the path as
`landing/<table>/cluster=IREN_MKZ/su=SU5/rack=h01r03/date=2026-07-23/hour=14/part-<ulid>.parquet`.
`node` (metrics/logs) and `switch` (fabric) are folded into a **sorted column** —
row-group min/max stats give `WHERE node=…` pushdown without a per-node directory
explosion at 8K→100k scale. Tables: `metrics, logs, fabric_phy, switch_events,
validation_runs, writer_meta` — full column list in `schema.py` / design §2.

## Storage prep (coordinate exact devices with the platform/VM agent)
```
# lake pool (3x7TB striped) and fast spool (894GB)
pvcreate /dev/nvme0n1 /dev/nvme1n1 /dev/nvme2n1
vgcreate vg_lake /dev/nvme0n1 /dev/nvme1n1 /dev/nvme2n1
lvcreate -i3 -I256 -l 100%FREE -n lv_lake vg_lake
mkfs.xfs /dev/vg_lake/lv_lake && mkdir -p /data/lake && mount -o noatime /dev/vg_lake/lv_lake /data/lake
mkfs.xfs /dev/nvme6n1 && mkdir -p /data/spool && mount -o noatime /dev/nvme6n1 /data/spool
# add both to /etc/fstab for reboot survival
install -d -o nvis -g nvis /data/lake /data/spool /data/lake/_identity
```

## Bring-up
```
cd /opt/observability/iren_mkz/datalake
docker compose -f compose.datalake.yml up -d          # or: systemctl enable --now nvis-datalake
cp systemd/*.service systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now nvis-lake-compact-hourly.timer nvis-lake-compact-daily.timer
curl -s localhost:9410/metrics | head              # self-observability
```

## Wire the fan-out (no extra scrape)
Ready-to-paste snippets live in `wiring/` — the lake is always a **second,
independent sink** added alongside the existing VM/Loki ones, never in their path:
- `wiring/prometheus.remote_write.snippet.yml` — second `remote_write` per shard (metrics).
- `wiring/alloy.lake.river` — on-node Alloy `loki.write` (logs) + optional OTLP export.
- `wiring/otelcol.lake-export.yaml` — fan-out from the running `nvis-otel-collector` → `/v1/logs`.

Minimal form:
```yaml
# prometheus.yml (per shard) — keep the VM entry, add:
  - url: http://127.0.0.1:9410/api/v1/write
    name: datalake
    queue_config: { capacity: 20000, max_shards: 50, max_samples_per_send: 5000 }
```
```river
# on-node Alloy — second sink alongside the Loki one:
loki.write "lake" { endpoint { url = "http://192.0.2.4:9410/loki/api/v1/push" } }
```
Drop the ib-identity `alias.json` at `/data/lake/_identity/alias.json` for exact
su/rack partitioning (falls back to hostname parsing if absent).

## Query (DuckDB)
```sql
SELECT node, avg(value) FROM read_parquet(
  '/data/lake/curated/metrics/**/*.parquet', hive_partitioning=1)
WHERE su='SU5' AND metric='DCGM_FI_DEV_GPU_TEMP' AND ts > now()-INTERVAL 7 DAY
GROUP BY node ORDER BY 2 DESC;
```

## Notes / dependencies
- **Binary paths work out of the box.** `pb_minimal.py` decodes the Prometheus
  `WriteRequest` and Loki `PushRequest` wire formats with the stdlib only — no
  `protoc`, no generated stubs, no image build step. If you later generate
  `prometheus_pb2` / `logproto_pb2` (faster C++ parse) the writer prefers them
  automatically and falls back to `pb_minimal` otherwise.
- OTLP logs (`/v1/logs`) accept **JSON** encoding (gzip ok); point otel/Alloy
  `otelcol.exporter.otlphttp` at it with `encoding = "json"`.
- Crash safety: every request body is fsync'd to a `raw_spool/` WAL segment
  before decode and deleted after the rows are buffered; leftover segments are
  replayed on writer startup, so the spool never grows without bound.
- `UFM_HOST` is unset until UFM URL/creds are provided (BLOCKING for IB PHY feed).
  Note the staged input: UFM primary `192.0.2.1` (telemetry CSV `:9001`).
- Lake is intentionally **not** RAID-protected and **not** on any dashboard
  alerting path; VM remains the 12-month system of record.
