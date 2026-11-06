# IREN MKZ: current staging delivery

Updated 2026-11-05T05:25:36.256963+00:00

**Published and full-byte read-back verified. Six-tool installation candidate; live Windows/VPN/IREN commissioning remains required.**

## Download and reading order

- NVFTP current entry points: `IREN_MKZ/agent_handoff.md` and `IREN_MKZ/RELEASE_INDEX.json`.
- Dated current delivery: `/nvidia-space/shared/IREN_MKZ/bundles/20261105-windows-native-02`.
- Six-tool control ZIP: `IREN_MKZ-windows-control-20261105-r2.zip` (636,211,960 bytes).
- SHA-256: `28765b63d5331dc1413a43152c433af288897059960d7f636385bb78247607e7`.
- Monitoring image/binary/plugin/wheel packs are separate, already verified objects. Choose exactly one Linux platform using `DEPENDENCIES.json`; their revision01 paths are deliberately reused by content hash.
- Local current handoff: `/data/iren-mkz-work/coordinator/release2/agent_handoff.md`.

## Deployment model

Codex already runs in native Windows PowerShell. No WSL, Hyper-V, local Linux VM or Linux Docker engine is assumed on Windows. Windows stages and controls native SSH/SFTP/browser access. Designated remote Linux management hosts run backends and scoped IREN nodes run collectors/workloads. The user supplies Fortinet instructions and actual SSH/host/node scope to the future deployment agent. No Windows VM or IREN target was contacted during preparation.

## Tool readiness and evidence

- P2P now defaults to basic CNCF Dragonfly core and console: public PostgreSQL16/Redis, Manager/scheduler/seed/peer and HTTPS console. Default UI bootstrap is root/dragonfly. No NGC token or MinIO is required for that profile. A narrow Manager auth-cache fix is delivered as an explicitly identified derivative with pinned source/patch/toolchain/binary provenance and actual database/authentication regression evidence. See its exact runtime acceptance report for seed/peer byte-transfer and origin-metadata scope.
- Rack Status is the exact requested nvis/nvis-rack-status project, not the previous PythonCM fork. Exact-main CI frontend/docs, optional Windows desktop shell and Linux CPython3.12 wheelhouses are supplied. Network-disabled x86_64 installation, pip check and124 tests passed. Revision02 changes only its handoff/provenance to distinguish dedicated basic P2P from Rack's old advanced provisioning action.
- Auto Trigger:35 offline suites and209 shell/Slurm syntax checks passed; all13 action/recovery switches disabled in its commissioning profile.
- Collection:22 portable checks and six tests; actual CPython3.12 x86_64 offline wheel installation/imports/tests passed. Both Linux platform wheelhouses included.
- Exemplar:13 tests passed; source/recipe-preparation kit supplied. Selected NVIDIA workload images/models and hardware-specific runtime closure remain future inputs, not a requirement to install basic Dragonfly.
- Observability:source reconciled to requested NVFTP September overlay;12 image archives across both platforms plus exporter/Alloy binaries, Infinity plugin, Compose and Python wheelhouses supplied. Compose/Prometheus/Loki/Alloy checks, isolated route probes,22 lake tests and106-dashboard consistency/mock restore passed.
- Root helper parsing, checksum/guard/mock-transport checks and archive/manifest verification are preparation evidence, not Windows/Fortinet live acceptance. See standalone postassembly validation and per-tool evidence.

## Remaining site inputs and optional paths

Provide the approved Linux management hosts/OS/CPU/ABI/storage and existing or staged OS/Docker/runtime packages; VPN/SSH trust and identity; actual IREN inventory/topology/sources; and bounded validation scope. GPU/DCGM/driver compatibility and selected Exemplar/benchmark image/model assets need matching target information. NGC/HF credentials may be needed only for selected protected assets that are not already cached.

Optional advanced P2P dfstore/MinIO/full-object-store integration retains independent original-image requirements. Three historical NVIDIA workload catalog/receipt hash disagreements must be resolved against actual selected payload bytes before those workloads are used; they do not gate public core login or synthetic-file P2P acceptance. Rack's existing advanced P2P provisioning action does not automatically become the new minimal profile.

No upstream merges, IREN service installs, cluster jobs, drain changes or node operations were performed. Known-token byte scanning passed; no exhaustive security scan is claimed. Runtime credentials, SSH keys, generated test TLS private keys and session tokens are excluded from the intended distribution.

Revision01 full-object-store P2P instructions are superseded for basic deployment. Its unverified large master temporary object was removed; use the revision02 current index and control ZIP.
