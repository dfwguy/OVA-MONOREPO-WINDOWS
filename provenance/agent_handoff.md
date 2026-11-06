# Current IREN_MKZ delivery: revision02

Download the six-tool control bundle `IREN_MKZ-windows-control-20261105-r2.zip` (636,211,960 bytes), SHA-256 `28765b63d5331dc1413a43152c433af288897059960d7f636385bb78247607e7`, from `bundles/20261105-windows-native-02/`. Download the matching Observability dependency pack separately, as listed in `DEPENDENCIES.json` and this folder's `RELEASE_INDEX.json`. All paths below refer to the extracted control bundle.

This revision uses the basic Dragonfly core/console by default. Earlier revision01 full-object-storage P2P gates are not prerequisites to this default profile.

---

# IREN Mackenzie: six-tool deployment handoff

## Read this first

You are Codex running **natively in Windows PowerShell** on a Windows VM inside the NVIDIA network. Codex is already installed. WSL and Hyper-V are unavailable. Use Windows for downloading, verification, staging, SSH control and UI access. Do not assume Bash, systemd, Enroot, Slurm or Linux Docker works natively on Windows.

The user will supply the Fortinet VPN setup instructions separately. Follow those instructions, then use trusted-key SSH to deploy the Linux services and collectors to **designated IREN Linux hosts**. IREN has no internet access. All remote installation must use staged dependencies or existing approved site infrastructure.

Revision 02 uses `IREN_MKZ-windows-control-20261105-r2.zip` from `bundles/20261105-windows-native-02`. This control/toolkit ZIP contains all six source/toolkits, handoffs and common scripts. The two large Observability architecture dependency packs remain separate verified NVFTP objects; select and download the matching Linux platform pack before a fresh offline Observability installation. See the inventory and `docs/artifact-index.md` for their exact paths and hashes. The control ZIP alone does not close Observability's image/binary/plugin/wheel dependencies.

This is a coordinated delivery layout, not a new integrated product: the six tools retain their own runtimes, configuration, services and evidence. Nothing in this bundle automatically deploys across the cluster, runs GPU jobs or enables remediation. The release inventory and per-tool validation records establish what was packaged and tested; they do not certify IREN live acceptance.

## Exact sources and purpose

| Tool | Requested source | Role |
| --- | --- | --- |
| NVIS P2P | https://gitlab-master.nvidia.com/nvis-ova/nvis-p2p | Dragonfly public core and web console with Manager, scheduler, PostgreSQL 16, Redis, seed and peer; optional dfstore/object-storage and NVIDIA workload assets are separate deployment choices |
| NVIS Rack Status | https://gitlab-master.nvidia.com/nvis/nvis-rack-status | Cluster/rack inventory, health/status UI and backend, SSH-connected remote operations; includes optional native Windows desktop shell |
| Auto Action Trigger | https://gitlab-master.nvidia.com/nvis-ova/auto-action-trigger | Linux/Slurm workflow scripts, monitoring, collection and configurable automatic actions; commission with jobs and recovery disabled |
| OVA Collection Framework | https://gitlab-master.nvidia.com/nvis-ova/OVA_Collection_Framework | Durable Linux evidence collection/processing service and hooks; stateful deployment must be near its approved data sources |
| Exemplar Recipe | https://gitlab-master.nvidia.com/nvis-ova/nvisova-exemplar_recipe | Recipe preparation and controlled Linux/Slurm GPU validation workloads using selected compatible images/models |
| Observability | https://nvftp.nvidia.com/file-explorer/8250a39b-4b0d-47dd-ae22-27b0db9a4618/nvidia-space/shared/NscaleTX-16K/Observability | Metrics/logs/dashboard stack and node/cluster collectors; derived from the deployed NVFTP source rather than silently replacing it with older GitLab source |

