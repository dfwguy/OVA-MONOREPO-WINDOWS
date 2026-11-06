# Continuous capture, recovery and workload impact

Return to [README](../README.md). Collect asynchronously on a dedicated host and keep durable terminal/run sources. Workload execution does not depend on browser, hub or Parquet availability.

## Default budgets

| Stage | Cadence after completion | CPU / memory cap | Timeout |
| --- | --- | --- | --- |
| Metadata | 15 s | 25% of one CPU / 384 MiB | 60 s |
| Active node capture | 15 s | 25% / 768 MiB | 180 s |
| Local scan/publication | 60 s | 50% / 1500 MiB | 600 s |
| Terminal node replay | 120 s | 25% / 768 MiB | 180 s |
| Text index | 5 s | 50% / 512 MiB | 120 s |
| Browser | On demand | 100% / 768 MiB | Restart on process failure |
| Watchdog | 60 s | 10% / 128 MiB | 120 s |

`Nice=15`, low IO weight, idle IO scheduling and service limits are rendered into collector units. CPU quotas describe CPU time, not a percentage of total host CPUs. IO weight is relative and device/cgroup dependent; it is not a bandwidth ceiling. Put the collector on storage separate from training IO where possible. Browser queries use one DuckDB thread, a 256 MiB engine budget, a 10 s query interrupt and 1,000 returned rows. Search has independent bounded scan/result limits.

Remote collection is disabled in the example for shared durable artifact deployments. Enable `remote_capture_enabled` only when node-local sources and SSH trust are commissioned. At most two node reads run concurrently in each active/history service. Each service selects eight hosts per pass by default; active and history can overlap, so the total can reach four remote reads. Each remote read has a 15 s default timeout and a 32 MiB byte budget. Remote commands run at `nice 19`; they do not allocate GPUs. The queue persists per job/host attempts and rotates through large fleets. Fleet revisit age must fit source retention. Host count, permission failures and deferred files remain visible. Host count beyond `remote_manifest_limit` is an explicit commissioning gap.

The metadata adapter reads current jobs and retained scripts; its cost grows with job count. Accounting is rate-limited independently to 300 s with a durable overlapping cursor and 24-hour query slices. A long outage replays retained accounting windows progressively. Set `accounting_start_utc` to an aware ISO timestamp when commissioning historical scope; initial default history is 48 hours. Accounting retention must exceed outages and replay delay.

## Capture limits and capacity

Snapshot capture limits remote files to 64 MiB; local files over 256 MiB use bounded-memory streaming with a 120 s per-file budget. Streamed sources must remain unchanged for a capture to commit. Parquet payload publication writes 1 MiB chunks incrementally rather than materializing entire files. Large-stream metric extraction is deferred, while raw stored bytes remain reconstructable. High-rate growing logs retain repeated snapshots and can amplify storage. Prefer final large logs in durable shared run directories; oversized remote logs or sources exceeding the stable-read/pass budget need a site adapter before complete-capture acceptance. Retain originals until exact final hashes are verified. Data-volume and fleet-specific adapter work is a real deployment prerequisite, not an automatic property of this baseline.

Raw payloads, exports and Parquet metadata generations have no automatic destructive retention. Monitor their growth. Retain the generations pinned by queries/exports and adopt a reviewed cleanup policy after backups/hub acknowledgement. Publication stops below 2 GiB free and warns below 20 GiB; collectors do not stop workloads or delete evidence to make room. Disk exhaustion can still prevent capture. Provision headroom and alert before the thresholds.

Missing numeric IDs are possible because IDs are not necessarily contiguous. Reconcile against scheduler accounting/completion inventory; distinguish unused IDs, unsupported identities, unreadable artifacts, jobs outside scope and actual permanent loss.

## Monitoring

Run `app/health_check.py` with `SLURM_HISTORY_CONFIG` set to the installed private config. It exits nonzero on stale source/publication/search health, open errors or low disk. When remote collection is enabled, partial/error host coverage also makes the check fail. Connect its JSON output and exit status to the customer's monitoring system. A watchdog restart is a local action, not a delivered alert. Track source age, queue depth, per-host partial/error state, disk growth, capture throughput and source-retention headroom.

Timers being enabled proves boot configuration; active services prove present process state. Increasing capture timestamps and verified content prove progress. Compare wall-clock/source-age lag during realistic simultaneous jobs. Configure freshness budgets from measured revisit times rather than using browser health as a completeness claim.

## Recovery matrix

| Failure | Automatic behavior | Operator verification |
| --- | --- | --- |
| Browser exits | Systemd restarts it | Authentication still fails closed; published data age is acceptable |
| Collector process exits | Retry on failure; next timer resumes checkpoints | SQLite integrity, payload hashes and no duplicated artifact versions |
| Collector host reboot | Mount dependencies and enabled timers restart collection | Persistent root mounted, unit timestamps advance, accounting/terminal replay completes |
| Compute reboot/SSH outage | Failed source is recorded and retried | Node-local files survived or shared durable copies are available |
| Controller unavailable | Metadata fails; terminal sources remain retained | Scheduler recovery, missed-job reconciliation and script retention |
| Export/hub unavailable | Collection continues locally | Capacity margin and eventual verified transfer |
| Source deleted | No reconstruction from missing bytes | Record permanent gap and fix retention for later jobs |
| Storage loss | Software restart cannot restore lost data | Restore checkpoint plus all referenced payloads from tested backup |

For maintenance stop the watchdog timer first, then collection timers/services and browser; otherwise it may restart deliberately stopped units. Use exact names from the rendered plan. Keep checkpoint/data untouched. Back up SQLite using `tools/backup_checkpoint.py`, not a casual copy of a live WAL database. A complete disaster-recovery backup includes state, raw payloads, Parquet payloads, configuration, code/dependency identities and secret references stored separately.

## Reboot and zero-downtime claims

Service definitions and restart fixtures are validated in CI. This release does not claim a real target-controller or compute reboot was performed. Run approved reboot tests in [acceptance](acceptance.md) with retained evidence and no production disruption. Capturing after reboot is different from collecting while a host is off. Continuous zero downtime requires retained redundant sources, monitored storage and a fenced failover writer; this baseline is one writer per lake.

Large-file redaction processes bounded log records. Binary/very long records can split at 1 MiB, so pattern redaction is not a general secret-sanitization guarantee. Never put credentials in captured run logs/configs; apply the owner's export classification review.
