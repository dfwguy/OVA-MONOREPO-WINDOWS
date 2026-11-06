# NVIDIA Exemplar recipe kit — deployment agent handoff

## What it does and where it runs

This repository is a documented deployment/preparation kit for official NVIDIA Exemplar Performance. It provides agent phases, input validation, manifest/verification tools, execution and acceptance runbooks. It does **not** bundle the official workload implementation, GPU containers, model metadata, datasets or a native Windows benchmarking application. Windows controls the preparation and SSH workflow; official workloads run on approved IREN Linux Slurm nodes with Enroot/Pyxis and GPU/fabric support.

## Operating boundary and reading order

This is a native Windows staging/control kit. The Windows VM runs PowerShell, Codex, Python for supported preparation helpers, OpenSSH and a browser. WSL, Hyper-V and Windows Docker are not prerequisites. Linux services, Bash, Slurm, Enroot and GPU/fabric work execute on an approved IREN Linux management host and selected compute nodes through Fortinet VPN. No GPU workload runs on the Windows VM.

Read this handoff, `source/AGENTS.md`, `source/README.md` and the tool-specific documents named below. The source tree is an exported, pinned source snapshot; no Git history or token is included. Keep real inventory, secret files, runtime state and validation evidence outside this kit. Obtain controller hostname, approved SSH identity and verified host key, Linux distribution/architecture/Python version, storage paths, service privileges, and exact node/partition scope before dependent operations. Use approved trust provisioning; do not disable host-key checking.

Download and verify the outer ZIP checksum, then run the common release verifier. `FILE_MANIFEST.json` records every payload file and its original Unix mode. ZIP extraction on Windows does not prove executable bits survived; after transferring/unpacking on Linux run `python3 RESTORE_MODES.py` from the kit root. It verifies every recorded payload SHA-256 before restoring file modes and follows no symlinks. Never run source shell scripts through PowerShell.

OpenSSH access from PowerShell is the supported control path. Establish a host alias in `%USERPROFILE%\.ssh\config` with the approved HostName, User, IdentityFile and host-key policy. Then use `ssh iren-controller` for remote Linux commands and `scp`/SFTP for approved artifacts. A successful Windows route is insufficient if a separate runtime is later introduced: validate routing from the process that actually opens the connection. Keep local service access on loopback; use SSH forwarding rather than opening telemetry/database ports across VPN.

## Acceptance levels

`SOURCE_PREPARED` means source and manifest are packaged and offline checks are recorded. `DEPENDENCIES_STAGED` covers only the explicitly listed dependency closure. Neither proves a service installed, VPN routing, target ABI compatibility, capture completeness or benchmark qualification. Live acceptance must retain actual command/version output and per-node evidence. Preserve failures and unknowns; do not replace them with PASS.

## Exact preparation contract

Read `source/agent_exemplar_skills.md`, `source/run_exemplar.md`, `source/docs/airgap.md` and `source/docs/acceptance.md`. The kit's `tools/prepare.py` uses the Python standard library and can be used for structural checks from Windows Python, with target Linux POSIX paths in configuration. No Windows installation/acceptance test was performed here. Native Windows mode/permission semantics do not verify Linux payload readiness; retain a final Linux manifest/verify step. Other helpers/installers are not assumed portable.

Copy `source/config/cluster.example.json` into the private deployment workspace. Fill every field: cluster alias, `network_mode=airgap`, exact upstream full commit/release, actual GPU type and CPU architecture, GPUs/node, explicit compute hosts, transport, expected HCAs, interface, scheduler account/partition/QoS/operator, storage roots/layout, credential-file references and supported workload/model/precision/GPU-scale tuples. This schema belongs to the kit and is not upstream `cluster_config.yaml`.

PowerShell structural validation (from kit root, with `py` referring to a provisioned Python):

```powershell
py -3 source/tools/prepare.py validate-config C:/IREN/private/exemplar-cluster.json
```

`INPUTS_VALID` proves structure and allocation arithmetic, not hardware support, credential availability or readiness. The kit reads no secret values for this check. Secure NGC/Enroot and HF credentials stay in restricted files on the connected download host; provide only paths and access status to the agent. Gated HF access must be accepted separately.

## Workload selection is a required gate

Resolve the official source `https://github.com/NVIDIA/exemplar-performance` at an approved immutable revision. Inspect that revision's supported GPU/CPU/scale/precision/workload matrix before downloading. Do not select recipes by customer name, hostname, generic GPU count or assuming all supported hardware is interchangeable. Choose a diagnostic canary before full-cohort qualification.

The existing runbook describes Slurm + Enroot/Pyxis. Other schedulers/platforms require a reviewed adapter. The upstream README lists broad prerequisite floors, but the pinned release and actual GPU generation determine the supported driver/CUDA/RDMA/PMIx/runtime combination. Do not install drivers, change firmware/fabric or replace scheduler infrastructure as an incidental setup action.