**Rack Status is the `nvis/nvis-rack-status` project.** The previous audit's `nvis-ova/rack-status-pythoncm` is a different source and is not substituted here. Exact source commits, package hashes and any local packaging adjustments are recorded in each kit.

## Placement without local virtualization

```text
NVIDIA network                         Fortinet VPN           IREN (no internet)
Windows VM / PowerShell                 established by user
  Codex (already installed) --------------------------------> trusted SSH entry
  source ZIP + dependency storage                              Linux management host(s)
  native Python verification                                  Rack backend + web assets
  OpenSSH: scp/sftp/ssh                                        P2P core (supported CPU)
  browser / optional Rack desktop <--- localhost SSH tunnel --- Observability core
                                                              Collection service/state
                                                              Auto Trigger service/scripts
                                                              Slurm workload launch control
                                                                      |
                                                               scoped Linux nodes
                                                               exporters/collectors
                                                               P2P clients/workloads
                                                               Exemplar jobs
```

The bulk **files and orchestration** can stay on Windows. The bulk Linux **runtime** cannot execute there under the stated constraint. Designated remote Linux management capacity is a required deployment input. Do not install all backend services onto an arbitrary login node or onto GPU nodes just because SSH succeeds. A site-provided management node, a separate approved Linux VM reachable over VPN, or existing supported site services must host them.

There is no need for an IREN-to-Windows callback route for browser access: Windows initiates local SSH forwards to the remote UI. Keep peer/RDMA/GPU benchmark data within IREN; VPN is for control, staging and selected telemetry/result transfer.

## P2P mode selection and bootstrap login

The default P2P delivery is the **minimal Dragonfly core and console**. Its deployment chain is PostgreSQL 16 + Redis → Manager → scheduler → seed → scoped peer, with nginx serving the Dragonfly console/API over HTTPS. A fresh minimal deployment uses the supplied initial Manager-console login `root` / `dragonfly`. The default console listener is remote loopback HTTPS port 4301. Forward Windows loopback port 4301 to that listener and browse `https://localhost:4301`, using the hostname covered by the generated localhost certificate. Verify/trust the site certificate using the minimal kit's procedure; sign in and change the default password. Manager REST on loopback port 12004 is a separate backend endpoint and is not the browser console entry point. The web UI account is separate from Linux SSH, PostgreSQL, Redis, JWT secrets and any optional object-storage identity.

This core uses public components and has no NGC/NVIDIA-registry credential requirement. Offline IREN hosts load the supplied platform-matched archives rather than pulling registries. A test file generated for acceptance and a controlled HTTP origin as described by the minimal kit are sufficient to test seed/peer distribution; no model, NGC image or GPU allocation is needed to establish that the core and console work.

Deploy the basic profile through the P2P kit's dedicated minimal-profile render/preflight/load/check scripts described in the P2P handoff. Rack Status's built-in `nvis-p2p-provision` action still targets its older full PostgreSQL/MinIO/object-storage layout; the new kit does not switch that action to the minimal path. Its unchanged `source/deploy/p2p/artifacts.lock` also pins the original buggy Manager, while revision 02 ships `v2.5.1-iren-authfix.1` with a different SHA-256. Do not run Rack's `stage-artifacts.sh` against the revised P2P `source/dist`, bypass the lock, restore the old Manager, or let old provisioning overwrite the accepted minimal core. Leave that action unused during minimal commissioning. Once Rack and Dragonfly work independently, register/check only the supported endpoint integration as a separate acceptance step. Native-console login and a synthetic peer transfer do not establish Rack's legacy NVIS/catalog/dfstore rollout contract.

The local preparation canary verified a fresh peer receiving a 14,800,000-byte file from a warmed seed while origin bulk-body requests were denied. This client still made a one-byte `Range: bytes=0-0` metadata probe to the internal origin. Keep that IREN-internal origin available; small files can take the client's direct-origin path. The temporary body-denial rule was an acceptance test, not the production origin configuration. None of this requires public internet access from IREN.

