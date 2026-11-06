# Agent handoff: prepare and run NVIDIA Exemplar Performance

Read [README.md](README.md), [AGENTS.md](AGENTS.md), [run_exemplar.md](run_exemplar.md), [offline delivery](docs/airgap.md), and [acceptance criteria](docs/acceptance.md) before deployment work. This document is the portable execution contract for an agent; it contains no active campaign, prior scheduler job, customer inventory, or fixed hardware topology.

## Objective

Take an approved target environment from discovery to a verified installation capable of executing the requested official Exemplar workload matrix. When execution is authorized, submit that matrix, monitor real training progress, archive the results and leave a resumable checkpoint. Complete independent authorized work while identifying exact missing inputs. Do not stop after a package download or a plan when installation/execution is within scope.

## Required initial conversation

Collect missing inputs together using `config/cluster.example.json` as a checklist:

- Existing versus new cluster; approved controller access and operator account.
- Explicit compute inventory, GPU type/count, CPU architecture and desired workload/model/dtype/GPU-scale/repeat matrix.
- Slurm account/partition/QoS and whether scheduler/runtime/driver installation is within scope.
- Connected or air-gapped mode, approved staging system and transfer mechanism.
- Shared versus node-local storage, persistent roots, capacity and result destination.
- Fabric type, intended device/port inventory, approved transport settings and health evidence source.
- Prepare-only versus prepare-and-run scope and maintenance restrictions.

Ask the operator to provision credentials securely:

> Provision a Hugging Face read token in `<HF_TOKEN_FILE>` using a restricted local file or secret manager. The account must have approval for every selected gated model repository. Provision authorized NGC registry access in `<ENROOT_CREDENTIALS_FILE>`. Confirm paths and readiness; do not send credential values in chat.

For air-gapped targets, provision download credentials on the connected staging host. Only artifact closure should cross the boundary unless an approved secret provisioning mechanism requires otherwise. Determine how the agent executes inside the restricted environment; do not assume external model/API connectivity.

## Durable state contract

Use a private campaign directory under the approved evidence root. Record non-secret deployment inputs, a unique campaign ID, source revision, intended tuple matrix, per-node artifact receipts, phase checks, scheduler IDs and UTC observations. Keep append-only attempt/event records, generated configuration/scripts, rank logs and an evidence index.

On every resume, reconcile that state with the actual scheduler, active processes and held/running jobs. Empty queues, absent manifests and stale session names are not proof that a recipe completed. If accounting is unavailable, collect durable batch exit codes and per-rank completion evidence. Never submit a duplicate because an agent session restarted.

## Phase 1 — Discover without assuming readiness

Inspect versions and current state of OS/kernel/architecture, GPUs/topology, Slurm services/account/GRES/PMIx, Enroot/Pyxis/hooks, mounts/capacity/inodes, approved network devices and telemetry. Find any existing official source/install/cache/images and verify versions before reuse. Identify active jobs and other runners.

Deliverable: a discovery report with UTC timestamps, installed versus missing components, scope constraints, actual selected nodes, and the exact missing inputs. Use aliases in shareable reports. Do not copy secrets, environment dumps or unrelated filesystem content into the transcript.

## Phase 2 — Resolve the supported target

Pin an approved full upstream Git commit and release. Read its workload metadata, installer documentation and CLI help. Confirm every requested GPU type/model/dtype/scale tuple is supported. Verify target architecture and image dependencies. Determine diagnostic versus qualification purpose from the operator's goal and the pinned validation process.

Complete and structurally validate the local input file:

```bash
python3 tools/prepare.py validate-config config/cluster.local.json
```

Deliverable: a release/compatibility matrix and an installation plan with versioned dependencies, expected paths/mounts, secret references, storage budget, transport design and readiness evidence requirements. Structural validation is not permission to launch.

## Phase 3 — Prepare infrastructure

Within approved scope, prepare OS dependency closure, supported GPU driver/RDMA or libfabric stack, scheduler/GPU allocation, authentication and container runtime integration. Use the platform's maintained installation/configuration system. Reconcile UID/GID, clocks, PMIx libraries, Pyxis plugin and required distributed/GPU hooks. Make persistent cache/install/evidence paths writable by the intended identity.

