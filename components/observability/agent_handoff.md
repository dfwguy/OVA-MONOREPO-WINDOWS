# Observability agent handoff — IREN Mackenzie

## Status and placement

This kit stages the requested NVFTP Observability source and actual offline dependencies. It is a deployment candidate. It has not been installed on the IREN cluster, tested through Fortinet, or accepted on Windows. Windows PowerShell is the control and transfer environment; no WSL, Hyper-V, local Linux guest, or local Linux Docker engine is required or assumed.

Run the central monitoring services on an approved **IREN Linux management host** with Docker Engine and Compose. Run Linux/GPU/Slurm collectors on the approved controller and compute nodes. Windows stores the source ZIP, architecture-specific dependency ZIPs, site files, and handoff; it opens SSH sessions and browser tunnels through the user-configured Fortinet VPN. The dashboards are viewed in a Windows browser. A PowerShell process cannot supply Linux `/proc`, Slurm/Munge, systemd, DCGM host libraries, or Docker Linux bind mounts. Installing a Windows edition of a component does not validate the Linux integration in this snapshot.

If policy requires all central services to remain physically on the Windows VM with no Linux runtime, stop this deployment path and record an architecture blocker. The staged source has not been ported to native Windows services. An independently approved accessible Linux backend is required.

## Exact source and reconciliation decision

The source is the live NVFTP object:

`/nvidia-space/shared/NscaleTX-16K/Observability/NVIS-Observability-16K-2026.09.24-Complete-Source.tar.gz`

Fetched again on 2026-11-05. Size: 5,355,141 bytes. SHA-256:

`2066a00595ce140d9e35f719aaf7b6dc7c3a7f28abc2f8a9a7673e26e5a48624`

The selected source is its September `live-portable-config` architecture, supplemented by the original node installer as a reference. The old root `platform/docker-compose.core.yml` and older GitLab tree are not authoritative for this deployment: they disagree with the live overlay on VictoriaMetrics/Loki versions and Grafana coverage. The overlay contains 106 dashboard JSONs, three folders and five datasource definitions; the older file-provisioned subset does not contain every live dashboard.

`source/` retains the selected overlay's collector/lake code and restore tools. Source-cluster inventories/receipts and runtime evidence were omitted. Private endpoint literals were replaced with documentation placeholders. Source customer and node prefixes were converted to synthetic/IREN examples, preserving naming relationships; the original hardware/rack geometry remains a **template assumption**, not discovered IREN topology. Dashboard UIDs and cross-links were customized consistently from the source prefixes. Cached query-variable options/source selections were cleared and dashboard time windows reset to relative six-hour ranges; no source-cluster job ID is chosen by default. `PROVENANCE.json` records these transformations. `deploy/` is the new IREN staging layer and is the only supported starting configuration in this kit. The upstream reference Compose files are retained for design review, not direct execution.

## Components and offline payloads

| Component | Version in this candidate | Purpose |
| --- | --- | --- |
| VictoriaMetrics | 1.108.1 | Metrics system of record; Prometheus remote write |
| Prometheus | 2.54.1 | Bounded pulls from approved exporters; self-monitoring |
| Loki | 3.5.12 | Log ingestion/query and filesystem retention |
| Grafana | 11.1.4 | Browser dashboards and five stable datasource contracts |
| Alloy | 1.5.1 | Metrics/log receiver and forwarding gateway; node agent binary |
| Infinity datasource | 3.6.0 | Grafana data-lake SQL/query surface |
| Python base | `python:3.11-slim`, captured image ID/digest in receipts | Optional lakewriter/browser runtime |
| node_exporter | 1.8.2 | Linux host metrics |
| cgroup_exporter | 1.2.0 | Per-Slurm-job cgroup metrics |
| Lake Python wheels | pyarrow 17.0.0, python-snappy 0.7.2, protobuf 5.28.2, duckdb 1.1.1 plus captured numpy/cramjam | Offline CPython 3.11 lake runtime |

Each dependency ZIP is specific to `linux/amd64` or `linux/arm64`. It contains six Docker-loadable image archives; vendor binary/plugin archives; CPython 3.11 manylinux wheelhouse; static Compose 2.39.4; image/vendor receipts and a per-file SHA manifest. Image receipts record immutable image ID and registry digest from this staging run. The Python tag was resolved at staging time; use the supplied archive and image ID check, not a future pull of that mutable tag. Both platforms were downloaded; only amd64 parser/unit checks were executed locally. arm64 payloads were staged and hashed, not executed.

These are the supplied source-compatible versions. Staging and parser checks do not establish vulnerability clearance or driver compatibility. Do not silently upgrade images independently; qualify a coherent revised set if security policy requires it.

## Inputs required before a remote write

