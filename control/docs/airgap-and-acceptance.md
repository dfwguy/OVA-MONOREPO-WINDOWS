# Dependency closure, offline installation and acceptance

## Two disconnected concerns

The Windows VM can use NVIDIA network access for staging. IREN Linux hosts must be treated as having no internet. VPN reachability is not internet access for those hosts. Do not rely on remote `apt`, `dnf`, `pip`, `npm`, `docker pull`, browser/CDN assets or model downloads during deployment.

Revision 02 is a smaller control/toolkit ZIP plus separately selected Observability dependency packs. The control ZIP includes all six toolkits and the Observability source, but excludes the two large Observability platform packs. Fetch the matching external pack from the exact path/hash recorded in `RELEASE_INVENTORY.json` and `artifact-index.md` before a fresh offline Observability installation. An extracted control tree without that compatible pack is not a complete Observability offline installer.

Each tool directory records exactly what is included and what remains external for each deployment mode. The minimal Dragonfly core/console is the default P2P path; the advanced dfstore/MinIO stack and selected NVIDIA workloads are separate choices. Source ZIP integrity, successful offline tests, dependency downloads and a live accepted deployment are distinct evidence. A ZIP is not automatically a complete OS installer.

## Determine the target before selecting payloads

Read-only SSH inventory must establish management OS release, CPU architecture, glibc, Python interpreter ABI, systemd, storage, scheduler environment, GPU architecture, container runtime and driver/CUDA support. `x86_64/amd64` and `aarch64/arm64` are different payload sets. A CPython 3.12 manylinux wheelhouse does not provide Python, OS shared libraries or support for musl/Alpine. ARM64 64K-page client binaries are not generic ARM64 binaries.

Use an **architecture- and OS-matched connected Linux builder**, available through approved NVIDIA infrastructure, when dependencies cannot be prepared by native Windows. No Linux builder is included inside the Windows VM. Prefer the staged dependency sets where compatible. The future agent may orchestrate an available builder over SSH; its location and authorization are target inputs, not an invented service.

## Offline installation rules

1. Verify the control ZIP checksum and the extracted `FILE_MANIFEST.json` before installing. Keep downloaded external dependency packs and all extracted tool/payload directories outside the strictly verified control tree. Verify the external pack's archive SHA against the recorded remote inventory, then verify its internal payload manifest. Verify tool-level manifests after unpacking and preserve modes on Linux using `scripts/unpack_toolkit.py`.
2. Match the staged wheelhouse to remote architecture and Python version. Create a remote venv. Install with `python -m pip install --no-index --find-links <wheelhouse> -r <tool-requirements>` or the exact hashed lock command given by that tool. Run `pip check`. A resolver download on the build host is not evidence of target execution.
3. Copy prebuilt frontend assets when supplied. A Node/npm lock file alone does not provide an offline npm cache. If a frontend must be rebuilt, prepare it on a matched connected builder and transfer its final static assets; verify assets contain no external runtime CDN references required by the UI.
4. For container services, select the correct platform archive, verify SHA-256, transfer it, then use `docker load -i <archive>` or the documented compatible runtime operation. Confirm loaded image IDs/digests and render Compose config before starting. Ensure the compose references the loaded image names and has a no-pull policy. Container engine and compose plugin are separate prerequisites, not supplied merely by an OCI archive.
5. Obtain OS packages and all transitive dependencies through the site's approved OS mirror/builder for the exact target distro. Keep a separate manifest with package name, version, architecture, URL/origin, bytes and SHA-256. GPU drivers, Enroot/Pyxis, scheduler client compatibility and Python runtimes must be provisioned independently if absent.
6. Public Dragonfly core staging and deployment do not require an NGC or NVIDIA-registry credential. For a selected NVIDIA workload or protected model that actually requires NGC/Hugging Face access, stage its pinned assets on an approved connected host, transfer complete architecture-compatible image/model/tokenizer files with checksums, and keep credentials outside the bundle. Do not choose or claim a model/workload set on the user's behalf. An offline target needs no registry login for an already staged image archive.
7. Test an install with outbound internet blocked or explicit offline flags. A successful connected install is insufficient to demonstrate the airgap requirement.

## Minimal Dragonfly acceptance versus optional object storage

The minimal P2P path uses public PostgreSQL 16 and Redis with the shipped Dragonfly Manager/scheduler/seed/peer and Manager web console. Its bootstrap UI login is `root` / `dragonfly`; change that known default after first login before broadening access. Create site-specific database/JWT secrets according to the minimal kit; the UI account does not supply those identities. Windows remains the PowerShell control/staging and browser host, with Linux runtime services reached through SSH and loopback forwarding.

