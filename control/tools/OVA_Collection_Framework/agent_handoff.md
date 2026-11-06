# OVA Collection Framework — deployment agent handoff

## What it does and where it runs

A Slurm evidence collector captures durable scheduler completion/accounting metadata and allowlisted validation artifacts, retains raw bytes and SQLite checkpoints, publishes Parquet/search views and provides an authenticated browser. It does not run GPU validation by itself. Deploy its backend and browser on an approved Linux management/collector host near the Slurm sources. Open the browser from Windows through an SSH tunnel across Fortinet; retain authoritative state on persistent Linux storage. SQLite WAL must not live on NFS or a Windows share.

## Operating boundary and reading order

This is a native Windows staging/control kit. The Windows VM runs PowerShell, Codex, Python for supported preparation helpers, OpenSSH and a browser. WSL, Hyper-V and Windows Docker are not prerequisites. Linux services, Bash, Slurm, Enroot and GPU/fabric work execute on an approved IREN Linux management host and selected compute nodes through Fortinet VPN. No GPU workload runs on the Windows VM.

Read this handoff, `source/AGENTS.md`, `source/README.md` and the tool-specific documents named below. The source tree is an exported, pinned source snapshot; no Git history or token is included. Keep real inventory, secret files, runtime state and validation evidence outside this kit. Obtain controller hostname, approved SSH identity and verified host key, Linux distribution/architecture/Python version, storage paths, service privileges, and exact node/partition scope before dependent operations. Use approved trust provisioning; do not disable host-key checking.

Download and verify the outer ZIP checksum, then run the common release verifier. `FILE_MANIFEST.json` records every payload file and its original Unix mode. ZIP extraction on Windows does not prove executable bits survived; after transferring/unpacking on Linux run `python3 RESTORE_MODES.py` from the kit root. It verifies every recorded payload SHA-256 before restoring file modes and follows no symlinks. Never run source shell scripts through PowerShell.

OpenSSH access from PowerShell is the supported control path. Establish a host alias in `%USERPROFILE%\.ssh\config` with the approved HostName, User, IdentityFile and host-key policy. Then use `ssh iren-controller` for remote Linux commands and `scp`/SFTP for approved artifacts. A successful Windows route is insufficient if a separate runtime is later introduced: validate routing from the process that actually opens the connection. Keep local service access on loopback; use SSH forwarding rather than opening telemetry/database ports across VPN.

## Acceptance levels

`SOURCE_PREPARED` means source and manifest are packaged and offline checks are recorded. `DEPENDENCIES_STAGED` covers only the explicitly listed dependency closure. Neither proves a service installed, VPN routing, target ABI compatibility, capture completeness or benchmark qualification. Live acceptance must retain actual command/version output and per-node evidence. Preserve failures and unknowns; do not replace them with PASS.

## Software and offline payload supplied

Read `source/AGENT_HANDOFF.md`, `source/docs/deployment.md`, `source/docs/hooks.md`, `source/docs/operations.md`, `source/docs/acceptance.md` and `source/docs/handover.md`.

The installer requires Linux Python 3.12+, `python3-venv` including pip, systemd and `systemd-analyze`, GNU `findmnt`, user/group management, `runuser`, OpenSSH and the configured Slurm CLI. **Even `tools/deploy.py plan` is Linux-only** because it imports `fcntl`, `pwd` and `grp` at startup. Do not run it natively in Windows Python. Do not copy a prebuilt virtual environment from staging to another path/OS.

`dependencies/collection-cp312-linux-x86_64` and `dependencies/collection-cp312-linux-aarch64` each contain the 10 exact pinned wheels from `source/app/requirements.lock`. Wheel filenames retain platform/ABI tags; CPython 3.12 and a compatible manylinux/glibc Linux distribution are required for the native dependencies. Select one directory matching the **collector host**, not Windows. The set includes pyarrow and duckdb native binaries. Wheels are staged and hashed, not target-installed or a target-validated OS closure. Python, ensurepip/venv, Slurm, SSH and system packages remain target prerequisites. A different Python ABI, musl-based OS or unsupported glibc requires a newly resolved closure.

The wheel hash manifests establish byte identity, not vulnerability or license approval. Rerun policy-required dependency review against the exact delivered wheels and live target. Do not add unrelated packages to the offline installer command.

## Configuration and capture contract

Use `source/examples/cluster.example.json` as a schema/checklist and write the filled configuration outside the source tree, normally `/etc/ova-collection/cluster.json`. Replace example site/cluster identity; `root` must follow `/var/lib/slurm-evidence/<cluster>/<epoch>`. Choose a durable epoch and never reset job IDs to avoid gaps. Fill actual Slurm binary/service names, retained controller/completion feeds, allowlisted local roots, service user/group, browser token path and collection budgets.