Obtain the Windows Fortinet setup instructions from the user and follow those instructions. The VPN is not configured in this staging session. Resolve:

- Linux management hostname/address, OS/distro, CPU architecture, Python 3.10+ for host helpers, Docker Engine/Compose availability, SSH username and key-file path; Windows OpenSSH availability and trusted host-key fingerprints.
- Exact canary node and subsequent allowed node list/partition, hardware generation, GPU/driver/DCGM versions and storage ownership/capacity.
- Authoritative IREN node/rack/SU naming map. Existing source hostname-to-rack functions and Slurm path inference are site-specific templates; adapt them against that inventory before using joins or topology panels.
- Grafana admin secret reference and authentication/access policy; collector credential files for optional UFM/Redfish integrations; retention and free-space policy.
- IREN-internal addresses for collector-to-core traffic. **Do not point nodes at the Windows VPN address by default.** Keep ingestion inside IREN; Windows accesses the Linux core through SSH. This avoids requiring inbound customer-to-NVIDIA routing.

No VPN configuration, SSH identity, Grafana password, NGC token or customer target inventory is bundled.

## Ordered deployment from Windows PowerShell

### 1. Stage and verify

Read the overall `agent_handoff.md` first. Verify release ZIP hashes in PowerShell with `Get-FileHash -Algorithm SHA256`. Extract the source ZIP and the dependency ZIP matching the **Linux backend architecture**, not Windows architecture. Preserve the directory layout when transferring. Windows extraction/transfer can drop POSIX execute bits; invoke Python helpers explicitly with Python, restore executable bits for vendor binaries with the supplied preparation helper, and set `chmod +x source/restore/import_grafana.py` before rerunning the mock restore test on Linux.

Use Windows OpenSSH (`ssh.exe`, `scp.exe`, `sftp.exe`) or the user-approved transfer method. Establish known host keys using an independently verified fingerprint. Do not disable host-key checking. Test SSH after Fortinet is connected before transferring large image archives.

Illustrative transfer only; set the variables to approved scope:

```powershell
$Controller = '<approved-linux-management-host>'
$SshUser = '<approved-user>'
$KeyFile = '<Windows-path-to-approved-private-key>'
ssh.exe -i $KeyFile "$SshUser@$Controller" 'uname -m; cat /etc/os-release; docker version; docker compose version; df -h'
scp.exe -i $KeyFile -r .\observability "$SshUser@${Controller}:/approved/staging/"
scp.exe -i $KeyFile -r .\dependencies\observability "$SshUser@${Controller}:/approved/staging/dependencies/"
```

These commands require an approved existing destination; create it with the correct owner first. The target has no internet. Supply Docker Engine/OS package dependencies from a distro-matched approved offline repository if they are not already installed. Docker daemon installation packages, GPU drivers and DCGM packages are **not bundled** because target OS/driver/hardware are unknown. The static Compose executable is included; it is not a Docker daemon.

### 2. Verify/extract/load on Linux

Run subsequent shell commands **inside an SSH session on the Linux management host**. They are Linux shell commands, not PowerShell commands:

```bash
cd /approved/staging/observability
python3 deploy/prepare_dependencies.py \
  --dependency-root /approved/staging/dependencies/observability \
  --load-images
```

The helper verifies every payload file, checks the host architecture, extracts the plugin and node binaries to staging, loads images, and checks loaded image IDs. It does not install or start a systemd service. Record the printed `PLUGIN_DIR`, `WHEELHOUSE_DIR`, and `NODE_BIN_DIR` paths. If using the bundled Compose binary, install it as the user's Docker CLI plugin only after verifying its checksum; alternatively invoke it directly as `docker-compose-linux-amd64`/`arm64` in all commands below.

### 3. Create protected configuration and empty storage

Copy `deploy/site.env.example` to a protected site file outside source, chmod 0600, set the Grafana secret without logging it, and set the actual dependency/storage paths. Retain `OBS_INGEST_BIND=127.0.0.1` until approved IREN-only inbound rules exist.

Create fresh storage directories with correct container ownership. Typical image users are Grafana UID 472, Prometheus UID 65534 and Loki UID 10001; inspect the loaded images before assigning ownership. VictoriaMetrics/Alloy users must also be checked rather than assumed. Apply permissions only to these new dedicated directories. Do not recursively chown existing cluster storage. Linux filesystems and storage service ownership are required; copying Windows ACL assumptions is insufficient.

The initial core uses seven-day VM metrics retention, two-day Prometheus retention, source Loki's 31-day policy, and rotated Docker JSON logs. These settings require site capacity review. An initial 8-vCPU/32-GiB Linux management allocation is only a canary planning estimate, not an accepted production sizing result. At fleet scale, measure sample/cardinality rates and disk growth; the original source used much larger CPU/memory/storage allocations. The optional lake defaults to a 200-GiB free-space guard and a 50-GiB spool bound; do not lower those guards merely to bypass a failing readiness check.

