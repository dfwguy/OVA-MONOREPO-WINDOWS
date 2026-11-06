# Agent handoff: implement Slurm Parquet capture on a customer cluster

Release 2026-10-07. Use [deployment](docs/deployment.md) for the one-command installer and [hooks](docs/hooks.md) for the runner wrapper; [operations](docs/operations.md) is authoritative for this revision's budgets. Read `IMPLEMENTATION_HANDOFF.md` and source before modifying a target. This file is task guidance supplied with a package; it is not a preinstalled agent skill and does not provide infrastructure credentials or authorization to access a customer environment.

## Paste-ready implementation request

> Read README.md, IMPLEMENTATION_HANDOFF.md and AGENT_HANDOFF.md from this package. Implement a persistent Slurm evidence lake on the approved target cluster using the supplied configurable app and renderer. Discover the actual cluster identity, Slurm version/binary/service paths, source/accounting retention, storage, access rights, artifact layout and authentication. Write the resulting non-secret customer configuration and concrete deployment plan. Set up continuous scheduler/script capture, terminal completion/accounting capture, approved local and node-local raw logs/configuration/validation capture, checkpointed history recovery, Parquet publication, full-text indexing, authenticated browsing, restart/watchdog protection and boot mount ordering. Integrate actual job-ID manifests from our validation/training runners. Preserve raw provenance and explicit coverage/gaps/errors. Validate the implementation with isolated fixtures, real approved job evidence, process restart, independent export query/checksum reconstruction and a clear reboot-tested/untested record. Do not change scheduler policy, reset/reboot compute nodes, expose credentials, delete evidence or claim unavailable historical files were recovered. Produce a detailed deployment receipt and ready-to-export local evidence snapshot. Upload private raw data only to a separately authorized validation-hub destination.

## 1. Define the deliverable before action

A working capture pipeline has independently measurable source coverage and freshness. A browser screenshot or a table containing all numeric IDs is insufficient. Use these completion conditions:

1. Correct customer/cluster/epoch identity and persistent root.
2. Actual visible scheduler jobs captured, with batch scripts while retained.
3. Durable terminal source preserved; job-step/accounting scope implemented if required.
4. Real artifact paths registered for every promised validation/workload family.
5. Node-local capture covers the actual allocation; shared storage is not assumed.
6. Raw/configuration/validation hashes and immutable source versions retained.
7. Parquet published, search progressing and queries enforcing access restrictions.
8. Browser/timers/watchdog enabled with persistent mount dependency.
9. Restart recovery demonstrated without resetting the scheduler or deleting checkpoints.
10. Source gaps/deferred files/unsupported schema and open errors visible.
11. Standalone export independently queried and raw bytes reconstructed by hash.
12. Reboot proof and workload/fleet scope honestly recorded.

If the customer asks for all Slurm data, enumerate required scheduler/step/accounting/artifact sources and owners first. Register adapters for each. Do not promise an unlimited, lossless archive from polling alone.

## 2. First checks on an existing target

Before installing anything, inspect existing collector/service units, lake roots, mounts, source configuration, versions and live scheduler jobs. If a healthy collector exists, compare requested scope with its current coverage and adapt it without destroying state. Do not create a competing writer against the same root.

Read any applicable workspace/customer instructions and standing no-reboot policy. Identify current workloads that a controller/process test could affect. Inspect read permissions and approved SSH identity paths without printing values. Do not search the filesystem for password/token values.

If this is a fresh customer deployment, complete the discovery worksheet in the main handoff. If an access/source input is absent, continue documentation/rendering/tests that do not depend on it, then ask only for the specific missing non-secret connection/path/approval. Reuse existing authorized connection history rather than asking for credentials again.

## 3. Work sequence and review boundaries

### A. Evidence discovery

Capture scheduler version/config paths, job retention, accounting/completion source, file rotations, persistent storage, node access and artifact paths. Confirm exact user/job visibility. Expand allocation hostnames with the installed scheduler. Record source timezone behavior and cluster/job-ID epoch.

### B. Configuration and adapter implementation