The older full dfstore/MinIO/catalog automation is retained as an **optional advanced path**. It introduces object-store endpoints, TLS, import/export credential separation and its own exact-image dependencies. After unpacking `tools/nvis-p2p/nvis-p2p.zip`, read `nvis-p2p/optional/full-stack-agent_handoff.md` before choosing that mode. The default entry point is `nvis-p2p/agent_handoff.md`, with its ordered `scripts/render-minimal.py`, `scripts/preflight-minimal.py`, `scripts/load-images.py` and `scripts/check-console.py` commands plus staged `offline/` dependencies. Do not require MinIO-specific credentials during basic Dragonfly setup, and do not imply that basic core acceptance proves dfstore or all historical NVIDIA workload payloads work.

## Bundle layout and entry points

Read `RELEASE_INVENTORY.json` and `docs/artifact-index.md` for actual filenames, sizes, platforms, included and external dependencies, measured hashes and limitations. Each tool has its own ZIP and handoff. The control ZIP includes the Observability source ZIP and handoff; its large per-platform dependency ZIPs are downloaded separately from the exact existing NVFTP objects recorded in the inventory. Root scripts coordinate integrity, transfer and connectivity only.

```text
agent_handoff.md                     this orchestration contract
RELEASE_INVENTORY.json                release status and actual artifact inventory
FILE_MANIFEST.json                    outer payload file hashes and byte counts
tools/<tool>/                        six toolkits and their deployment handoffs
config/site.example.json             private site inputs to fill; not an installer
config/ssh_config.example            Windows OpenSSH alias template
scripts/verify_bundle.py             stdlib SHA-256 verification
scripts/unpack_toolkit.py            safe ZIP extraction with Linux mode retention
scripts/Test-WindowsControlHost.ps1   read-only native Windows inventory
scripts/Test-RemoteLinux.ps1          read-only authenticated SSH preflight
scripts/Send-Release.ps1              transfer a ZIP into a NEW remote staging dir
scripts/Open-ToolTunnel.ps1           loopback-only UI forwarding
scripts/Download-Release.ps1          optional native SFTP download and checksum check
docs/windows-vpn-runbook.md           VPN, routing, UI access and diagnosis
docs/airgap-and-acceptance.md          dependency closure, acceptance and rollback
docs/artifact-index.md                generated pointers to per-tool artifacts
```

Do not run every `.sh` or installer found in a source ZIP. Read the tool's handoff and the proposed configuration first. Retained historical examples are not IREN deployment defaults. Site-specific runtime secrets, the GitLab token, SSH keys, optional NGC/Hugging Face credentials and the user's VPN instructions are deliberately external to the distribution. Check the existing NVFTP asset cache before requesting any credential for a selected protected benchmark/model image. The supplied Dragonfly bootstrap UI login is `root` / `dragonfly`; this known default is not an NGC credential. Change it after the first authenticated login, before broadening access.

## Inputs to obtain from the user/site

The user already intends deployment; do not ask for blanket permission to do ordinary preparation. Obtain missing **concrete configuration** before the step that needs it:

| Input | Why it is needed |
| --- | --- |
| Fortinet instruction file/client/gateway/authentication process | Connect through the intended VPN without inventing settings |
| Linux management host(s), SSH alias/user/port and trusted fingerprint | Place unsupported-on-Windows services and transfer files securely |
| Host OS/CPU architecture/Python ABI/available runtimes/storage | Choose compatible offline wheels, binaries, image archives and OS packages |
| Approved controller/BCM/Slurm endpoints, node list and partition | Avoid using old customer/lab configuration and bound collection/workloads |
| Collector discovery targets and labels | Correct telemetry/topology and permitted data sources |
| Persistence roots, ownership and available capacity | SQLite state, time-series/log retention and large workload storage |
| UI authentication/TLS and service-owner requirements | Correct listener and authenticated access model |
| Validation recipe/model/precision/scale/time/GPU limits, when GPU workload validation is selected | Select the requested compatible Exemplar/NVIDIA workload assets and a bounded canary; these inputs are not prerequisites for installing the basic Dragonfly console |
| SSH credential-file location; NGC/HF file locations only for selected protected assets | SSH authorizes target access. Public Dragonfly core requires no NGC or NVIDIA-registry credential; selected NVIDIA/model downloads may require separate credentials. Never paste private secrets into shared docs |
| Available approved connected Linux builder, if prerequisites are missing | Produce OS/architecture-specific dependency closure without WSL/Hyper-V |

