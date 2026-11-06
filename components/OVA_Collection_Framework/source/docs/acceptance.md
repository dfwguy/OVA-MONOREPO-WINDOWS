# Commissioning and job-1 acceptance

Return to [README](../README.md). Mark a campaign capture-ready only after the source contract is proven on its actual cluster. Automated fixtures verify software behavior, not target completeness or performance.

## Arm before the first job

Keep validation submissions closed while commissioning. Confirm one cluster/epoch/root, persistent filesystem/mounts, native completion or accounting, actual all-user scheduler visibility, trusted runner registration, source ACLs and artifact retention. Verify no existing collector writes the same root. Choose shared durable run artifacts when compute-node reboot would erase local scratch. Establish the campaign's actual first job identity; do not reset a working scheduler to obtain numeric job 1.

Write an explicit coverage inventory: every workload family, job/step identity type, node scope, stdout/stderr, scripts, configs, rank logs, validation outputs and external evidence. For each source record readability, retention, size bounds and capture mechanism. Missing source ownership or oversized files prevent an “every artifact” claim. Scalar job support does not imply array/federation support.

## Real job evidence

Use small owner-approved commissioning workloads before campaign release. Run one successful job, one validation failure, one cancelled job and one job shorter than the polling cadence. Preserve their exact outputs, scripts and configs in registered durable run directories. Compare completion inventory independently with collector job rows, coverage and artifact hashes. Short jobs must appear through the durable terminal feed even if their live scheduler script expires.

Verify per-host node-local inventory where used. Compare actual file counts/bytes/hashes with `remote_coverage` and `artifacts`. Inventory counts are per-pass, not proof of all expected files; compare the declared manifest and final filesystem snapshot. Redacted stored hashes differ from original hashes and must be labelled. A workload that returns zero does not automatically pass its validation or qualification criteria.

## Fault and recovery tests

| Check | Required evidence |
| --- | --- |
| Browser authentication | Anonymous, incorrect token and tampered session denied; approved session works |
| Browser crash | Only browser process killed; systemd restarts it; collector still advances |
| Collector interruption | Terminate one collection process; restart reopens state; previously captured hashes remain valid |
| Interrupted publication | Prior complete generation still queryable; later generation complete; no referenced missing payload |
| Remote outage | One scoped source unavailable; explicit error; other hosts progress; recovery clears error and restores bytes |
| Collector reboot | Approved reboot: mount present, timers restart, retained source replay recovers missed jobs/files |
| Compute reboot | Approved reboot: declared persistent/shared sources survive and resume capture |
| Long accounting outage | Cursor remains behind source end; replay advances without skipping retained windows |
| Portable export | Standalone DuckDB query and full stored-byte SHA-256 reconstruction pass |

Do not reboot or reset nodes merely to test a software bundle. If target reboot tests are not authorized or feasible, record `real_reboot_tested=false` and the reason. A fixture checkpoint reopening is never labelled a real reboot.

## Noninterference acceptance

Measure baseline and collection-enabled job launch latency, validation wall time, controller RPC rate, collector CPU/RSS/IO, node read IO and network traffic under representative concurrent runs. Use the site's agreed tolerances and confidence window; this package does not invent a universal allowable slowdown. Confirm no GPU allocation, scheduler-policy change or synchronous remote upload was introduced. Reduce budgets or move storage/collector placement when overhead exceeds those tolerances, then repeat coverage/freshness checks.

Record deployment revision, dependency/config hashes, exact tested job IDs, source coverage, open gaps, process/reboot tests, workload scope, overhead results and export checksum in the deployment receipt. Change capture-ready/complete booleans only from real evidence. The installer emits an installation receipt; commissioning updates it with evidence paths.

At campaign end compare every independent terminal job against recovered records, finalize still-running jobs and exact declared artifacts, resolve or explain gaps, then export. Handover is complete only when the recipient verifies the agreed evidence scope and records unresolved limitations.
