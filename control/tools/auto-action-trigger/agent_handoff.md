# Auto Action Trigger — deployment agent handoff

## What it does and where it runs

This framework uses Bash, systemd **user** timers, Slurm queries, node health checks, image caching, benchmark sequencing, optional burn-in, parser verdicts and fleet reporting. Its head-node watchdog and node agents must run inside the Linux cluster management boundary. It has no native Windows daemon or UI. Windows stores the kit and evidence copies and controls approved remote commands. All node fan-out originates on the Linux head node using this framework's `fanout.sh`/ClusterShell or `pdsh` abstraction.

## Operating boundary and reading order

This is a native Windows staging/control kit. The Windows VM runs PowerShell, Codex, Python for supported preparation helpers, OpenSSH and a browser. WSL, Hyper-V and Windows Docker are not prerequisites. Linux services, Bash, Slurm, Enroot and GPU/fabric work execute on an approved IREN Linux management host and selected compute nodes through Fortinet VPN. No GPU workload runs on the Windows VM.

Read this handoff, `source/AGENTS.md`, `source/README.md` and the tool-specific documents named below. The source tree is an exported, pinned source snapshot; no Git history or token is included. Keep real inventory, secret files, runtime state and validation evidence outside this kit. Obtain controller hostname, approved SSH identity and verified host key, Linux distribution/architecture/Python version, storage paths, service privileges, and exact node/partition scope before dependent operations. Use approved trust provisioning; do not disable host-key checking.

Download and verify the outer ZIP checksum, then run the common release verifier. `FILE_MANIFEST.json` records every payload file and its original Unix mode. ZIP extraction on Windows does not prove executable bits survived; after transferring/unpacking on Linux run `python3 RESTORE_MODES.py` from the kit root. It verifies every recorded payload SHA-256 before restoring file modes and follows no symlinks. Never run source shell scripts through PowerShell.

OpenSSH access from PowerShell is the supported control path. Establish a host alias in `%USERPROFILE%\.ssh\config` with the approved HostName, User, IdentityFile and host-key policy. Then use `ssh iren-controller` for remote Linux commands and `scp`/SFTP for approved artifacts. A successful Windows route is insufficient if a separate runtime is later introduced: validate routing from the process that actually opens the connection. Keep local service access on loopback; use SSH forwarding rather than opening telemetry/database ports across VPN.

## Acceptance levels

`SOURCE_PREPARED` means source and manifest are packaged and offline checks are recorded. `DEPENDENCIES_STAGED` covers only the explicitly listed dependency closure. Neither proves a service installed, VPN routing, target ABI compatibility, capture completeness or benchmark qualification. Live acceptance must retain actual command/version output and per-node evidence. Preserve failures and unknowns; do not replace them with PASS.

## Required review and platform selection

Read `source/docs/tutorials/first-bringup.md`, `source/docs/how-to/update-the-deployment.md`, `source/docs/reference/settings.md`, `source/docs/reference/jobs.md`, `source/docs/explanation/running-unprivileged.md` and `source/docs/explanation/containers.md`.

Shipped job sets are `nvl72`, `nvl72-spx`, `b300`, `b300-spx`, and `h200x2`; health sets currently ship under `health-checks/nvl72`, and parser sets under `parsers/nvl72` and `parsers/spectrum-x`. These directory names are platform selectors, not evidence of compatibility with IREN. Confirm supported GPU topology, CPU architecture, fabric, job launchers, image names and parser thresholds before choosing `JOBS`, `HEALTHCHECKS`, `PARSERS` or `BENCHMARKS`. Floors and LLM step-time ceilings are inherited hardware-specific reference values and need reviewed baseline policy. The `cmods` default account and `/cluster/bringup*` paths are conventions requiring explicit target decisions.

The Linux side requires Bash, GNU coreutils/awk/find/diff, systemd user sessions, persistent approved storage, Slurm CLI/access, rsync, and ClusterShell (`clush`/`clubak`) or `pdsh -R ssh` with grouping tooling. GPU health commands and privileged diagnostics depend on the selected check set. Enroot/Pyxis, NVIDIA GPU/RDMA stack and SquashFS images must already be approved and compatible. Sudo rules remain site-owned; `source/agent/sudoers.default` is a review reference, not an instruction to grant broad privilege. SSH trust and fan-out reachability to selected nodes are needed from the head node. Do not mount the Windows drive as live shared `$BRINGUP_HOME`.

## Safe staging and initial configuration

`configuration/SETTINGS.commissioning-paused` is deliberately inert: jobs, health checks, image copy, recovery, arming and burn-in are off, and the node filter matches no intended host. The upstream defaults enable several of these operations, including recovery capable of clearing Slurm drains and restarting slurmd. Never arm directly from defaults.

