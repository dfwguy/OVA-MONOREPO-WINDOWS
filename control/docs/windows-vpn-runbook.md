# Windows PowerShell and Fortinet VPN runbook

## Placement fixed by the requested environment

Codex already runs natively in PowerShell. Do not install WSL, Hyper-V, Docker Desktop, a new hypervisor, or another Codex instance as part of this handoff. Windows is the staging/control machine: ZIPs, dependency caches, native OpenSSH, browser, optional Rack Status desktop shell. Bash/systemd/Slurm/Enroot and Linux container backends run on designated Linux hosts reachable through the VPN.

The Linux management host must be provided. Do not assume a login node permits persistent web services or container engines. If no approved Linux management host exists, source staging can finish, but a full six-tool deployment cannot: these packages are not native Windows ports.

## Before VPN setup

Use the revision 02 control/toolkit archive `IREN_MKZ-windows-control-20261105-r2.zip` and its current inventory. If staging a fresh Observability backend, also download its external Linux architecture dependency pack from the exact NVFTP object recorded in the inventory/artifact index. Those immutable pack objects remain under `bundles/20261105-windows-native-01/tools/observability`; use their hashes without downloading an old master archive. Store/extract external packs outside the verified control tree, e.g. `C:\IREN\payloads\observability`. Finish the necessary downloads before connecting if Fortinet policy prevents subsequent NVFTP access. The smaller control ZIP alone is not a complete fresh offline Observability install.


1. Read the user's Fortinet installation/connection instructions from the private local path they supply. Use the required client version, VPN type, gateway, certificate, MFA and corporate network requirements exactly as specified. The bundle does not choose these values or contain VPN credentials.
2. Run `scripts/Test-WindowsControlHost.ps1`. Record OS/version/architecture, PowerShell version, native Python availability and free disk. This is read-only and needs no virtualization.
3. Confirm `ssh.exe`, `scp.exe`, `sftp.exe` and a native Python 3.11+ interpreter are available. Use the enterprise-approved Windows Features on Demand/OpenSSH deployment route if absent. The helper scripts do not install them automatically. The official Microsoft OpenSSH installation guide is linked below.
4. Copy `config/site.example.json` into a private working directory outside the release. Fill addresses, paths, scope and architecture as they become known. The example is a specification, not input to an automatic installer.
5. Populate the OpenSSH alias from `config/ssh_config.example`; obtain the remote host fingerprint through an independent trusted channel. Set up the SSH private key and ACLs using the organization's procedure. Never upload that key to NVFTP or put it in the ZIP.

## Connect and prove the path

Connect Fortinet using the user's instructions. Check both the IREN path and the NVIDIA/OpenAI path after connection: a full tunnel may remove access to GitLab, NVFTP, package registries or Codex's service. Codex needs its approved service connectivity from Windows; it is not an offline model deployed on IREN.

```powershell
Get-NetAdapter | Where-Object Status -eq 'Up'
Get-NetRoute -AddressFamily IPv4 | Sort-Object RouteMetric
Resolve-DnsName <approved-management-fqdn>
Test-NetConnection <approved-management-fqdn> -Port <approved-ssh-port>
ssh.exe -o StrictHostKeyChecking=yes iren-mkz-management 'uname -sm'
.\scripts\Test-RemoteLinux.ps1 -SshAlias iren-mkz-management
```

These commands use actual private values supplied by the site; angle-bracket examples are not executable until replaced. Do not publish route/DNS/IP inventory to a broadly shared delivery folder. A successful TCP test proves only reachability, not SSH identity, authentication, scheduler permission, collector access, or throughput. Confirm an authenticated SSH command with the expected remote identity.

Record VPN reconnect behavior, idle timeout and connection ownership. Test `ssh` from the **same Windows user/session that runs Codex**, because per-user VPN or credentials may differ. There is no WSL connectivity test in this design. If the VPN permits only a bastion, configure `ProxyJump` in the alias rather than embedding passwords in commands.

## Network flows and application direction

| Initiator | Destination | Purpose / boundary |
| --- | --- | --- |
| Windows | NVIDIA GitLab/NVFTP/approved public sources | Source/payload staging while network access exists; use appropriate corporate authentication; public Dragonfly core has no NGC credential requirement |
| Windows | OpenAI/enterprise Codex service | Existing agent connectivity; retain access after VPN connection |
| Windows | IREN management host SSH | File transfer, read-only preflight, deployment commands and local UI tunnels |
| Windows loopback browser/desktop | Windows loopback SSH listener | UI access; use a distinct local port per tool |
| Linux management host | Allowed controller/BCM/SSH/Slurm endpoints | Tool operations using explicitly supplied management interfaces |
| Linux collectors/exporters | Linux observability core, or core scraping collectors | Depends on exporter vs push architecture; configure each tool's actual source and destination |
| IREN peer nodes | Allowed IREN scheduler/seed/peer endpoints | Minimal Dragonfly file-distribution/control traffic stays within IREN; no MinIO or Windows callback is required for basic seed/peer distribution |
| Selected advanced P2P components | Approved IREN object-store endpoints | Optional dfstore/MinIO path only; separate TLS, port and import/export identities from the minimal public core |