For existing services, preserve configuration and current workload isolation. Driver/kernel changes, reboots, privileged restoration or fabric changes need an approved maintenance procedure. Do not mutate routes, reset GPUs or weaken health gates to make a benchmark start.

Deliverable: version/service manifest and scheduler/container smoke evidence. The upstream recipe installer does not provision a whole operating system or scheduler for you.

## Phase 4 — Obtain and install software

Connected mode: use secure credential provisioning and the official installer from the pinned checkout. Reconcile its generated cluster configuration with the reviewed inputs. Inspect any persisted secret values before staging or sharing configuration.

Air-gap mode: follow `docs/airgap.md`; build the source/image/model-cache/package/Python closure on a compatible connected host. Record registry digests and local image hashes, preserve internal cache links and exclude credentials. Verify the transferred payload, install without internet, and test absence of late downloads.

Deliverable: exact artifact inventory, provenance, non-secret effective configuration, installed CLI/workloads, and offline rehearsal evidence when applicable. Obtain missing source/helpers from approved upstreams instead of inventing an executable path.

## Phase 5 — Deliver to recipients

Shared layout: prove shared backing-store and container mount visibility from the actual compute nodes. Node-local layout: verify static payload identity at every intended recipient, preserve required absolute paths and keep per-node receipts.

Generated experiments need a separate per-job staging step. When using node-local paths, generate or submit held through the pinned supported CLI, inspect intended allocation, stage experiment files to all intended recipients, verify hashes/mounts, then release only after current readiness passes. Do not reuse old job scripts or assume image delivery also copied generated files.

Deliverable: static and generated payload receipts plus actual recipient/allocation mapping.

## Phase 6 — Validate the live cluster

Collect fresh whole-cohort GPU/power, scheduler/storage, runtime, rendezvous and communication evidence. Use the expected device/port inventory from the reviewed target; no fixed NIC count, GID, traffic class or socket interface is universal. Test inside the actual container with the intended rank bootstrap and transport.

Run canaries before the full-cohort collective test. Confirm every intended rank and device/provider is represented. A one-node, reduced-rail or host-only test is diagnostic evidence, not full-scale launch acceptance. Refresh evidence after configuration, cohort, artifact or boot changes and recheck dynamic health just before submission.

Deliverable: readiness record tied to cohort, source/image/configuration identity, time, checks and evidence. Never create a ready flag from intention or rewrite timestamps.

## Phase 7 — Plan and execute the recipe

Use the pinned CLI to preview each explicit tuple. Inspect generated account/partition/node/rank/GPU count, image/mounts, precision, model and parallelism. If execution is in scope and the gates pass, launch only the reviewed matrix, with a campaign lock and durable attempt records.

Inspect `llmb-run exemplar` behavior separately before using it: a qualification suite command may select a fixed scale. A smaller supported diagnostic must use its explicit tuple and be labeled accordingly.

Monitor scheduler and actual iteration progress. Report latest completed step/time, step duration, modeled throughput with units, rank/transport evidence and first faults. Archive all node-local outputs before advancing. On setup/staging/integrity/evidence failure halt affected advancement; on a workload failure preserve first-fault evidence, diagnose and allow at most one authorized corrected retry before halting the campaign on another failure.

Deliverable: real scheduler IDs, generated scripts/configs, complete logs, outcome/attempt history and parsed metrics. Do not classify missing log evidence as success.

## Phase 8 — Archive and hand off

Use the pinned archive CLI after collecting all remote outputs. Package external readiness/fabric records separately if not included. Scan for secrets, retain hashes, verify upload readback only when an upload destination is authorized, and record retention policy.

Report completed preparation gates and actual recipe outcomes separately. Compare performance only with a matching approved baseline and scoring window. Qualification follows the applicable NVIDIA validation/review process; exit zero alone does not confer certification.

Leave a checkpoint with active/held jobs, evidence paths/times/hashes, secret provisioning status, blockers and the next exact safe action. Never automatically message another person, upload results or operate another environment beyond the approved scope.