### 4. Render and start only the central core

```bash
docker compose --env-file /secure/site/observability.env -f deploy/compose.yml config --quiet
docker compose --env-file /secure/site/observability.env -f deploy/compose.yml up -d \
  victoriametrics prometheus loki grafana alloy
docker compose --env-file /secure/site/observability.env -f deploy/compose.yml ps
curl -fsS http://127.0.0.1:8428/health
curl -fsS http://127.0.0.1:9090/-/ready
curl -fsS http://127.0.0.1:3100/ready
curl -fsS http://127.0.0.1:3001/api/health
```

All images use `pull_policy: never`; a missing image fails instead of reaching the internet. This is a dedicated Compose project. Metrics/log stores use internal Compose service DNS rather than old source bridge IPs or host-gateway assumptions. Empty JSON files in `deploy/prometheus/targets` intentionally select no remote nodes. Confirm that Prometheus `/api/v1/targets` contains only the central core before installing collectors.

### 5. Open the Windows browser through SSH

In a separate Windows PowerShell terminal:

```powershell
ssh.exe -i $KeyFile -N -o ExitOnForwardFailure=yes `
  -L 127.0.0.1:13001:127.0.0.1:3001 `
  -L 127.0.0.1:19090:127.0.0.1:9090 `
  "$SshUser@$Controller"
```

Visit `http://127.0.0.1:13001`. The local diagnostic Prometheus URL is `http://127.0.0.1:19090`. Only bind these forwards to loopback. The Windows listener uses 13001 rather than assuming local 3001 is free. Grafana anonymous access is disabled in the IREN overlay. Keep credentials out of URLs, command history, transcripts and uploaded bundles.

### 6. Restore dashboards with explicit no-data boundaries

Create a least-privilege Grafana service token through the approved authentication workflow. Read it into the Linux process environment or run the stdlib Python restore from Windows through the forwarded URL. The restore importer needs only Python's standard library; Python on Windows is an additional prerequisite if choosing that path.

```bash
python3 source/restore/import_grafana.py --url http://127.0.0.1:3001 --dry-run
# Read GRAFANA_API_TOKEN securely; do not paste or echo it.
python3 source/restore/import_grafana.py --url http://127.0.0.1:3001
unset GRAFANA_API_TOKEN
```

The importer upserts three folders, five datasources, and 106 dashboards. Running it twice should update the same UIDs. It does not provision authentication/ACLs or activate source-cluster alert routing. The Data Lake datasource will show a source gap until the optional lake profile is commissioned. Source topology images/HTML panels and regex-derived rack joins are examples and may require site rendering and HTML-policy review. An imported panel is not proof that the collector exists or that the queried metric semantics match IREN.

### 7. Commission one node and one integration at a time

Prefer existing approved node_exporter/DCGM endpoints where present; do not install a duplicate service or steal a port. The dependency kit includes staged node_exporter/Alloy/cgroup binaries for both architectures. It does not include the NVIDIA driver, DCGM host engine, or a selected DCGM exporter binary. Select DCGM artifacts matching actual GPU/driver/libdcgm support and mirror their complete OS dependencies before rollout. Source `node-agents/systemd/dcgm-exporter.service` contains an arm64 library path; an amd64 target must use its actual discovered libdcgm directory.

`reference/node-installer/install-node.sh` and `stage-binaries.sh` are design references. Do not run them wholesale on IREN: their hostname geometry is site-specific, the original installer can remove pre-existing units with `SKIP_*`, and DCGM installation falls back to online apt. The offline target cannot use that fallback. Build reviewed IREN-specific units/drop-ins against existing service ownership, using the supplied `source/node-agents` files as templates. Install one explicitly named canary, collect its configuration/backup evidence, and verify `systemctl status` and exporter metric semantics before enabling timers or expanding.

For pull metrics, add exactly that node to the appropriate JSON, with explicit `instance`/`node`/cluster labels, e.g. `[{"targets":["<approved-canary>:9100"],"labels":{"node":"<inventory-node-id>","cluster":"IREN_MKZ"}}]`. Use a strict approved IP/name list. Source scrape filenames must match the new deploy configuration (`node.json`, `dcgm.json`, `cgroup.json`). Validate changed Prometheus configuration with `promtool` before reload/restart.

For push mode, bind Alloy 9098/9099 only to the approved IREN management interface and restrict firewall sources to canary/approved node subnets. Configure node remote-write to `http://<IREN-core>:9099/api/v1/metrics/write` (confirmed against the staged Alloy 1.5.1 runtime with networking disabled), and log push to its Loki-compatible ingest on 9098. A direct VM `/api/v1/write` endpoint is not the same URL as Alloy's receiver. The offline route probe returned HTTP 400 for a deliberately malformed request to the correct metrics/log routes and HTTP 404 for the VM-style route on Alloy; it verifies routing, not a successful payload round trip. Prefer the pull path for the first canary. The systemd/Alloy source reference contains additional native push configuration for adaptation.

