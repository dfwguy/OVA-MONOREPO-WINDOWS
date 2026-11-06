# IREN MKZ — Rack Status agent handoff

## Delivery identity and qualification

Use this kit for the exact requested project `https://gitlab-master.nvidia.com/nvis/nvis-rack-status`, main commit `337a25615c083a09f567aed3cf7e848e766b6e84`. It is not the earlier `nvis-ova/rack-status-pythoncm` fork. The exact upstream commit passed [pipeline 79123349](https://gitlab-master.nvidia.com/nvis/nvis-rack-status/-/pipelines/79123349). This kit adds an offline bootstrap option, removes cross-customer deployment notes, replaces known deployed endpoint examples with reserved addresses, and materializes exact-commit CI build outputs. See `PROVENANCE.json` and `evidence/` for the derivative changes. Upstream CI success does not certify those local packaging changes or the IREN cluster.

Status: staged source, built web assets, Linux Python runtime dependencies and optional Windows client. Not live installed or accepted. No SSH/VPN/cluster operation was performed for this delivery. Do not report deployment success until the acceptance evidence below exists.

## What this tool does

Rack Status is the operator interface and execution gateway: Flask API; React 19 dashboard; cluster/platform catalog; SSH transport; workload/audit workflows; result parsing/history; report generation; and links/queries to Observability. It can submit jobs, cancel them, power-cycle equipment and drain/resume nodes. Those actions require the approved exact IREN node/partition scope and appropriate identity policy.

The project includes P2P provisioning and catalog-driven per-cluster configuration for its existing full object-storage workflow. That built-in provisioning action has not been converted to the separately supplied minimal Dragonfly profile. Deploy basic Dragonfly using the new P2P kit's dedicated minimal-profile render/preflight/load/check scripts, then qualify any Rack-to-P2P endpoint integration separately. Avoid competing controllers and historical site defaults.

## Windows and remote placement

The Windows VM runs existing Codex in PowerShell, Fortinet VPN, OpenSSH and a browser (optionally the included desktop shell). Do not enable or require WSL, Hyper-V, Docker Desktop, a local Linux VM or a Windows port of gunicorn.

The Flask/gunicorn backend, durable `source/var/`, SSH execution gateway and web assets run on an approved **remote Linux management/application host** inside IREN. This is a backend-only install across the VPN; the browser displays the UI through a loopback SSH forward. Place workload scripts on the explicitly configured head/login/execution host. Compute nodes run jobs and collectors rather than a copy of the full dashboard.

Select Linux x86_64 or aarch64 for Rack Status itself, CPython 3.12, glibc >=2.28. P2P core server binaries bundled in the separate P2P kit are x86_64 only: choose an x86_64 management host if combining them there. The ARM64 peer binary is for Linux aarch64 with 64 KiB page size; do not infer cluster architecture from the Windows VM.

## Contents and offline closure

- `source/`: derivative source without Git history or runtime secrets. `static/spa`, `static/tracker`, `static/forecast` are prebuilt from exact-main CI job 527645238; `static/docs` is from job 527645228. Building the frontend requires Node/npm; using these assets does not.
- `offline/wheels-linux-x86_64-py312/` and `offline/wheels-linux-aarch64-py312/`: all Python runtime requirements resolved on 2026-11-05 as wheels. Keep architectures separate. These include native cryptography, Brotli, Pillow and Pydantic components, not just top-level packages.
- `scripts/prepare-linux.sh`: checks the actual Linux runtime and installs only from the local wheelhouse with `--no-index`. It starts no service and contacts no cluster.
- `windows/nvis-greenlight-setup-0.3.1-260915203005-x64.exe`: existing optional Windows x64 Electron shell, fetched from this project's versioned registry and checked against registry SHA-256 `f8f3e8c0f7773d448debfec656e2d9d99a259a47184782f02dda9259475c09a8`. Its source tag is `desktop-0.3.1`, commit `0de2aa5b63612c916706db9becba543ef7912647`. The shell loads the remote SPA; it is not a backend and need not match the backend version. It was not executed here. Upstream describes the Windows installer as unsigned; signature verification is not claimed. A browser is sufficient.

Not included: a Linux OS or CPython installation; OS packages such as `openssh-client`, `rsync`, `bash`, `coreutils`, `util-linux`; Docker/Compose; cluster-side Slurm/BCM/MAAS tools; NGC/HF credentials; benchmark workload images; cluster inventory; Fortinet installer/configuration. Provision OS prerequisites before disconnecting the target from external repositories, or stage packages for its exact distro. This wheelhouse does not close the OS prerequisite gap.

## Required deployment input

Read the overall IREN handoff and approved configuration before opening a connection. Obtain the management SSH alias/user/key/verified host fingerprint; the backend install directory and service account; the controller/execution endpoint and known-hosts file; BCM/MAAS and Slurm/PythonCM choice; cluster root, exact node list/partition and workload limits; cluster name/naming convention; persistent storage budget; telemetry endpoint; authentication/TLS policy; and approved workload-image catalog. Keep secret values in private files outside the shared ZIP. Templates/reserved addresses are never targets.

After first startup, the Project/Cluster record becomes authoritative and outranks instance environment variables. Put `connection.root`, per-host roles, script/log/workspace paths, scheduler and naming there. Validate `/api/cluster-paths` and Projects & Clusters before any workflow. The settings file is bootstrap configuration, not a permanent alternate target registry.

## Install sequence

1. On Windows, verify the outer ZIP SHA-256 against the release manifest and the extracted file manifest. Keep an immutable staging copy. Copy only this kit and separately selected dependencies through the approved VPN route with Windows OpenSSH/SFTP. Use the management host's verified host key, never `StrictHostKeyChecking=no`.
2. On the Linux host, extract using a mode-preserving ZIP reader or restore executable bits using `FILE_MANIFEST.json`. Use an isolated reviewed directory, e.g. `/srv/iren-mkz/rack-status`; do not overwrite an existing service. Record existing listeners/services and back up previous config/state first.
3. Run `bash scripts/prepare-linux.sh --check`. CPython 3.12 and its `venv`/`pip` support must already exist. Then run `bash scripts/prepare-linux.sh --install`. It uses only the local wheelhouse. Keep `pip check` output as evidence.
4. In `source/`, generate configuration through the existing CLI (the flags only set existing settings):

   ```bash
   .venv/bin/python backend/cli.py init-config --ssh-host "$IREN_CONTROLLER_HOST"
   ```

   Add the reviewed `RACK_SSH_USER`, `RACK_SSH_KEY` and **`RACK_SSH_KNOWN_HOSTS`** file path using `config/rackstatus.toml.example` sections. The upstream SSH transport does not verify host keys unless a known-hosts file is configured; configure it before use. Seed host keys from an independently verified source rather than trusting an unverified `ssh-keyscan` result. Configure `RACK_STATUS_DEMO=0` explicitly for production. Generate/provision a TLS certificate including `localhost`; preserve `var/secrets/` privately.
5. Check first-start readiness without starting listeners:

   ```bash
   RACK_STATUS_DEMO=0 .venv/bin/python backend/cli.py check --json
   ```

   This may seed the catalog but creates no admin/password/policy. Missing cluster settings are faults. A fresh identity/TLS bootstrap is expected on first `serve`; review the JSON rather than calling every exit 78 a failure or suppressing faults.
6. Start in a foreground canary session, **bound to loopback**, using the supported startup path with offline dependency mode:

   ```bash
   export NVIS_OFFLINE_WHEELHOUSE="$(cd ../offline/wheels-linux-x86_64-py312 && pwd)"
   # On aarch64 use wheels-linux-aarch64-py312 instead.
   export BUILD_FRONTEND=0 RACK_STATUS_DEMO=0 RACK_WEB_BIND_ADDR=127.0.0.1 PORT=5050
   ./start.sh
   ```

   First start bootstraps an admin, authorization policy and TLS if absent. The one-time password appears in the local protected log; rotate it on first login and do not copy it into release evidence. Keep the backend service account and private SSH key narrowly scoped.
7. From Windows PowerShell, forward the remote loopback listener:

   ```powershell
   ssh.exe -N -T -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=yes -L 127.0.0.1:5050:127.0.0.1:5050 iren-management
   ```

   Open `https://localhost:5050`. Independently verify the certificate fingerprint/CA before accepting it. Keep SSH running. The optional Electron shell can manage this same alias/port and pin the certificate, but does not configure Fortinet or deploy the server.
8. Complete Projects & Clusters with IREN-only identity, connection root, scheduler, platform and exact inventory. Register read-only telemetry first. Use the UI setup wizard's script deployment or the repository's `bin/deploy-scripts.sh --dry-run` and approved real deployment. The script tree is the source of truth; avoid hand copying a subset of scripts. The backend→head connection originates in IREN, not Windows. Host/user/key paths in the catalog must be Linux paths on the backend.
9. After local canary health and operator configuration review, install a systemd unit on the management host using the same environment/WorkingDirectory and `ExecStart=<kit>/source/start.sh`. Use the dedicated service account; persist the entire `source/var/` directory; set restart policy and private log permissions; preserve `config/` and `.venv/`. Do not enable it before first-start acceptance. No ready-made service with guessed UID/path is installed by this kit.

## P2P integration: separate deployment and integration gates

### Basic Dragonfly deployment

Revision 02 supplies a separate minimal P2P kit. After extracting `nvis-p2p.zip`, use `nvis-p2p/agent_handoff.md` and its dedicated `scripts/load-images.py`, `scripts/render-minimal.py`, `scripts/preflight-minimal.py` and `scripts/check-console.py` entry points for the public PostgreSQL 16/Redis/Manager/scheduler/seed/peer deployment. The native Dragonfly console is served through its nginx HTTPS listener, default remote loopback port 4301. Windows opens an SSH forward and browses `https://localhost:4301` after verifying/trusting the generated localhost certificate as documented. A fresh minimal deployment has bootstrap UI login `root` / `dragonfly`; change it after the first authenticated login. No MinIO, NGC credential, protected model or GPU workload image is required for that basic deployment or a synthetic-file seed/peer test.

**Do not launch Rack Status's built-in P2P provision/reconcile action to install this minimal profile.** Its `nvis-p2p-provision` workflow and `source/deploy/p2p/` renderer still describe the older full object-storage layout with its own exact PostgreSQL/MinIO image requirements. Installing the new minimal kit does not rewrite that workflow or switch its deployment mode. Standalone Rack Status installation and standalone minimal Dragonfly acceptance remain independent.

### Register and check selected integration separately

After both services pass their standalone acceptance, record the actual P2P management host, HTTPS console URL, service roles, paths and approved identity references in the site plan. Configure only the endpoint/catalog fields supported by the selected Rack integration, using the real rendered minimal deployment rather than the old full-stack defaults. Do not assume a `console_bind` or object-store field from the old provisioning schema represents the new HTTPS console. Do not invent a schema field or enable provisioning merely to register an endpoint.

Check each selected Rack-to-P2P contract independently: backend-to-management reachability, certificate/authentication handling, supported read-only status/catalog calls, identity/path mapping and attribution to the intended cluster. A working native Dragonfly console does not establish that Rack's legacy NVIS operations, dfstore/catalog automation or fleet rollout endpoints are available in the minimal profile. Where the minimal kit does not implement an expected legacy endpoint, record the integration as unsupported or pending; do not mark the full P2P integration ready. Do not run provisioning, import/export or rollout actions as a connectivity probe.

### Optional advanced provisioning

The old full dfstore/MinIO path remains available only as a separate, explicitly selected advanced workflow. Read the new P2P kit's `optional/full-stack-agent_handoff.md` for its independent dependencies and limitations. Its missing exact image pins, object-store TLS/endpoints, import-versus-read-only credential separation and selected workload integrity requirements remain gates for that path; they are not blockers for the replacement minimal core.

**Do not run Rack's `source/deploy/p2p/bin/stage-artifacts.sh` against the revised minimal P2P `source/dist` directory.** Rack's unchanged `source/deploy/p2p/artifacts.lock` pins the original Manager binary; revision 02 deliberately ships the auth-fixed derivative `v2.5.1-iren-authfix.1` with a different recorded SHA-256. The lock mismatch is expected and must not be resolved by restoring the original buggy Manager, bypassing verification, or letting the old provision/reconcile action overwrite the working minimal core.

The binary staging helper only verifies/copies lock-listed files; it neither selects the minimal profile nor establishes runtime integration. Any future Rack provisioning update must explicitly carry the auth-fixed Manager's digest and compatibility evidence, reconcile the selected deployment profile and qualify the complete workflow. The existing Rack UI workflow also omits separate Manager/seed unit startup and produces an incorrect default object API endpoint for the previously reviewed advanced deployment. Keep advanced provisioning held until its independent image, lock, workflow, object-store and integration gates are resolved. Minimal-core acceptance does not close them.

## Network and acceptance

Windows→IREN requires the approved management SSH port over Fortinet. The SSH forward carries dashboard HTTPS to the remote loopback port. Backend→head requires trusted SSH; controller→compute requires the site's existing scheduler/fanout routes. Telemetry queries are backend→Observability. Do not expose `5050` to all interfaces to bypass a tunnel failure, and do not assume VPN reachability means compute nodes can call back to Windows.

Verify: Python dependency closure; no outbound dependency lookup during startup; actual TLS/authenticated login; every SPA asset (including compressed headers) resolves; backend routes/imports; expected IREN catalog only; trusted SSH host-key behavior; read-only inventory agrees with approved roster; fresh metrics; correct per-cluster paths and script deployment; durable history/admin/certificate across restart. Only then run one approved canary workflow and inspect attributed logs/results before broader tests. Do not run the fixed 256-node NeMo recipe merely because it is catalogued.

For rollback, preserve previous source/dependencies, protected config and a consistent backup of `var/`. Stop the newly created service, restore prior code/config/state as a coordinated version, retain collected evidence. Never delete shared cluster workload images, users or Slurm state as an application rollback.

See `evidence/VALIDATION.json` for actual checks performed on this kit; any skipped check remains a live acceptance requirement.


## Sanitized monorepo derivative (2026-11-06)

This copy removes generated OIDC private key, web secret, key index, runtime log and lock state from the original packaged delivery. New installations generate fresh runtime identity and state. The upstream source commit is unchanged; artifact bytes and checksums differ. See the monorepo evidence/sanitization-removals.json.