1. Verify the package on Windows, transfer the ZIP plus checksum to a fresh, local-disk staging directory on the approved Linux management host, unpack and run `RESTORE_MODES.py`.
2. Inventory existing agents and active jobs. For an update, stop the watchdog first and pause existing node agents with the existing deployment's documented `admin_pause-agents.sh`; do not overwrite running source.
3. Copy the reviewed source with `rsync -av` into the explicit deployment root. Do **not** use `--delete`; preserve `SETTINGS`, `SETTINGS_HOME`, results, logs, baselines, containers and site state.
4. For a new deployment, create the private settings file from the paused profile. Do not overwrite an existing site settings file. Set `JOB_USER`, `$BRINGUP_HOME`, `$BRINGUP_DATA`, exact `NODE_FILTER`, exclusions, directories and supported hardware sets. Configure the source `SETTINGS_HOME` pointer to that existing private file (one absolute path per file); review resolution in `source/settings.sh` and `source/docs/reference/settings.md`.
5. As the approved job user, inspect resolved settings and paths before any timer installation. No default all-node scope is acceptable for commissioning. Preserve the paused switches during transfer/preflight.

Remote Linux inspection example (operator sets `DEPLOY_ROOT` to the reviewed target path):

```bash
cd "$DEPLOY_ROOT"
bash -n settings.sh agent/install-agent.sh actions/node_health.sh actions/launch_job.sh
bash check_trigger-debug.sh
```

Offline regression can be rerun on a Linux test host with `bash tests/<name>-test.sh`; these suites stub cluster commands. They do not verify target privileges or systemd startup. The delivered tests and fixtures retain structural semantics while old site hostname prefixes and private IPv4 examples have been replaced consistently. No live `SETTINGS`, output directories or health baseline are shipped.

## Containers and no-internet installation

No benchmark containers, Enroot/Pyxis packages or OS dependency closure are bundled. Resolve the image list from the reviewed job set and selected benchmark list. Upstream `build_containers.sh` supports explicit image names and architecture; read its installed `--help` and `docs/explanation/containers.md` on a connected compatible Linux staging system. It may authenticate to NGC and build/import images, so do not execute it on the offline controller expecting downloads to work. `-L` writes an Enroot credential file: keep that file on secure staging, outside the payload.

Produce a filename/architecture/source-digest/local-SHA256/size manifest for every `.sqsh`. Registry digests and SquashFS file hashes are different identifiers. Transfer verified images to the intended `CONTAINER_DIR`; use node-local caching only within scoped nodes. Prior P2P catalog/receipt disagreements must be resolved by hashing actual payload bytes before those objects can be used. The Windows CPU architecture does not select the compute image architecture.

## Commissioning and deliberate activation

Before any arming, satisfy the source documentation's NFS lease checks, sudo diagnostic rules, shared unit behavior, storage/performance and user-session/lingering prerequisites. An approved initial canary scope and accepted baseline are required. If configuring service units, `install-agent.sh` must run **as JOB_USER**, not root. It enables lingering, writes user units and starts a timer; it is an active operation, not a dry run. `--head` and `--node` affect that install invocation's role reporting; runtime role detection remains in `cycle.sh`.

When approved for a canary, enable only required actions in private settings and arm via the documented procedure. Examples of bounded node preflight use either tool:

```bash
clush -w "$APPROVED_NODESET" 'sudo -n dmesg >/dev/null 2>&1 && echo sudo-ok || echo sudo-REFUSED'
pdsh -R ssh -w "$APPROVED_NODESET" 'sudo -n dmesg >/dev/null 2>&1 && echo sudo-ok || echo sudo-REFUSED'
```

Capture a baseline only from a known validated node using `admin_set-baseline.sh`; never use a symlink to current live health output as the reference. Check timer enabled/active status, advancing per-node heartbeat timestamps, watchdog trace, exact allowed cohort and first health/benchmark results. Register validation artifacts with Collection before any benchmark submission; Auto Trigger does not automatically provide universal Collection integration. The collector's runner-manifest hook needs a reviewed adapter for the actual launch path.

Keep drain/recovery controls off until observed findings and scope are accepted. Report parser verdict inputs, skipped probes, sudo refusals and missing tests as gaps. No performance qualification follows from a healthy timer.

## Update, recovery and rollback

Read `source/docs/how-to/pause-and-resume.md`. Pause watchdog before nodes; verify quiet state, copy with `rsync -av`, check unit contents and resume with `admin_pause-agents.sh --resume` so changed units are reinstalled. Preserve state and prior reviewed source. Recovery should restore code/settings while retaining results and baselines; do not purge jobs/results or resume arbitrary operator drains as cleanup. Record source manifest hash, configuration hash, installed modes, timer units, scope, images and actual run evidence in the private checkpoint.
