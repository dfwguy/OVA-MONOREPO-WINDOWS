---
name: nvis-p2p-deploy
description: Install, configure, deploy, reconcile, verify, or safely roll back an NVIS-P2P release for persistent Dragonfly/dfstore container distribution across an SU-based compute fleet. Use for new-cluster bootstrap, catalog rollout, node reprovision recovery, and fleet integrity repair; do not use for Slurm, GPU, validation-job, NHC, or unrelated monitoring changes.
---

> Revision02 delivery note: this legacy skill describes the optional full native-dfstore/MinIO persistence architecture. For a basic Dragonfly installation follow the kit-root AGENTS.md and agent_handoff.md, using scripts/render-minimal.py and the shipped minimal runtime images. MinIO/NGC and fixed-site fleet operations are not default prerequisites.


# NVIS-P2P Deployment

Operate an NVIS-P2P release end to end without interactive prompts. Discover the release, validate explicit inputs, generate a bounded eligible roster, install the server and lightweight compute peers, persist the catalog through native `dfstore`, reconcile images, start the console, and verify exact content. Never treat reachability or file presence alone as success.

## Noninteractive contract

Read configuration from environment variables or an operator-supplied environment file. Never prompt for a missing value and never guess a credential. If a required input is absent or unsafe, stop before mutation and report every missing/invalid variable in one response.

Required inputs:

```bash
NVIS_P2P_RELEASE=/absolute/path/to/extracted/NVIS-P2P
NVIS_P2P_CONTROL_IP=<compute-facing-control-plane-IP>
NVIS_P2P_MANAGEMENT_IP=<management-console-IP>
NVIS_P2P_CANONICAL_DIR=/absolute/path/to/canonical-images
NVIS_P2P_INVENTORY=/absolute/path/to/approved-hostname-roster
NVIS_P2P_SSH_USER=<non-root-service-account>
NVIS_P2P_NODE_CONTAINER_DIR=/opt/containers
NVIS_P2P_OBJECT_DATA=/absolute/persistent/object-store/path
NVIS_P2P_SEED_CACHE=/absolute/persistent/seed-cache-path
NVIS_P2P_SEED2_CACHE=/absolute/persistent/second-seed-cache-path
NVIS_P2P_CONSOLE_PORT=4300
NVIS_P2P_SU_COUNT=<positive-integer>
NVIS_P2P_NODES_PER_SU=<positive-integer>
NVIS_P2P_EXPECTED_ARCH=aarch64
NVIS_P2P_EXPECTED_PAGE_SIZE=65536
```

Secret inputs are file paths, never literal values:

```bash
NVIS_P2P_MANAGER_ENV_FILE=/absolute/mode-0600/manager.env
NVIS_P2P_DFSTORE_IMPORT_ENV_FILE=/absolute/mode-0600/dfstore-import.env
NVIS_P2P_DFSTORE_READONLY_ENV_FILE=/absolute/mode-0600/dfstore-readonly.env
NVIS_P2P_OBJECT_ROOT_PASSWORD_FILE=/absolute/mode-0600/object-root-password
```

Optional controls have conservative defaults:

```bash
NVIS_P2P_PREFLIGHT_PARALLELISM=${NVIS_P2P_PREFLIGHT_PARALLELISM:-32}
NVIS_P2P_DEPLOY_PARALLELISM=${NVIS_P2P_DEPLOY_PARALLELISM:-32}
NVIS_P2P_SYNC_START_PARALLELISM=${NVIS_P2P_SYNC_START_PARALLELISM:-12}
NVIS_P2P_SYNC_PARALLELISM=${NVIS_P2P_SYNC_PARALLELISM:-48}
NVIS_P2P_MAX_START_ATTEMPTS=${NVIS_P2P_MAX_START_ATTEMPTS:-3}
NVIS_P2P_MAX_UNREACHABLE_CHECKS=${NVIS_P2P_MAX_UNREACHABLE_CHECKS:-3}
NVIS_P2P_SYNC_TIMEOUT_SECONDS=${NVIS_P2P_SYNC_TIMEOUT_SECONDS:-86400}
NVIS_P2P_MODE=${NVIS_P2P_MODE:-deploy}
```