Record these in a private copy of the site plan. Do not upload site credentials or full node inventory to the shared delivery folder. Unknown inputs do not block downloading, reading handoffs, local checksum verification or writing an explicit deployment plan.

## Execution sequence

### 1. Download and verify on Windows

From the IREN_MKZ NVFTP folder, use the revision 02/current index to download `IREN_MKZ-windows-control-20261105-r2.zip` and its `SHA256SUMS`/receipt. Do not use an earlier master archive as the default P2P deployment source. Separately download the compatible Observability dependency pack recorded in the inventory when provisioning Observability offline from fresh storage. Use the authenticated web client or the supplied native SFTP helper with **your own** NVFTP credentials. Compare the control ZIP's SHA-256 before extraction:

```powershell
Get-FileHash -Algorithm SHA256 C:\IREN\downloads\IREN_MKZ-windows-control-20261105-r2.zip
Expand-Archive -LiteralPath C:\IREN\downloads\IREN_MKZ-windows-control-20261105-r2.zip -DestinationPath C:\IREN\release-r2
Set-Location C:\IREN\release-r2
py -3 scripts\verify_bundle.py .
.\scripts\Test-WindowsControlHost.ps1
```

Store external dependency ZIPs and their extracted content in a separate directory such as `C:\IREN\payloads\observability`, outside `C:\IREN\release-r2`. `FILE_MANIFEST.json` verifies the control tree only; adding image packs or extracted files inside it will fail strict verification. Verify the selected pack's archive SHA-256 against the external inventory, then use its internal payload manifest/helper after extraction. The dependency object paths still contain the earlier `20261105-windows-native-01` directory because those exact immutable Observability packs are reused by hash; this is not an instruction to download the old complete master ZIP.

Use actual bundle filenames from the index. A short extraction path reduces Windows path-length issues. The Windows staging directory is not a Linux installation root. Do not let PowerShell turn LF Bash source into CRLF when transferring it.

If native Python is absent, `windows/` includes an optional official CPython embeddable x64 ZIP for these stdlib helpers. See `windows/README.md`; extract the interpreter outside the verified release tree and invoke it by its full path. It supplies no pip/Linux service runtime and requires a compatible Windows x64 host.

### 2. Apply the user's VPN instructions and inspect the Linux host

Follow `docs/windows-vpn-runbook.md`. Establish Windows-to-IREN trusted SSH, then run `Test-RemoteLinux.ps1`. Inventory management hosts separately from GPU nodes. Record architecture and storage before choosing dependency sets. Check existing ports and service names to avoid collisions. Confirm the Linux host is authorized for persistent backends; ordinary login access is insufficient evidence of placement.

### 3. Close the selected offline dependency set

Read each toolkit's dependency inventory. Use supplied wheels and prebuilt assets only for matching platforms. For P2P, select the minimal Dragonfly core/console unless the user explicitly requests dfstore/MinIO object storage. Identify missing dependencies for the selected path, stage them on connected infrastructure and record measured hashes. Models, GPU workload images and object-storage dependencies are required only by the functionality that uses them. The Observability platform dependency pack is an external required input for a fresh offline core installation; download it to the separate payload directory and verify its recorded hash before transfer. See `docs/airgap-and-acceptance.md` for explicit offline flags and workload-image integrity gates.