Start with Windows-initiated SSH and pull/scrape paths. An IREN exporter does not automatically have a route back to a Windows VPN-assigned IP. Running the core on the remote Linux management host avoids depending on unsolicited IREN-to-Windows traffic. If a selected mode truly needs callbacks across VPN, obtain and test the specific source, destination, route, port and authentication configuration before selecting it. Do not turn the Windows VM into a general VPN router.

Open only the necessary site-internal collector/service paths. UI services should bind to loopback where possible and be accessed through SSH; authentication remains required according to each tool's handoff. Preserve TLS where configured. Never make a broad firewall rule or bind every service to every Windows interface merely to bypass a connectivity issue.

## Browse a remote UI from Windows

First confirm the **actual** remote listener from the installed config and `ss -ltn` on the management host. Ports in `config/site.example.json` illustrate a non-conflicting local layout; they do not prove a tool's listener.

```powershell
# Supplied Observability core: remote Grafana port 3001, local browser port 13001.
.\scripts\Open-ToolTunnel.ps1 -SshAlias iren-mkz-management -LocalPort 13001 -RemotePort 3001
# In a separate window, open the configured scheme: http://127.0.0.1:13001
```

For minimal Dragonfly P2P, the default UI is the nginx HTTPS listener on remote loopback port 4301, not Manager REST on port 12004 or the older console-operations API. Use the configured listener and match the certificate hostname when browsing. With the default generated localhost certificate:

```powershell
.\scripts\Open-ToolTunnel.ps1 -SshAlias iren-mkz-management -LocalPort 4301 -RemotePort 4301
# After verifying/trusting the kit-generated certificate as documented:
# Browse https://localhost:4301
```

 The supplied bootstrap UI account is `root` / `dragonfly`; sign in, change the default password, and keep the UI bound/restricted as documented. NGC credentials and MinIO object-store credentials are not needed for this login. The PostgreSQL/Redis/JWT site configuration is a separate backend concern. The default P2P remote port 4301 is distinct from Observability's optional lake-browser host mapping on port 4300. If overriding the minimal kit's `console_port`, recheck actual remote bindings; changing only a local SSH forwarding port cannot fix a remote socket collision.

For Rack Status, prefer its source-pinned prebuilt web client served by the matching backend. The optional Windows desktop shell is separately versioned and older; verify the kit's desktop provenance and its connection settings before use. Do not treat it as the Linux backend installer.

## Failure diagnosis

| Symptom | Next discriminating check |
| --- | --- |
| Hostname fails but IP connects | VPN DNS suffix/resolver configuration from the user's instructions; do not permanently replace DNS with public resolvers |
| Windows SSH port unavailable | Fortinet connection, route choice, VPN ACL, bastion requirement and site SSH port |
| SSH connects but UI fails | Remote listener/bind address, HTTP vs HTTPS, SSH forwarding policy, exact port and application auth |
| UI works but no telemetry | Exporter process, discovery target configuration, site-internal direction/ports, label mappings and scrape/ingestion errors |
| VPN connects and Codex/GitLab stops working | Full-tunnel or proxy policy; finish staging before VPN or use the approved split-tunnel policy; do not invent routes |
| Transfer interrupted | Reconnect, reverify SHA-256, resume with an approved transfer tool; retain and identify partial files |
| VPN drops while service is running | Inspect remote service/job state first; loss of the Windows terminal does not prove cancellation |

## Disconnect and recovery

Close local SSH tunnels when finished. Stop only the exact remote services/jobs created for this release, using per-tool rollback instructions and recorded job IDs. Preserve inventories, logs and run evidence in private site storage. Never issue a blanket `scancel -u`, restart an existing cluster service, clear drains, or delete shared logs as a cleanup shortcut.

Primary references checked during packaging:

- [Microsoft: install OpenSSH on Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)
- [Microsoft: SSH key authentication](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement)
- [Official OpenAI Windows documentation](https://learn.chatgpt.com/docs/windows/windows-app) (agent is already installed; no installation requested)

Fortinet configuration remains the user's forthcoming site instructions. No unverified generic VPN setup is included.
