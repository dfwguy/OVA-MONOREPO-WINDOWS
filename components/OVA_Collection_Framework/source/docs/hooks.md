# Agent harness, runner hooks and Slurm integration

Return to [README](../README.md). The harness is a documented execution contract for a coding/operations agent; it is not tied to one model, SDK or cluster provider. Read [AGENT_HANDOFF](../AGENT_HANDOFF.md) for the full task and receipt.

## Harness phases

| Phase | Action | Evidence gate |
| --- | --- | --- |
| Discover | Inspect scheduler version/visibility, completion/accounting retention, persistent storage, artifact roots and existing collectors | Private configuration, exact supported identity scope and source owners |
| Prepare | Verify source bundle; run fixtures; render installation; provision ACLs and trust | Reviewed plan and dependency provenance |
| Deploy | Run `deploy.py apply` on authorized collector | Installed source/version, enabled units, source preflight and installation receipt |
| Arm | Verify terminal feed, trusted runner manifests and artifact retention before first submission | Acceptance gate authorizes campaign capture scope |
| Observe | Inspect metadata/live/publication/search freshness, gaps, host inventory and open errors | Increasing timestamps and captured raw bytes; browser availability alone is insufficient |
| Recover | Restart affected collection services, replay retained sources, validate cursor/checkpoint integrity | Hash-verified recovery with outage/gap record |
| Handover | Finalize outstanding jobs, reconcile all sources, publish/export/verify | Portable export and honest coverage receipt |

The agent acts through the installed collector and bounded tools. It never stores raw customer evidence in the software repository. Missing approved access or platform configuration is a concrete input, not a reason to invent a universal default. It does not reset job IDs, change fabric settings or mark qualification from a collector health check.

## Automatic Slurm completion plugin

Use Slurm's native `jobcomp/filetxt` on fresh clusters or the existing site terminal/accounting integration. Every completed, failed, timed-out or cancelled scoped job must appear in the retained feed even when it finishes between live polls. The collector replays completion records and retains raw source evidence. The filetxt plugin records job completion metadata; it does not capture arbitrary stdout or application configuration.

A Python/network/Parquet operation never runs synchronously in a Slurm prolog, epilog or job-submit callback in this design. This prevents collection outages from turning into scheduler launch failures. The native plugin still writes a local file and must have healthy durable storage. Slurm's [prolog/epilog guide](https://slurm.schedmd.com/prolog_epilog.html) describes the operational consequences of hook failures; existing hooks are preserved. This is a completion-feed integration, not an unverified custom Slurm ABI plugin.

## Plug-in runner wrapper

For scalar batch validations with durable shared run directories, use:

```sh
python3 tools/submit.py --config /etc/ova-collection/cluster.json \
  --run-dir /srv/validation/results/<unique-run> --script /path/to/validation.sbatch -- --partition=<approved-partition>
```

The wrapper archives the script before submission, manages `%j` stdout/stderr paths, calls `sbatch --parsable`, records the real job ID and registers a manifest. It does not hold a job or wait for collection. Each invocation must use a new run directory. The runner's identity needs write permission in the trusted registration directory. A submitted job survives a later manifest-registration error; the wrapper reports that distinction so the operator can register the preserved manifest manually. Never retry submission blindly.

Place generated configurations, validation JSON, command/version records and per-rank logs under that run directory. Application validation logic remains the validation runner's responsibility. All runs, including retries and failures, get independent IDs and immutable evidence. Do not execute the example manifest or populate its PASS fields as real observations.

## Existing runner lifecycle hooks

The common manifest contract has a numeric `job_id`, `nodes` array and approved `experiment` path; optional fields include `experiments`, `batch_host`, `stdout`, `stderr`, `workload`, `gpus`, provenance and validation/qualification state. A trusted runner can register it at submission and update it after allocation or completion:

```sh
python3 tools/write_job_manifest.py --config /etc/ova-collection/cluster.json --input /private/path/actual-job-manifest.json
```

Registration is locked, atomically replaced and flushed. The collector merges discovered allocation and scheduler state with runner metadata. Avoid stale updates that overwrite true outcomes; give one harness ownership of lifecycle updates. Never include a full environment or credential values. For node-local logs, list actual expanded allocation nodes and paths within `remote_allowed_roots`; capture must finish before cleanup/reboot removes the sources.

## Scope and extension rules

Interactive allocations have no batch script; archive their actual command/config through the runner manifest. Arrays, heterogeneous components and federation require compound identity support throughout the parser, database, browser, export and hub contract. Do not flatten them to scalar IDs. Unregistered sidecar files and external validation systems require explicit source adapters.

Stable large files on collector-readable storage use the included bounded-memory streaming adapter and chunked Parquet publication. Applications producing remote files above the snapshot limit, continuously changing large logs or sources beyond pass timeouts require a site-specific append/archive adapter with rotation and exact reconstruction tests. Retain those files durably while adapting; a metadata row does not satisfy raw capture. An agent must keep this unresolved in acceptance rather than silently raising memory budgets or asserting every run is captured.