Do not claim installation ready if a selected dependency remains a URL-only reference. The Windows control host retains network access only as permitted by the VPN policy; IREN itself performs no public-registry downloads. A package cache may be staged before VPN connection if the VPN prevents access to NVIDIA services.

### 4. Transfer into a versioned remote staging directory

`Send-Release.ps1` checks the local ZIP hash, creates a new `/var/tmp/iren-mkz/<release-id>` and checks the remotely read ZIP hash. It does not extract or install. Supply the checksum from the release receipt:

```powershell
.\scripts\Send-Release.ps1 -SshAlias iren-mkz-management `
  -BundleZip C:\IREN\downloads\<release-bundle>.zip `
  -ExpectedSha256 <64-hex-release-hash> -ReleaseId <unique-release-id>
```

Extract the control ZIP into a fresh Linux `control/` directory, run root verification there, then unpack only selected tool ZIPs outside that verified tree using `python3 scripts/unpack_toolkit.py <tool.zip> <new-directory>`. If extracting with `unzip`, verify executable modes against tool metadata. Transfer/extract external Observability packs to a separate sibling `payloads/` directory; pass its actual path to the Observability dependency helper. Do not place external packs inside the verified `control/` tree, and do not overwrite a working installation with staging files.

### 5. Render site configuration before starting services

Prepare the real site paths/endpoints/discovery lists/credentials outside Git. Compare them against the supplied templates. Render and inspect systemd/Compose/tool plans using the tool-specific commands. Confirm no retained Nscale/Lab examples are active. Confirm job submission, drain recovery and automated remediation are disabled during initial commissioning.

Choose a coherent service allocation. Prefer one designated management host for tightly coupled components if it meets platform and capacity constraints; use additional designated hosts when required by CPU architecture or site policy. Distinct tools may have differing default web ports; use explicit remote bindings and separate local SSH tunnel ports. The minimal P2P console defaults to remote HTTPS port 4301, avoiding Observability's optional lake-browser mapping on remote port 4300. If overriding `console_port`, check the new remote binding against other services. Changing only the Windows tunnel port cannot resolve two services competing for one remote port.

### 6. Commission services in dependency order

The following sequence is a commissioning plan, not a hardcoded runtime dependency graph:

1. Confirm SSH/site storage/source access and install the necessary compatible runtimes.
2. Install Observability core with empty explicit discovery; verify authenticated dashboard access through SSH. Add only one scoped exporter/source and check labels, freshness and error logs.
3. Install Rack Status backend with its matching prebuilt SPA; configure the approved inventory/management endpoints. Verify login and a read-only target before enabling integrations. Do not trigger its older full-stack P2P provisioning action to install the minimal Dragonfly profile; use the dedicated P2P CLI and qualify endpoint integration separately. The Windows desktop shell is optional.
4. Configure the Collection service with explicit minimal approved sources **before** applying its deployment plan. Apply immediately performs collection passes and enables its timers/services; there is no paused installer mode. Verify durable state, permissions, one scoped source, restart behavior and intended output destination.
5. Install the minimal Dragonfly P2P core/console on a supported Linux management host using its dedicated kit. It includes the public PostgreSQL 16/Redis and Manager/scheduler/seed/peer path. Open the nginx console HTTPS listener on remote loopback port 4301 through a loopback SSH tunnel, browse `https://localhost:4301` after certificate verification, and sign in with `root` / `dragonfly`; change the bootstrap password. Validate one synthetic file through a seed and a scoped peer. Neither MinIO/dfstore, NGC credentials, a model download nor a GPU workload image is required for this basic acceptance. Use the separate advanced object-storage kit only if that mode is explicitly selected.
6. Install Auto Trigger scripts with the supplied paused commissioning settings; verify paths/read-only collection before arming any job/recovery loop.
7. Prepare one Exemplar recipe with staged image/model assets and run it only on the supplied node/partition/GPU/time scope. This is a validation job, not a prerequisite to viewing installed UIs.