Create a customer-specific copy of `examples/cluster.example.json`. No credential values. Keep the root isolated by cluster/epoch. Add trusted runner-manifest directories and exact capture allowlists. Implement missing source adapters or custom metrics parsers with fixture evidence; do not use timestamp coincidence as a job join.

The generic metadata adapter can discover scalar Slurm jobs and stdout/stderr. Per-rank logs, generated configs and validation outputs need an experiment manifest/template. If the customer's lifecycle includes arrays/heterogeneous jobs/federation/multiple phases per job, extend identity/parser/schema before claiming that scope.

### C. Local review/test and render

Run tests in a scratch copy/temporary lake. Verify package manifest. Render into an empty review directory with `tools/render_deployment.py`. Inspect source/unit/config output and resource/permission budgets. Check the actual target version's manuals for unsupported Slurm flags/systemd directives.

### D. Infrastructure installation

Use the owner's authorized account/procedure for persistent directories, service account/ACLs, approved SSH trust, local browser token/gateway and service installation. Implement concrete source paths before requesting approval for a genuinely new privileged/infrastructure change. No repeated permission request for already-authorized routine deployment work.

Never automatically replace a customer's existing completion plugin/accounting or restart/reconfigure scheduler services without that scope. Filetxt is an optional terminal feed; existing accounting can be adapted instead. Avoid unbounded synchronous hooks in the scheduler.

### E. Source commissioning

Run serial first passes as the real collection identity. Verify metadata and scripts before source expiration. Verify approved local and node-local files against actual hashes. Inspect explicit errors, per-host inventories and publication/search age. Enable timers only after initial source mapping works; document expected partial historical evidence.

### F. Access and recovery commissioning

Test anonymous and wrong-token denial; validate approved SSO reader access. Test browser/collector process restart independently of the scheduler. Confirm checkpoints and source hashes persist. Validate boot-enabled units/mount dependencies. Test real reboot only when explicitly authorized; otherwise record untested.

### G. Export/hub readiness

Capture a complete quiet/pinned generation, export locally, verify archive hash, query exported tables and reconstruct raw payloads independently. Produce tenant/cluster/epoch/job identity and schema/unit/redaction/gap provenance for hub import. Leave raw upload disabled until the owner authorizes the actual destination/sink.

## 4. Supplied executable files and limits

| File | Agent use |
|---|---|
| app/settings.py | Validated config selection, source roots, strict SSH arguments and manifest enumeration |
| app/history.py | Inventory/version journal, raw/redaction, local/scheduler source capture, normalization, Parquet publication/export |
| app/metadata.py | Fast scheduler discovery, durable generic manifests and submitted scripts |
| app/accounting.py | Optional existing sacct JSON capture; no accounting provisioning |
| app/live.py | Bounded multi-job/allocation raw capture and fair queue |
| app/backfill_remote.py | One terminal job per historical pass, fair retry of surviving remote evidence |
| app/search_index.py | Checkpointed FTS cache over immutable raw snapshots |
| app/reconcile_validations.py | Validation JSON reconciliation |
| app/reparse.py | Explicit retained-log reparse helper; review source selection before running |
| app/browser.py | Token-gated loopback browser, approved-table DuckDB, bounded text search/download |
| app/health_check.py | Independent freshness/open-error/disk check for external monitoring |
| tools/render_deployment.py | Non-privileged reviewed deployment/13 units |
| tools/write_job_manifest.py | Register real allocation/validation paths atomically |
| tools/backup_checkpoint.py | Online checkpoint backup and integrity check; payload backup still required |
| tools/verify_export.py | Independent raw Parquet reconstruction/checksum |

Review hard caps in source and main handoff. The package does not supply enterprise sharding, live remote append streaming, object-store lifecycle, distributed writer fencing, customer SSO itself, an external alert transport or a validation-hub API. Implement only the requested missing integrations, then prove them with actual data. Do not silently widen filesystem access or bypass guards.

## 5. State and data integrity rules