Accept `NVIS_P2P_MODE` values `plan`, `deploy`, `reconcile`, `verify`, or `rollback`. `plan` is read-only. `rollback` additionally requires `NVIS_P2P_ALLOW_ROLLBACK=YES` and an explicit prior-release path. Never infer approval for rollback or data removal.

## Invariants

- Use only the supplied inventory and catalog. Never discover targets by scanning a subnet.
- Normalize the inventory to nonempty, comment-free, unique hostnames and reject invalid tokens.
- Preserve SSH host-key verification. A changed key is a security deferral, not a retry workaround.
- Intersect requested SUs with a preflight-produced eligible allow-list before mutation.
- Run at most one fleet mutation at a time and use the release's operation lock.
- Install only the small Dragonfly client and NVIS units on compute nodes. Do not install Docker, CUDA, GPU agents, NHC, or monitoring stacks.
- Do not modify Slurm, drain nodes, launch validation jobs, query `journalctl`, or touch GPUs.
- Compute peers must have back-to-source disabled; only controlled seed peers may contact origin.
- Preserve compute cache, Dragonfly storage, receipts, quarantine, and valid container files across upgrades/reconciliation.
- Process catalog images sequentially for persistence. Avoid simultaneous fleet-wide hashing.
- A node is complete only with the expected byte count and SHA-256 receipt for every catalog image, plus the current-wave `failed=0` completion marker.
- Bound retries and explicitly defer exhausted nodes. Never loop indefinitely.

## Discover and validate the release

1. Resolve every path with `realpath`; reject non-absolute paths, missing paths, symlink escapes outside the release, and broad destructive targets such as `/`, a home directory, or the release parent.
2. Run the bundled read-only checker when present:

   ```bash
   "$NVIS_P2P_RELEASE/release/nvis-p2p-deploy/scripts/preflight-release.sh"
   ```

3. Require the catalog, peer template, compute units, fleet scripts, and matching `dfdaemon`, `dfget`, and `dfstore` release binaries.
4. Validate JSON, shell syntax, Python syntax, Compose rendering, executable bits, and shipped checksums/signatures. Do not rebuild a binary merely because the target architecture differs; select the signed artifact matching the target or stop.
5. Confirm catalog JSON and TSV describe the same filenames, sizes, and digests. Confirm every canonical file exists and matches both size and SHA-256 before any import.
6. Validate secret file ownership/mode without printing contents. Require mode `0600` or stricter and reject world/group-readable secrets.
7. Detect current listeners, containers, units, and data directories. Preserve existing unrelated services; reject port/path collisions rather than stopping them.

For release layout and health sources, read [references/architecture.md](references/architecture.md). For precise phase gates and exception handling, read [references/operations.md](references/operations.md).

## Generate inventory and eligible roster

Never scan for nodes. Read `NVIS_P2P_INVENTORY`, strip blank/comment lines, validate the approved hostname pattern supplied by the deployment, sort uniquely, and write a timestamped normalized roster under release state.

Derive SU membership from an explicit inventory field/mapping or a reviewed hostname mapping. Do not infer a new naming convention. Verify the total does not exceed `NVIS_P2P_SU_COUNT * NVIS_P2P_NODES_PER_SU`; missing slots are unavailable, not fabricated nodes.

Run bounded preflight and record one TSV row per requested node. Eligibility requires SSH success with the trusted host key, expected architecture/page size, expected service identity, narrowly required noninteractive sudo, writable/traversable container paths, sufficient free space, no conflicting legacy transfer, and routable service addresses.

Write separate eligible and deferred rosters. Include the exact reason for every deferred node. Continue only if the eligible roster is nonempty and the requested/canary scope is satisfied.

## Render configuration

Render from release templates into a timestamped staging directory; never substitute directly in tracked templates. Replace control, management, storage, console, database, scheduler, seed, node, and SU values only from the validated contract.

Require Manager REST and the operations API to remain loopback-only; bind the console only to loopback and the explicit management address; keep object-store administration loopback-only; use TLS for the object API; separate import and read-only credentials; deploy only read-only export credentials to compute; redact secrets; keep compute back-to-source disabled; and use persistent seed/object data paths.

Validate rendered Compose/config files before installation. Save a redacted rendered-config manifest and its digest.

## Install and start the server

Install in dependency order: persistent database/Redis, TLS object store, Manager/scheduler, canonical read-only origin, seed peers, loopback operations API, then the NVIS console.

