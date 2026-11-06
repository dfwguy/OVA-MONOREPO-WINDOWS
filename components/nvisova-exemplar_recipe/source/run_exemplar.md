# Installation and execution runbook

This procedure starts with the private inputs described in [README.md](README.md) and is executed by the agent according to [the handoff](agent_exemplar_skills.md). All paths, node counts and workload selections come from the target configuration. Examples use non-secret variables, not a past deployment's values.

## 1. Establish the workspace and checkpoint

Use an approved controller account and persistent working directory. Read local agent instructions and maintenance restrictions. Create a unique private campaign/evidence directory, record the operator's prepare-only or prepare-and-run scope, and identify all active/held scheduler jobs before mutation.

Store a filled copy of `config/cluster.example.json` outside Git or as ignored `config/cluster.local.json`. Replace placeholder strings and null integers. Record actual inventory privately and use a short alias in shareable reports. Validate:

```bash
python3 tools/prepare.py validate-config config/cluster.local.json
```

Keep a phase ledger with UTC time, status, exact input/source/artifact identities, evidence paths and next action. Validation of configuration is structural; it does not check remote services or official workload support.

## 2. Discover the target

Run commands through the approved controller and compute access path. Do not paste whole environment dumps into logs. Representative read-only commands:

```bash
uname -m
uname -r
python3 --version
bash --version
sinfo -N -o '%N %t %G'
squeue -o '%.18i %.30j %.12T %.10M %.6D %R'
srun --mpi=list
nvidia-smi -L
nvidia-smi topo -m
nvidia-smi -q
```

Check Slurm account/partition/QoS and service state using the site's supported commands. Establish whether GRES matches actual device count, identities are consistent, authentication works, time is synchronized and accounting is available. Review GPUs for current errors/reset requirements rather than relying on count alone.

For each intended node check persistent mount backing, path permissions, free bytes/inodes, kernel/driver/runtime versions, GPU/NIC topology, Enroot/Pyxis/hooks and cache locations. Examine network device/port state using platform-specific tooling: verbs and RoCE settings for the corresponding platforms, or provider/libfabric/EFA validation for EFA. Save the expected inventory and current result.

Do not run distributed diagnostic jobs until access and scheduler scope allow them. A diagnostic consumes resources and is not merely a documentation read.

## 3. Resolve source and workload compatibility

Choose the approved release, full immutable upstream commit, target GPU/architecture and explicit workload/model/dtype/scale tuples. Read source metadata and pinned documentation. Confirm node count times GPUs per node can satisfy the scale and required recipe parallelism. Whole-node arithmetic alone does not prove a recipe supports the selected scale.

On a connected installation host:

```bash
git clone https://github.com/NVIDIA/exemplar-performance.git "$LLMB_REPO"
git -C "$LLMB_REPO" checkout --detach "$UPSTREAM_COMMIT"
git -C "$LLMB_REPO" lfs pull
```

Materialize required submodules and workload helper repositories according to the pinned installer. Retain source/version provenance. For offline targets, perform acquisition on staging and transfer a verified source export with all required content; use [the air-gap procedure](docs/airgap.md).

## 4. Prepare host and scheduler prerequisites

Reconcile the README responsibility matrix with existing services. If missing components are within scope, install through approved distro/platform provisioning. Choose a tested GPU-driver/container-CUDA/RDMA-or-libfabric combination for the platform. Container user-space CUDA does not replace the host driver.

Prepare supported Python/tooling on the controller. Configure Slurm GPU allocation, affinity and PMIx, consistent identities, authentication, partition/account/QoS and required service persistence. Prepare Enroot, Pyxis/SPANK, GPU and distributed hooks, runtime/cache paths and required writable/remap behavior from the pinned platform documentation.

Read the effective configuration; do not assume installation of a package enabled the plugin. Validate a small approved allocation and inspect container GPU/network visibility. Preserve backups and change records. Driver/kernel changes or disruptive service actions require the approved maintenance plan, not a benchmark workaround.

For ephemeral compute roots, use the platform's existing image/bootstrap process and secure scheduler-secret provisioning. Verify current-boot state without demanding a reboot. Persistent images/install/cache/evidence must survive the documented restart model.

## 5. Provision access and install workloads

Ask for secure HF/NGC provisioning as specified in README section 6. Check only file presence/owner/mode and authenticated access outcomes; never print values. Check gated model approvals separately. Use a restricted process environment or the tool's supported credential provider when needed.

Inspect `install.sh` and its help from the pinned checkout, then run the official installer in the approved environment. Select exact GPU type, architecture, install/image directories, account/partition and workload list. The installer produces release-specific `cluster_config.yaml`; reconcile its fields with the private input file rather than substituting this kit's JSON.

```bash
cd "$LLMB_REPO"
./install.sh -i "$IMAGE_ROOT"
cd "$LLMB_INSTALL"
llmb-run --help
llmb-run list
```

Inspect image existence/provenance, workload helper repositories, model metadata/cache and Python environments. Check generated configs/scripts for persisted token values before distribution. Determine what can run offline and remove unnecessary token propagation from benchmark jobs. Do not modify official recipe semantics to avoid missing artifacts.

