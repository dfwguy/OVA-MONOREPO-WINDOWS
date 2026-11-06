# Architecture and evidence model

Return to [README](../README.md). View the [standalone architecture diagram](../assets/architecture.svg). The diagram is a vector asset and renders without an online diagram service.

The framework separates scheduler execution from evidence collection. Slurm runs workloads; the collector reads evidence asynchronously with explicit CPU, memory, IO and remote-host budgets. Queries run in a separate browser process over published Parquet generations. Hub delivery is an export operation, never a dependency of job launch or collection.

## Components and data flow

| Component | Input → output | Responsibility |
| --- | --- | --- |
| Native `jobcomp/filetxt` or existing accounting | Every terminal scheduler job → retained terminal feed | Preserve outcomes of short jobs and replay after downtime |
| `metadata.py` | `scontrol` → scheduler metadata, allocation manifests and batch scripts | Capture retained live details; one discovery phase every pass |
| `accounting.py` | Optional `sacct --json` → raw job/step records and cursor | Overlapping, checkpointed accounting windows across restarts |
| Runner hook | Actual submitted job ID and exact run path → trusted manifest | Associate logs, scripts, config and validation evidence without time guesses |
| `live.py` / `backfill_remote.py` | Approved node paths → immutable snapshots and host inventories | Bounded SSH reads, fair host queue, visible deferrals |
| `history.py` | Local roots, manifests, controller/completion logs → SQLite and raw payloads | Recover source versions, normalize selected metrics, publish/export |
| `search_index.py` | Captured immutable payloads → disposable FTS cache | Resume incomplete indexing without changing raw evidence |
| Browser | Pinned Parquet generation → SQL, text search and downloads | Token/session authentication, loopback binding, bounded read-only SQL |
| Systemd | Fixed units and timers → restarted services and boot activation | Resource caps, mount ordering, watchdog and service timeouts |
| Hub importer | Verified portable export → tenant-scoped reference records | Separate integration with its own authorization and schema policy |

## Persistence and commit boundaries

`state/index.sqlite` uses SQLite WAL. Payload bytes are stored by SHA-256 beneath `raw/`; hashes distinguish original from stored/redacted bytes. Raw writes use unique temporary files, `fsync`, atomic rename and directory sync before committing references. Interrupted capture may leave an unreferenced payload that can be reconciled later; it must not create a committed reference to an unflushed raw write.

Parquet metadata tables are published into a new `lake/generation-*` directory. Payload Parquet is immutable and content-addressed. Files and generation directories are flushed before `lake/current` is atomically switched. Exports and publication use a common advisory lock. No automatic generation pruning removes a snapshot while a browser/export may still reference it. Persistent filesystem semantics and storage redundancy remain platform responsibilities; software flushes cannot repair physical storage loss.

SQLite is operational state, not the hub export format. An export contains metadata tables, generation provenance and binary Parquet payload chunks. A consumer can reconstruct stored bytes and verify SHA-256 without the collector, SSH or its SQLite checkpoint.

## Identity and schema

Every hub record is namespaced by `(tenant/site, cluster, cluster_epoch, job_id)`. Start a new epoch/root after a job-ID reset or cluster rebuild. A filename on two nodes has two `ssh://host/path` source identities. Artifact versions identify source plus original SHA-256; payloads deduplicate by stored SHA-256. Clock strings remain source-native unless timezone provenance is verified.

| Published table | Meaning |
| --- | --- |
| `jobs` | Scheduler metadata, coverage, model/dtype fields where known, separate completion/validation/qualification states |
| `artifacts` | Source/version, job association, original and stored hashes, sizes and redaction flags |
| `metrics` | Preferred normalized measurements with source artifact and explicit units |
| `metric_observations` | Current parser observations before preferred-source selection |
| `validations` | Captured validation summaries; a scheduler `COMPLETED` state does not imply a validation pass |
| `remote_coverage` | Inventory/capture count, last attempt, partial/error state per job and host |
| `errors` | Source capture failures and resolution timestamps |
| `gaps` | Numeric IDs lacking recovered evidence; requires independent scheduler interpretation |
| `payloads/*.parquet` | Stored bytes in ordered chunks keyed by SHA-256 |

Model/dtype inference from names is a convenience field, not authoritative hardware/workload inventory. Parsed metrics retain units and raw source references; future comparisons must select compatible workload, software, scale and parser provenance.

## Trust and access

Only the service identity needs read access to approved source roots. Runner-manifest directories are trusted write interfaces and must be limited to authorized validation runners. Manifests never grant broader filesystem permissions. Local symlink resolution and remote allowlists constrain reads. Secret-looking filenames are excluded; pattern redaction provides an extra layer but does not prove arbitrary logs are secret-free.

The browser binds loopback and supports a token login for an SSH-tunnel user. For teams, a TLS SSO gateway authenticates end users and replaces incoming evidence-token headers. The token is not a multi-tenant ACL system. Separate collector/browser deployments and OS ACLs isolate clusters; no shared public raw-data endpoint is created.

## Availability boundary

Timers resume after boot, oneshots restart on failure and the browser restarts after process loss. Fair queue state, accounting cursors and source snapshots survive process restart on persistent storage. Controller outages, node reboot, storage exhaustion or denied permissions remain observable collection gaps until retained sources can be replayed. True zero downtime needs redundant retained sources and a fenced failover writer; distributed HA is outside this baseline.

The Slurm [configuration reference](https://slurm.schedmd.com/slurm.conf.html) defines completion and accounting integrations. [PyArrow Parquet](https://arrow.apache.org/docs/python/parquet.html) supplies the serialization layer. The separate [DuckDB UI extension](https://duckdb.org/docs/current/core_extensions/ui) is optional upstream software and is not used by this bundle.