Use pinned container digests and packaged binaries. Enable restart policies/units only after configuration validation. Do not stop unrelated containers or services.

Before compute deployment, require healthy object store, Manager, scheduler, seeds, operations API, and console. Confirm listeners are bound only to intended interfaces.

## Install compute clients

Start with the release's canary roster. For each eligible node:

1. Create the NVIS structure below `NVIS_P2P_NODE_CONTAINER_DIR/.nvis-p2p` without deleting existing data.
2. Stage `dfdaemon`, `dfget`, `dfstore`, catalog, peer config, read-only export environment, sync script, and systemd units under unique names.
3. Verify binary digests before promotion.
4. Atomically install with the service identity and restrictive secret mode.
5. Reload systemd, enable/start the peer, and enable catalog reconciliation.
6. Require the local dfdaemon socket and active peer unit.

Record READY or DEFERRED exactly once per node. Retry transient SSH/start failures at low concurrency no more than `NVIS_P2P_MAX_START_ATTEMPTS`. Do not retry permissions, host-key changes, unexpected identity, architecture mismatch, insufficient disk, or checksum mismatch as though transient. Expand by SU only after canary gates pass.

## Persist the catalog with dfstore

For each image sequentially, revalidate canonical size/digest, use the server-only import credential, run native `dfstore import` through a healthy seed socket to `s3://<bucket>/images/<sha256>/<filename>`, request configured persistence, write a receipt only after success, and verify visibility before advancing.

Never put the import credential on compute nodes. Never substitute a plain per-node copy loop for persistent dfstore distribution.

## Reconcile the fleet

Start the packaged catalog-sync service with nonblocking systemd calls on the eligible roster. Keep start concurrency at or below 16 and poll concurrency at or below 64 unless the release documents a tested lower limit.

Poll with short-lived SSH calls and read only systemd state plus the catalog sync log; never poll `journalctl`. Node-side native `dfstore export` owns transfer logic.

Classify `COMPLETE` only after a current-wave `NVIS_P2P_SYNC_COMPLETE ... failed=0`; `PENDING` while active without a terminal marker; `FAILED` for explicit failure, inactive/dead without marker, missing service/log, or integrity failure; `UNREACHABLE` for SSH failure; and `DEFERRED` only when the relevant bound is reached.

Skip valid files/receipts, hash expected-size unreceipted files once, quarantine stale/mismatched content, and atomically replace only after digest validation. Write complete, deferred, tracking, summary, and wave-log artifacts. Never count deferrals as complete.

## Start validation and UI

After canary reconciliation, run service and artifact validation without launching workload benchmarks unless separately requested. Validate health/listeners, dynamic catalog count, persistence receipts, client digests, a verified canary export, operation locking, and console sign-in/Artifact Fleet/SU selection/sync overlay/heatmap/log access.

Start or retain the console only after backend health is green. Report the management URL and tunnel command without credentials. Require first-login password rotation.

## Verify completion

Verify every reachable eligible node. Every required image needs the canonical filename, expected bytes, and exact SHA-256 receipt; also verify effective systemd properties, peer socket, and latest current-wave completion. Recheck repaired exceptions.

Produce totals for requested, eligible, complete, pending, deferred, and unreachable plus exact exception rosters. Do not say “all caught up” unless complete equals currently reachable eligible and pending is zero.

## Reboot, reprovision, and rollback

For reboot, preserve storage/cache/receipts, ensure units are enabled, let the peer return, reconcile, and verify. For reprovision, validate the new host key through the approved process, preflight, reinstall, reconcile, and verify; never automatically delete or accept a host key.

Rollback requires `NVIS_P2P_MODE=rollback`, `NVIS_P2P_ALLOW_ROLLBACK=YES`, and an explicit validated prior release. Stop admission of new operations, let active transfers reach a safe terminal point, restore a canary atomically, and verify before expansion. Preserve images, receipts, cache/storage, quarantine, object data, seed caches, and logs. Data deletion requires separate explicit authorization.

## Final report

Report release identity/checksums, redacted configuration digest, server health/listeners, catalog count/persistence, requested/eligible/complete/pending/deferred/unreachable totals by SU, exact exceptions, evidence paths, rollback point, and skipped phases. Never expose a secret.