The default `remote_capture_enabled=false` captures collector-readable local/shared artifacts. Enable remote node capture only if node-local logs require it and the dedicated read-only SSH identity, known-host entries and exact approved roots exist. The collector does not disable SSH trust verification. Retention must exceed worst outage + revisit time + export margin. Confirm source read/search ACLs as the service account and preserve existing Slurm hooks/plugins. `JobCompType=jobcomp/filetxt` supplies completion metadata; it does not capture arbitrary stdout or configurations.

## Plan and fresh installation on remote Linux

Create a fresh, empty output directory for each plan/apply invocation. Commands below execute on the Linux collector after source extraction/mode verification, from this kit's `source` directory:

```bash
python3 tools/deploy.py plan --config /etc/ova-collection/cluster.json --output /var/tmp/ova-plan
# Review deployment-plan.json, rendered source, service account, paths and units.
sudo python3 tools/deploy.py apply --config /etc/ova-collection/cluster.json --output /var/tmp/ova-install   --wheelhouse /absolute/path/to/kit/dependencies/collection-cp312-linux-ARCH
```

Replace `ARCH` with the matching delivered directory (`x86_64` or `aarch64`). Run under the intended supported Python interpreter; check `python3 --version` first. `apply` creates a non-root collector account, source/dependency installation, secure token, systemd services/timers/watchdog and initial passes. The installer rejects tmpfs/ramfs/overlay state and refuses an existing app or checkpoint. A failed partial install remains for diagnosis; do not delete evidence and rerun blindly.

Default `apply` does **not** change Slurm completion configuration. If no existing retained terminal feed/accounting satisfies capture, adapt to it before launch. The explicit `--configure-jobcomp /path/to/slurm.conf --slurm-user <actual-user>` option changes scheduler config and invokes `scontrol reconfigure`; use only under that approved operational scope after reviewing HA, included configuration and current plugins. This package does not authorize replacing existing plugins or scheduler configuration.

## Windows browser access

Use OpenSSH local forwarding from PowerShell (assuming the configured SSH alias and default configured browser port):

```powershell
ssh -N -L 127.0.0.1:4310:127.0.0.1:4310 iren-controller
```

Then open `http://127.0.0.1:4310/login` in the Windows browser and retrieve the generated token through the approved secure channel. Do not print it in a handoff or transcript. Confirm actual port/URL/token path from the deployment receipt. This is authenticated shared cluster access; team SSO/TLS uses the repository's proxy fragment and secure cookie setting. Do not expose an unauthenticated listener on the VPN or public NIC.

## Integrate before validation job 1

The upstream `tools/submit.py` wrapper archives a scalar script, manages `%j` stdout/stderr, submits with `sbatch --parsable` and registers a trusted manifest. Example, remote Linux only and only for an approved run:

```bash
python3 tools/submit.py --config /etc/ova-collection/cluster.json   --run-dir /srv/validation/results/UNIQUE_RUN --script /absolute/path/validation.sbatch   -- --partition=APPROVED_PARTITION
```

Each attempt needs a new directory. Replace placeholders before execution. If submission succeeds but registration fails, the job still exists: preserve the reported manifest and register it, rather than submitting again. `tools/write_job_manifest.py` is available for existing runners. Rack Status, Auto Trigger and Exemplar need their actual runner lifecycle adapted to this contract; shipping the tools together does not create that integration.

Support is bounded: scalar IDs, allowlisted paths, source limits and retained feeds. Arrays, heterogeneous jobs and federation require adapters. Large/continuously changing node-local files can exceed snapshot budgets; retain them durably and implement/rehearse an appropriate append/archive adapter instead of silently asserting complete capture.

## Acceptance, export and rollback

Check exact installed unit names in `deployment-plan.json`, enabled/active state and advancing metadata/live/publication/search freshness. Reconcile short success, failure and cancellation jobs against independent Slurm terminal/accounting records. Verify captured bytes, per-rank outputs, gap reporting, source outage replay and recovery. Browser availability or enabled timers are insufficient. The installer reports `INSTALLED_REQUIRES_COMMISSIONING` until these gates pass; no actual reboot test was performed during packaging.

Follow `source/docs/handover.md` for export and reconstruction verification. An external validation hub needs its own approved ingestion schema/access. Preserve checkpoint plus referenced raw/Parquet payloads, cluster/epoch identity, configs and unit/dependency hashes. Stop watchdog first during upgrades, then timers/browser; back up state, swap reviewed code/dependencies and verify recovery before re-enabling. Never remove the evidence lake to reset installation.

## Measured offline runtime validation

The supplied x86_64 wheelhouse was installed in a fresh CPython 3.12 Debian bookworm container with Podman `--network none`, using `pip --no-index`. `pip check`, native Flask/DuckDB/PyArrow/Waitress imports and all six framework unit tests passed. See `OFFLINE_RUNTIME_VALIDATION.json` and `offline-runtime-validation.log`. This validates that interpreter/platform dependency closure in the test container, not target systemd deployment, Windows execution or IREN live acceptance. The ARM64 wheelhouse remains downloaded/hash-verified and has not been executed. The separate 22-check portable suite passed on the Linux preparation host with systemd-analyze; no equivalence to a real collector reboot is claimed.