For air-gap mode, complete the offline closure and clean rehearsal before proceeding. A local image alone is insufficient when launch still fetches Python packages, Git content or HF model files.

## 6. Verify and distribute static artifacts

Build a reviewed payload directory containing distributable source, images, packages, caches and non-secret configuration. The manifest must be outside it:

```bash
python3 tools/prepare.py manifest "$PAYLOAD_ROOT" "$PAYLOAD_MANIFEST"
python3 tools/prepare.py verify "$PAYLOAD_ROOT" "$PAYLOAD_MANIFEST"
```

Use a trusted manifest channel and factory secret/malware/provenance checks. Transfer to the target and every intended node-local recipient using the approved transport. Preserve internal relative cache links and executable flags. Reverify at the destination and keep per-recipient receipts. If absolute paths differ, rebuild or adapt environments/configuration under review and create new hashes.

For shared storage, collect compute-side file/mount identity evidence and container visibility. Do not copy giant images again if verified immutable artifacts already exist; reconcile current manifests and receipts first.

## 7. Validate the complete runtime and fabric

Run platform-appropriate GPU/power/storage/service checks. Review upstream system-info collection before execution because it can include environment configuration. Its nonfatal warnings require interpretation.

Use a small container/PMIx canary, then a two-node communication test, then a full selected-cohort test. Determine the supported test tools from the pinned source/platform. Verify every intended rank and full expected fabric/provider inventory. Establish actual reachable rendezvous address/interface and confirm the generated container process receives intended transport variables.

Retain UTC timestamps, command/config identity without secrets, rank/node count, all relevant logs and return statuses. A reduced rail subset or unexpected socket fallback cannot approve a full-bandwidth RDMA run. Freshness must reflect the platform's health policy and revalidation after boot/configuration/cohort changes. Do not manufacture readiness from a stale report.

## 8. Preview the requested recipe

Run from the installation directory with explicit tuple variables:

```bash
cd "$LLMB_INSTALL"
llmb-run submit --help
llmb-run submit -w "$WORKLOAD" -s "$MODEL_SIZE" \
  --dtype "$DTYPE" --scale "$GPU_SCALE" --dry-run
```

Review generated scheduler flags, node/rank/GPU allocation, supported parallelism, account/partition/QoS, image, mounts, cache, model/precision and environment. Inspect offline flags inside the actual container if applicable. Treat any credential value in generated files as a publication/delivery defect.

Do not use a fixed qualification suite command for an arbitrary diagnostic scale. Inspect the pinned `exemplar` command and qualification metadata separately. Required suite size and baseline depend on the chosen release and platform.

## 9. Submit and stage safely

When execution is in scope, gates pass, no competing campaign exists and the preview matches, submit through the official CLI using its supported options. For node-local experiments, use a verified generation/held-job workflow discovered through CLI help. Record the scheduler-returned ID, current node mapping and experiment paths.

Before release:

1. Inspect the actual held job and generated script.
2. Confirm intended recipient/allocation mapping and all runtime paths/mounts.
3. Stage newly generated experiment/configuration/scripts to every intended node.
4. Verify hashes from each recipient and retain receipts.
5. Recheck live health, active campaigns, cohort and intended transport.
6. Release only this verified job through the approved scheduler workflow.

If the pinned CLI cannot support safe generation/holding/staging, stop dependent launch and implement a reviewed adapter or choose proven shared storage. Do not improvise a raw batch script from an old run.

## 10. Monitor, diagnose and resume

Track scheduler state, actual completed iterations, timestamp, step duration, parsed throughput, GPU health, transport/rank evidence and first faults. Startup compilation and growing logs are not iteration completion. Preserve all per-rank files, not only merged stdout.

On restart, reconcile campaign lock/checkpoint, runner process, scheduler IDs and durable attempt records. Monitor an active job; do not resubmit it. Resolve orphaned or held jobs before advancing. When accounting is absent, collect batch exit and complete node/rank evidence before classifying terminal state.

On infrastructure, staging, integrity or evidence failures, halt affected advancement and preserve outputs. A recipe failure may receive one corrected authorized retry after diagnosis; another failure halts the campaign. Never erase failures from the ledger or bypass evidence requirements to continue.

## 11. Archive and evaluate

Collect remote logs and generated files before archive creation. Inspect pinned archive behavior:

```bash
cd "$LLMB_INSTALL"
llmb-run archive --help
```

Use the supported archive command and verify included files. Package external readiness/transport/health records separately if necessary. Record source/image/configuration hashes, complete outcomes, scoring window and units. Scan for secrets and sensitive inventory before sharing. Upload only to the authorized destination, verify readback and preserve retention metadata.

A diagnostic establishes evidence at its supported tuple. Qualification additionally requires the official suite/scale, matching baseline/scoring and applicable NVIDIA review. Report these separately. Finish with a private checkpoint and a concise next-agent handoff, including blockers and exact safe resume action.