Use each tool's exact installation commands and acceptance checks. Do not infer that installing one collector satisfies all six tools. Hooks/integrations need their own configuration and verification.

### 7. Validate one canary, then expand deliberately

First inspect the proposed command and its effect. Record the selected nodes, scheduler constraints, expected duration, GPU allocation and cleanup behavior. Record job IDs and source/tool versions. Collect one known-good telemetry/report flow and one controlled failure/retry path where appropriate. Validate P2P topology and Exemplar performance against the site/hardware criteria supplied by the user; there is no universal pass threshold in this bundle.

Only expand coverage after the canary result is understood. Automatic recovery and actions that can clear drains, restart daemons or launch jobs remain off until their specific scope and behavior are configured.

### 8. Hand the installation back with evidence

Produce a private installed-state report: release checksum, source IDs, actual hosts, runtime versions, service names, configuration locations/hashes, listener/tunnel ports, credential locations (not contents), persisted state paths, collectors/node coverage, job IDs, acceptance results and rollback instructions. State every skipped/blocked check. Disconnecting VPN does not stop remote services or jobs; record what is intentionally left running.

## Boundaries and known release gates

Read `RELEASE_INVENTORY.json` for this build's precise status. No IREN workload was executed while constructing this handoff. Linux runtime execution and Windows helper execution are different validation domains; this Linux packaging host cannot establish that the target Windows VM, Fortinet policy or site Linux hosts behave correctly.

The minimal profile replaces the original unavailable PostgreSQL pin with its explicitly recorded, staged and locally tested public PostgreSQL 16 image. The unavailable MinIO pin remains an independent prerequisite only for the optional advanced object-storage path. Neither requires a registry credential for the supplied public minimal core. P2P's previously identified catalog/receipt disagreement applies to the affected NVIDIA workload payloads, not the public core or a synthetic-file distribution test. Exemplar workloads/models must be selected for the actual IREN hardware when that validation is requested. Container image staging does not provide site OS packages, drivers, an installed container runtime or site-specific credentials. The optional older Rack desktop package is not evidence that the newer backend supports every desktop feature without a connection test.

The delivery provides specific installation material and explicit remaining gates. Report completed work accurately: `STAGED`, `OFFLINE_INSTALL_VERIFIED`, `SERVICE_READY`, `CANARY_PASSED` and `SITE_ACCEPTED` require different evidence. Never label the entire six-tool cluster validated because source tests or one UI health endpoint passed.

## Suggested first prompt for the Windows agent

> Read agent_handoff.md and RELEASE_INVENTORY.json in this IREN_MKZ bundle. Codex is already running in native Windows PowerShell, with no WSL/Hyper-V. Verify the bundle and inventory the native tools. Read my private Fortinet VPN instructions at the path I provide, connect using them, and use my specified SSH alias and approved Linux management hosts to inventory target OS/architecture/storage. Prepare the site-specific offline installation plan using the staged toolkits. Download the external Observability dependency pack matching the approved Linux backend architecture, verify its recorded SHA-256 and keep it outside the strictly verified control tree. For P2P start with the minimal public Dragonfly core/console, sign in with the supplied bootstrap root/dragonfly account through an SSH tunnel, change that password, and verify one synthetic seed-to-peer file transfer. Do not make NGC access, MinIO, models or GPU images prerequisites for the public core. Use the separate advanced object-storage path only if I select it. Proceed with compatible staged installation and read-only commissioning within the supplied scope. Resolve missing target inputs before dependent steps. Keep automatic recovery and GPU jobs disabled until their exact node/partition/workload/time/GPU scope is supplied. Use SSH tunnels for UIs. Record commands, versions, checksums, service state, acceptance evidence and rollback paths; do not claim live acceptance for unrun checks.