## Connected staging and complete offline closure

The Windows VM can store and transfer artifacts and native Codex can orchestrate SSH, but Windows cannot run Bash/Enroot conversion natively. Use an approved **connected Linux staging/conversion host** compatible with the target image architecture and runtime for operations that require Enroot, Linux package tooling or official Linux installers. This is a distinct staging dependency, not WSL or Hyper-V on Windows and not internet on IREN. If no connected Linux builder is available, obtain verified prebuilt payloads from an approved artifact pipeline. Do not run a network downloader on the offline IREN host expecting VPN to provide an internet route.

For each selected recipe acquire and inventory:

1. Official source plus all required LFS/submodules/helper repositories at recorded revisions, exported without Git credentials/history and without unresolved LFS pointers.
2. Exact container reference, immutable registry digest, target platform and entitlement; convert/import into the actual `.sqsh` format on the approved compatible Linux host. Record local artifact SHA-256 separately from registry digest. An OCI/Docker tar renamed `.sqsh` is invalid.
3. Recipe-specific HF model configuration/tokenizer and only required weights/datasets/checkpoints at pinned revisions. Preserve cache blobs/relative links or export self-contained files with reviewed path adaptation. Exclude HF token/stored-token files.
4. Full controller/workload Python closure matching target interpreter/ABI and OS/native libraries, including build-time/dynamic dependencies; materialize with the pinned release's tooling rather than inventing a universal pip recipe.
5. Approved target OS/runtime packages and integration/hooks not already provisioned: Enroot, Pyxis, Slurm/PMIx where in scope, GPU/RDMA/provider libraries and platform requirements. Keep credentials/Slurm authentication keys separate.
6. Generated target configuration, mount paths, experiment files, no-network launch controls and retained evidence layout.

The generic source installation example in upstream/runbook is version-dependent (`./install.sh -i "$IMAGE_ROOT"`). Inspect help/setup at the pinned revision; it is not a universal offline installer and must not be run on the isolated target until fetches have been eliminated or a supported manual/local adapter is prepared. There is no two-container universal bundle and no inferred upstream `--offline` switch.

No selected workload source/image/model/package closure is bundled in this kit: hardware/workload and credential inputs are still needed. This explicitly prevents labeling this ZIP a dependency-complete Exemplar installation. P2P can distribute the later verified payload after its catalog/actual-byte integrity gate passes.

## Materialize, verify, transfer

Use a versioned payload with source, images, model-cache, wheels, packages and non-secret target configuration. On compatible staging, produce and verify its manifest:

```bash
python3 tools/prepare.py manifest "$PAYLOAD_ROOT" "$PAYLOAD_MANIFEST"
python3 tools/prepare.py verify "$PAYLOAD_ROOT" "$PAYLOAD_MANIFEST"
```

The helper rejects credential-like paths, unsafe links and common small-file secret patterns but is not an exhaustive malware/license/secret scanner. Preserve internal relative symlinks and executable flags; ZIP extraction on Windows can lose them. Use an approved Linux-preserving archive format for the final runtime payload and verify again on every recipient. Install new environments at their final paths rather than assuming virtualenv relocation works.

Store large verified payloads on persistent cluster storage; confirm free space/inodes and temporary conversion/extraction overhead. The runbook's 300GB typical-install guidance is not an actual budget for an unspecified workload set. For node-local images/experiments, every intended node needs a receipt; controller visibility alone is insufficient.

## Readiness, run and evidence

Commission Collection capture before submission. Verify GPU inventory/topology/health, full fabric/provider/HCA coverage, scheduler account/partition/explicit cohort, Pyxis/Enroot startup, mounts, model configuration loading, metadata cache and no-network setup/launch. Run help/list/preview with the installed pinned CLI; command flags may change by release, so use `source/run_exemplar.md` and actual help rather than constructing speculative flags. A dry run does not exercise all lazy downloads.

Only after canary readiness and approved workload scope, submit the intended matrix, monitor all ranks and retain stdout/stderr, generated scripts/configuration, command/version records, image digests, model revisions, allocation identity, timings, failures and actual measured outputs. Do not interpret scheduler exit alone as performance qualification. Compare through the official scale/scoring/baseline review applicable to the chosen recipe.

For repeat attempts use new run IDs. Preserve prior failures and qualification status independently from diagnostic adaptations. Never silently reduce scales, disable intended fabric rails or change recipe semantics to obtain a PASS.

## Resume and rollback

Keep a private checkpoint containing pinned source/workload/image identities, architecture/ABI, approved cohort, upstream CLI version/help, credential file **paths only**, payload hashes, installed paths, readiness evidence, submitted job IDs and next action. Retain a prior verified version and result directories. Do not update payloads beneath active jobs or blindly resubmit a job after a control disconnect. Query the scheduler first and resume evidence collection. Roll back code/runtime/configuration through a recorded version selection while preserving all outputs.
