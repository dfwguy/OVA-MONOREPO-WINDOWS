# IREN MKZ P2P kit instructions

Read `agent_handoff.md`, `PROVENANCE.json`, `evidence/VALIDATION.json` and the package integrity manifests before selecting a deployment path.

The default is the revision02 **minimal Dragonfly core**, using the shipped auth-fixed Manager, scheduler, seed/peers, public PostgreSQL16.15, Redis, nginx and HTTP origin. Root/dragonfly is the initial console login and must be rotated after acceptance. No NGC credential or MinIO service is required for this default.

Use `scripts/load-images.py`, `scripts/render-minimal.py`, `scripts/preflight-minimal.py` and the exact ordered deployment commands in the handoff. Rendering starts nothing. Windows remains the PowerShell/Codex/Fortinet/SSH/browser staging host; services and peer binaries run on the approved remote Linux hosts. There is no WSL/Hyper-V requirement.

Historical source includes a full MinIO/native-dfstore deployment skill and fixed-site NVIS fleet operations. They are an optional different architecture, not a prerequisite or automatic fallback for the basic kit. Do not invoke those legacy installer/fleet scripts for the default deployment. Preserve prior state when an existing service/config is found; the default instructions cover a new isolated installation.

Use only the operator-provided IREN management/controller addresses, trusted SSH identity and exact node/workload scope. Reserved template addresses are not targets. Check each peer's architecture/page size and existing unit/ports/state before any write. Keep private generated site data, credentials, certificate keys, DB volumes and session tokens out of shared artifacts.