- Never remove `state/index.sqlite`, raw hashes, payload Parquet or queues to restart capture.
- Use one cluster/epoch per lake; namespace hub records with the manifest identity.
- Preserve failed validation/job evidence alongside successful retries.
- Keep scheduler terminal state, runtime validation state and qualification separate.
- Missing/unreadable files remain errors/coverage gaps; unknown is not pass/zero.
- BatchFlag=0 means no submitted batch script; keep actual diagnostic command evidence.
- Keep original/stored hashes separate when redaction changes bytes.
- Partial search/collection must display partial coverage.
- Retain raw logs even when a custom parser is absent; do not replace raw provenance with normalized values.
- Do not substitute printed rounded step_time for elapsed iteration_time without naming that choice.
- Preserve raw timezone strings; normalize only with verified timezone provenance.
- Avoid destructive retention until backup/export/hub acknowledgement is verified under customer policy.

## 6. Monitoring while implementing

During an active implementation, report concrete findings and blockers promptly. Check current workload/runner status when applicable so collection work does not hide a training failure. Distinguish source collector errors from scheduler/workload failures.

Record metadata/live/publication/search ages independently. A healthy browser process can serve stale data. Systemd “enabled” is boot intent, “active” is present unit state, and increasing capture timestamps are actual progress. A watchdog log is not a chat/email alert; wire the approved customer monitoring transport if notifications are required.

## 7. Recovery decisions

| Trigger | Required action |
|---|---|
| Stopped browser/timer | Verify mounted root and fixed unit list; restart affected collector, inspect fresh data |
| Stale active oneshot | Inspect timeout/transaction/IO; do not start a duplicate writer |
| Read permission/SSH identity mismatch | Resolve approved source identity/read rights; no blind host-key acceptance |
| Low disk | Report capacity growth and preserve evidence; add space/approved archive retention |
| Source missing after teardown | Record permanent gap; fix future terminal spool/retention |
| Accounting absent | Use available completion source and document missing step/accounting scope |
| Invalid metrics | Compare raw archived bytes, version parser fixtures and reparse preserved snapshots |
| Unexpected job-ID reset | New epoch/root; no merging old IDs with new jobs |
| Export collision/concurrent publication | Use quiet/pinned-generation procedure and verify all referenced payloads |
| Reboot forbidden | Do process/checkpoint/enablement tests and mark real reboot untested |

## 8. Deployment receipt template

Write a machine-readable JSON receipt plus an operator-facing report. Suggested fields:

```json
{
  "checked_utc": "actual UTC timestamp",
  "site": "actual site",
  "cluster": "actual cluster",
  "cluster_epoch": "actual epoch",
  "source_package_sha256": "actual checksum",
  "configuration_sha256": "non-secret config checksum",
  "dependency_lock_sha256": "actual checksum",
  "runtime_versions": {},
  "persistent_root": "actual persistent path",
  "source_contract": [],
  "units_enabled": [],
  "units_active": [],
  "source_freshness": {},
  "fixture_test_receipt": "path",
  "real_test_job_ids": [],
  "expected_and_recovered_host_file_counts": {},
  "open_errors": [],
  "historical_gaps": [],
  "checkpoint_restart_verified": false,
  "browser_process_restart_verified": false,
  "real_reboot_verified": false,
  "reboot_test_reason_or_receipt": "actual reason/receipt",
  "export_archive_sha256": "actual checksum",
  "raw_payload_roundtrip_verified": false,
  "hub_upload_authorized_and_performed": false
}
```

Replace booleans only with actual evidence. Include owner-approved limitations and next integration steps. Do not copy secrets, private keys, tokens or full environments into the receipt.

## 9. Expected final communication

State what was deployed, exact evidence sources/coverage, which restart/boot behavior was tested, remaining gaps and the artifact locations. Link the runbook, configuration, test receipt and source/export checksums. If hub upload occurred under explicit authorization, include destination and readback receipt. Otherwise distinguish a locally verified export from external delivery.

Do not call an adapter complete because a generic fixture passed. Do not claim all historical raw files are recovered because job IDs are indexed. The operator needs enough evidence to reproduce the implementation and understand what data can be trusted.