Accept the minimal core using Manager health/login, scheduler registration, a seed, and one approved normal peer transferring a synthetic file with a measured SHA-256. Record which hop supplied the data and whether origin fallback was disabled, as required by the test. This verifies the chosen file-distribution path, not a GPU workload or object-store import/export pipeline. The prepared bulk canary used 14,800,000 bytes and allowed only one origin metadata byte after warming; it did not establish complete origin independence. Keep the internal origin available for metadata and the client's small-file path, and restore normal origin body service after the controlled acceptance test.

Rack Status's built-in P2P provisioning action has not been converted to the minimal profile. Install the basic core with the dedicated P2P the minimal-profile render/preflight/load/check scripts described in the P2P handoff, then check selected Rack endpoint integration separately after both services pass standalone acceptance. Do not use Rack's advanced provision/reconcile action as a basic-core installer or connectivity test. Its older exact-image/object-store/workflow gates remain independent.

MinIO/dfstore is optional. If selected, satisfy that kit's exact object-store image, TLS, endpoint and import/read-only credential requirements and qualify a real dfstore round trip independently. Earlier missing PostgreSQL/MinIO digest pins and optional object-store access are not prerequisites for the replacement minimal public-core kit. NVIDIA workload catalog checks below apply only when those payloads are selected.

## Large P2P / Exemplar workload payloads

Prior NVFTP inventory lists approximately 468.6 GB of workload objects across multiple architectures and versions, including aggregate archives and duplicates. This is **not** a minimal six-tool install dependency estimate. Do not copy all of it as a substitute for selecting workloads. The user has not yet provided IREN hardware/workload scope.

The previous audit found three P2P catalog SHA-256 values disagreeing with transfer receipts. Receipt metadata does not prove current payload integrity. Never fix a catalog by copying a receipt hash without hashing the actual selected object. The advanced kit records this workload gate. The minimal public core, console and synthetic file test proceed independently of those objects; no NGC login or GPU workload download is needed for them.

For the chosen workload set, read the full actual payload and compute SHA-256 before acceptance. Preserve observed remote object path, byte count, timestamp, catalog value, receipt value and measured digest. If measured content differs from the approved catalog, record the discrepancy and obtain an authoritative matching artifact or release a reviewed updated catalog. Do not silently overwrite the original evidence. Large-payload source links remain references until copied and verified.

## Acceptance ladder

| Gate | Required evidence |
| --- | --- |
| Staged source | Exact source/release identifiers, files, sanitized deployment examples, SHA-256 manifests |
| Dependency closure | Compatible selected wheels/images/frontend/OS/runtime assets present, including the external Observability platform pack for a fresh install; model assets only for chosen model workloads; all remaining external prerequisites listed |
| Windows control ready | Native tools available, release integrity verified, VPN instructions applied, SSH authenticated with trusted host key |
| Linux install ready | OS/CPU/ABI/storage/runtime checked; offline install succeeds; rendered site configuration reviewed |
| Service ready | Exact services enabled as intended, health checks pass, authenticated local tunnel/UI works, no automatic remediation armed; minimal Dragonfly bootstrap login succeeds and its default password is changed |
| Collector ready | One explicitly selected node/source reports correct data and timestamps; secrets not present in logs |
| Canary workload ready | Approved node/partition/time/GPU limits; one chosen workload; job ID/output/exit state recorded |
| Site accepted | Repeatable results, expected topology coverage, recovery/rollback tested, owner signs off on relevant validation criteria |

Do not jump from static tests or health endpoints to site acceptance. Recovery actions and GPU jobs use the supplied scope and run limits. Discovery-only commissioning must not drain nodes, clear drains, restart Slurm, or run benchmarks.

## Evidence record

Keep a private `evidence/<UTC-run-id>/` on the deployment control host or approved site storage. Record release checksum, exact tool source IDs, target OS/arch/ABI, configuration hashes (not credentials), installed dependency versions, remote service names, listener bindings, collector target list, scheduler job IDs, logs, measurements and rollback commands. Report skipped gates with their reason. Publish only sanitized summaries into the shared handoff folder.

## Rollback contract

Before each install, record prior service state, configuration and release symlink target. Install into versioned paths. Preserve prior SQLite/databases and persistent telemetry stores with tool-appropriate backups. Do not roll back a database schema by replacing binaries without checking migration compatibility. Stop only the newly installed unit/compose project, restore the recorded configuration/release path, and recheck health. Collector uninstall must not remove shared drivers, scheduler plugins or unrelated services.
