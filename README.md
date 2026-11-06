# OVA-MONOREPO-WINDOWS

Six-tool OVA delivery for a Windows management VM, with inspectable source, offline assets, a user guide and repeatable validation.

**Status: native Windows backend commissioning is incomplete.** The supplied NVFTP revision was designed for native Windows orchestration over SSH, with Linux backends. It does not establish that six services run natively on Windows. This repository preserves that limitation and the current requirement: no WSL, Hyper-V or Linux virtualization on the Windows VM.

- [User guide](docs/OVA-MONOREPO-WINDOWS-User-Guide.md)
- [PDF user guide](docs/OVA-MONOREPO-WINDOWS-User-Guide.pdf)
- [Original release provenance](provenance/RELEASE_INDEX.json)
- [Windows acceptance harness](tests/Test-WindowsControls.ps1)

## Contents

| Path | Purpose |
| --- | --- |
| `control/` | Sanitized Windows staging/control delivery and six toolkits; its manifest checks this tree only. |
| `components/` | Expanded toolkits and source for review. |
| `components/rack-status-pythoncm/` | Requested PythonCM source, pinned to commit `8d1896e55cf24c23ef80d9ccef8a0d9a8a7962f7`. |
| `components/nvis-rack-status/` | Different Rack implementation supplied by the original bundle; retained for provenance, not a PythonCM substitute. |
| `artifacts/` | Sanitized control archive and Linux architecture-specific offline Observability packs. |
| `provenance/`, `evidence/` | Source identities, integrity checks, sanitation records and validation evidence. |
| `tests/` | Portable integrity checks and actual Windows control-host acceptance harness. |

The six requested tools are Exemplar Recipe, P2P, Rack Status/PythonCM, Auto Action Trigger, Observability and OVA Collection Framework. Their services, dependencies and cluster-side execution requirements remain distinct. Bundling does not itself integrate or port them.

## Clone and validate

Install Git LFS before cloning. Large binary archives are stored through Git LFS; a ZIP containing only LFS pointers is not an offline release.

```powershell
git lfs install
git clone https://gitlab-master.nvidia.com/nvis-ova/OVA-MONOREPO-WINDOWS.git C:\OVA
Set-Location C:\OVA
git lfs pull
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\Test-WindowsControls.ps1
```

The Windows harness exercises PowerShell parsing, bundled Windows Python, integrity/extraction and guarded transport arguments. Mocked transport checks are explicitly identified. It does not establish customer VPN reachability, service startup, GPU workload success or site acceptance.

VPN configuration must come from the site owner. Verify Windows connectivity to the actual BCM head node and app-server, SSH host identity and approved node scope before commissioning. Keep credentials and site configuration outside this repository. The current requirement places persistent management services on native Windows and limits cluster installations to necessary collectors, peers and workload execution; every exception or unsupported service must be reported explicitly.

## Release integrity

The original NVFTP distribution contained generated Rack runtime secret material. The publishing copy is sanitized; original archives are excluded. Use the sanitation and release records for the new checksums rather than treating historical NVFTP checksums as the checksum of a rebuilt archive. Source test evidence and Windows control acceptance are separate from six-service runtime acceptance.

Agent coordination with the existing Windows Codex session will use `codex queue --remote` once its reachable app-server endpoint and session ID are supplied.
