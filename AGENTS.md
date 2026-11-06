# Working on OVA Monorepo Windows

Read `README.md`, `VALIDATION.md`, the operator guide, and the selected `windows/` profile before deployment or code changes. The current target is a native Windows management VM with no WSL, local Linux VM or Linux container engine. Original documents under `control/` and original component handoffs describe historical Linux-backend staging; they do not override the native profile architecture.

## Source and runtime boundaries

- `control/` and component source manifests identify pinned baselines. Change them only through a reviewed revision that rebuilds affected manifests/archives and records provenance.
- Preserve `windows/rack-p2p/adapters/` as the immutable, sanitized VM export. Make reviewed adjustments through deterministic build transformations and separate patches; never overwrite a live source tree.
- Use the original Rack connection, catalog, workflow and scheduler owners. Do not add a parallel runner or bypass the explicit PythonCM workflow guard. Inventory, ProgramRunner execution and Slurm resource allocation require distinct evidence.
- Native Auto Action calls the upstream `fanout.sh` and launcher on one explicit approved node. Its task definition is disabled by default. Do not enable jobs, drain recovery, fleet discovery or remediation without concrete site scope.
- Exemplar preparation checks do not certify official recipe support or GPU execution. Keep actual supported workloads, immutable image/model identities and node/partition/GPU/time scope explicit.
- P2P's Windows profile is its console/proxy; the Dragonfly management core remains Linux-hosted. Keep that exception visible.

## Private state and deployment

Keep site configuration, inventory, logs, credentials, keys, runtime databases, generated certificates and evidence containing customer details outside Git. Use secure file references rather than credential values in chat or command arguments. Fresh builds must not copy baseline or existing deployment secret directories.

Inspect existing services, source drift and active jobs before any deployment. Use fresh versioned runtimes, preserve state and backups, and qualify isolated acceptance before commissioning. Do not replace working services or reinterpret an interrupted SSH request as proof that no remote work exists.

Use approved VPN instructions and trusted SSH aliases. Never disable host-key checking or accept a changed/unknown fingerprint merely to make a probe pass. Obtain concrete operator input when VPN authentication, MFA or authoritative trust information is missing.

## Validation and publication

Retain exact source/dependency hashes and actual receipts. Distinguish local preparation, Windows CI, isolated native runtime checks, persistent service commissioning and live customer/GPU acceptance. Keep earlier failures and their corrections. Metadata-only changes do not require repeating unchanged runtime tests; bind accepted file bytes to the published source.

Run relevant profile tests for functional changes, PowerShell parsing and supported Python syntax checks. Build the offline ZIP with `tools/build_windows_release.py`, verify its embedded manifest, and publish its checksum/provenance alongside the artifact. Keep upstream NVIDIA headers and vendor provenance intact.

The authoritative current status is `VALIDATION.md` and its linked receipts. Branding and architecture visuals must describe that status accurately. Do not turn an isolated test result into an all-features or production acceptance claim.