Slurm/fleet/headnode/validation exporters need local Slurm binaries, Slurm config and accounting permissions, filesystem/log paths, and possibly Munge. Keep these collectors in IREN; do not mount remote `/cm`, `/cluster`, `/proc` or `/run/munge` paths on Windows. Install only the ones that correspond to the approved scope. BMC/Redfish/UFM integration is optional until endpoints, secret references and an explicit low-pressure polling plan exist. A reachability check is not authenticated sensor coverage.

### 8. Optional data lake

The IREN `lake` profile supplies lakewriter plus a DuckDB browser with offline wheels. The source's collector/reconciliation/compaction services remain templates and require paths, scheduler identity, explicit retention and minimum-free-space policies. Do not run the source Compose variants that execute `pip install` against the internet at container startup.

```bash
docker compose --env-file /secure/site/observability.env -f deploy/compose.yml --profile lake config --quiet
docker compose --env-file /secure/site/observability.env -f deploy/compose.yml --profile lake up -d lakewriter lake-browser
curl -fsS http://127.0.0.1:9410/healthz
curl -fsS http://127.0.0.1:4300/healthz
```

The lake starts with no data and the new core does not mirror metrics into it automatically. Select and commission the required log/artifact ingestion, VM export or reconciliation path before expecting dashboard SQL rows. Configure compaction/retention before bulk collection; the bundled two-service lake profile does not automatically enable the source's compaction timers. Browser data should remain read-only and access controlled; the source query API is not a general production authorization layer.

## Port and direction matrix

| Port | Listener location | Use and exposure |
| --- | --- | --- |
| TCP 22 | Linux management/controller | Windows-to-IREN SSH/SCP through Fortinet |
| TCP 3001 | Linux management loopback | Grafana; Windows SSH forward 13001 |
| TCP 9090 | Linux management loopback | Prometheus diagnostics; optional Windows forward 19090 |
| TCP 8428 | Linux management loopback | VM diagnostics/write; internal core uses service DNS |
| TCP 3100 | Linux management loopback | Loki query/write diagnostics |
| TCP 12345 | Linux management loopback | Alloy diagnostics |
| TCP 9098/9099 | Linux management loopback initially | Optional approved internal IREN log/metrics push |
| TCP 9100/9400/9306 | Selected Linux canary/node | node/DCGM/cgroup pulls from IREN core only |
| TCP 5555 | Node loopback | DCGM host-engine; never expose across VPN |
| TCP 9410/4300 | Linux management loopback | Optional lakewriter/browser |
| TCP 9105/9106/9421 | Site-configured Linux collectors | Optional UFM/headnode/Redfish; no default rollout |

No node is required to initiate traffic toward the Windows VM in the recommended architecture. Validate VPN DNS, SSH reachability, tunnel reconnect, MTU and long-transfer resumption using the user's Fortinet instructions. A Windows-to-controller ping alone does not prove collector/core traffic inside IREN.

## Verification evidence and acceptance

Offline checks in `VALIDATION.json` cover Python/JSON/shell syntax, Compose rendering, all 106 dashboard UID/file relationships, two mock Grafana restore passes, Prometheus `promtool check config`, Loki's own config verifier, Alloy fmt/parser validation and an isolated runtime route probe, and 22 data-lake unit tests in an amd64 Python container with network disabled. They do not exercise a GPU or Slurm controller. arm64 binaries/images were downloaded and checksum verified, not executed.

Before declaring ready, record: runtime/image IDs; actual architecture; VPN/SSH/tunnel proof; central health; the exact target list; matching live node/DCGM/cgroup metrics; a canary log round trip; time synchronization; restart/reconnect behavior; storage headroom/retention; dashboard query errors and no-data/source-gap panels; optional lake ingestion/query and compaction; scoped authenticated integrations; and rollback evidence. Absence of a collector must remain an explicit source gap. Do not replace missing telemetry with zero or label a synthetic sample topology as IREN discovery.

## Rollback

Keep a pre-change copy of site units/configs, Grafana provisioning/export and approved target lists. Stop the dedicated Compose project with `docker compose ... down` without `--volumes`; bind-mounted metrics/log/Grafana data remain for analysis. Remove/restore only the canary units and files created by this deployment, after confirming their ownership. Do not disable pre-existing node/DCGM exporters. Stop Windows SSH forwards by closing their dedicated process. Restore recorded target lists and original scheduler/collector configurations. Retain run logs and dependency receipts, excluding secrets, for the handoff.
