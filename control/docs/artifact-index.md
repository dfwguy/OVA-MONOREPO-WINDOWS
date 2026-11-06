# Delivered artifact index

All included paths below are relative to the extracted revision 02 control/toolkit ZIP, `IREN_MKZ-windows-control-20261105-r2.zip`, under NVFTP `bundles/20261105-windows-native-02`. Open each per-tool handoff, then extract that tool ZIP outside the verified control tree before following its internal `source/`, `scripts/` or `deploy/` paths. The Observability dependency ZIPs are external objects; select and download the matching Linux platform pack separately. The control ZIP alone does not provide a fresh offline Observability dependency closure.

| Tool | Handoff | Status |
| --- | --- | --- |
| auto-action-trigger | [tools/auto-action-trigger/agent_handoff.md](../tools/auto-action-trigger/agent_handoff.md) | `SOURCE_OFFLINE_CHECKED_WORKLOADS_EXTERNAL` |
| OVA_Collection_Framework | [tools/OVA_Collection_Framework/agent_handoff.md](../tools/OVA_Collection_Framework/agent_handoff.md) | `SOURCE_AND_CP312_WHEELS_STAGED` |
| nvisova-exemplar_recipe | [tools/nvisova-exemplar_recipe/agent_handoff.md](../tools/nvisova-exemplar_recipe/agent_handoff.md) | `SOURCE_OFFLINE_CHECKED_RECIPE_PAYLOADS_EXTERNAL` |
| nvis-rack-status | [tools/nvis-rack-status/agent_handoff.md](../tools/nvis-rack-status/agent_handoff.md) | `SOURCE_SPA_CP312_WHEELS_AND_WINDOWS_CLIENT_STAGED` |
| nvis-p2p | [tools/nvis-p2p/agent_handoff.md](../tools/nvis-p2p/agent_handoff.md) | Minimal public Dragonfly core/console is the default; advanced object-storage mode has a separate handoff and gates |
| observability | [tools/observability/agent_handoff.md](../tools/observability/agent_handoff.md) | `SOURCE_CORE_IMAGES_BINARY_PLUGIN_AND_WHEEL_PAYLOADS_STAGED` |

## ZIP payloads included in the control archive

- `tools/auto-action-trigger/auto-action-trigger.zip` — 987,133 bytes; SHA-256 `75ff6ddcea4f9c0fdd5e133b7a71d106de1551b7b1d9e19702a3b8ced57eaf59`.
- `tools/OVA_Collection_Framework/OVA_Collection_Framework.zip` — 138,220,636 bytes; SHA-256 `820abcb7d8509ca8416df1f6e6ecf3e7ca91aa1ef7bfd38c96459ab4f3721136`.
- `tools/nvisova-exemplar_recipe/nvisova-exemplar_recipe.zip` — 56,451 bytes; SHA-256 `fab35c5f7774e98fe53562cb04581485a462f85f4b30e9e3f50bf094ab1d4dd7`.
- `tools/nvis-rack-status/nvis-rack-status.zip` — 167,666,445 bytes; SHA-256 `1e42423d7737aa6f77acbc8864ab7eb38086a09106a4d345eba6698a52fb3ae7`. Revision 02 changes the handoff/provenance only to distinguish minimal P2P from Rack's older advanced provisioning; source, wheels, scripts, frontend, desktop binary and existing evidence are unchanged.
- `tools/nvis-p2p/nvis-p2p.zip` — 314,579,747 bytes; SHA-256 `5124c5799237f21d6fa2a90f27d0b4e51f265be398814a73623ac757d8ef0fa8`. Replacement minimal Dragonfly core/console, including explicitly versioned auth-fixed Manager; the revision 01 P2P checksum does not identify this replacement.
- `tools/observability/observability-source.zip` — 1,813,105 bytes; SHA-256 `5dfe9c3b751817e0a1e871976fda768347c42a166e3a34dbd040211c9dc620d4`.

## External Observability platform packs

These paths are relative to the NVFTP `IREN_MKZ` folder. They identify the already uploaded, fully readback-verified dependency objects from revision 01; the revision 02 control bundle reuses these exact bytes. Downloading these packs does not require downloading an earlier full master ZIP.

| Backend platform | Exact NVFTP object path | Bytes | SHA-256 |
| --- | --- | --- | --- |
| Linux amd64 | `bundles/20261105-windows-native-01/tools/observability/observability-dependencies-linux-amd64.zip` | 680,949,898 | `914991007abbbef5a66f00a01864c8c8715ed4ef5bfc110c964bc66e46fe4519` |
| Linux arm64 | `bundles/20261105-windows-native-01/tools/observability/observability-dependencies-linux-arm64.zip` | 634,417,483 | `1386ed791e5879d5071f0d1c97a912255c91b36052e47ec1481bc2c07a5904e3` |

Select according to the Linux backend architecture, not the Windows VM CPU. Each archive contains `dependencies/observability/` with six Docker-loadable images, native exporter/Alloy archives, Infinity plugin, CPython 3.11 lake wheelhouse, static Compose and per-file receipts. Store/extract it outside the verified control tree, for example `C:\IREN\payloads\observability` on Windows and a sibling `payloads/` directory on Linux. Verify the archive hash before extraction, then run the documented remote-Linux helper to verify/extract/load. No image pack supplies a Docker daemon, site OS packages or driver-compatible DCGM artifacts.

## P2P entry points after extraction

Extract `tools/nvis-p2p/nvis-p2p.zip` to a fresh directory. Its top level is `nvis-p2p/`:

- `nvis-p2p/agent_handoff.md` — default minimal public-core/console deployment.
- `nvis-p2p/scripts/render-minimal.py` (then the ordered preflight/load/check commands in the handoff) — minimal deployment CLI; use the exact commands from that handoff.
- `nvis-p2p/offline/` — staged public dependencies for the documented platform.
- `nvis-p2p/evidence/` — actual test records and remaining validation limits.
- `nvis-p2p/optional/full-stack-agent_handoff.md` — opt-in full dfstore/MinIO/object-store workflow with its independent requirements.

Rack Status's built-in `nvis-p2p-provision` action remains the older full object-storage workflow. Use the dedicated P2P the minimal-profile render/preflight/load/check scripts described in the P2P handoff for basic Dragonfly, then qualify any Rack endpoint integration separately; the replacement minimal kit does not switch that built-in action.

The control bundle still contains six tools. Optional P2P modes are not additional tools and are not prerequisites for logging into the minimal console.

## Deployment facts

- No WSL, Hyper-V or local Linux containers are used on Windows.
- P2P core requires a supported Linux x86_64 host; its ARM64 client binary requires 64-KiB pages.
- Rack backend and Collection wheelhouses target CPython3.12; Observability lake wheelhouses target CPython3.11.
- Root common scripts do not interpret site.example.json automatically. It is a private-input checklist; per-tool renderers consume their own configuration schemas.
- Minimal Dragonfly core requires no NGC/NVIDIA-registry credential. Its supplied initial console login is `root` / `dragonfly`; change it after first login. PostgreSQL/Redis/JWT site secrets are separate from that UI account.
- MinIO/dfstore and their exact-image/TLS/import/export requirements are optional advanced mode. Unverified NVIDIA workload payloads gate only the corresponding selected workload, not public-core login or synthetic file distribution.
- All target OS packages, GPU driver/DCGM compatibility where a selected feature needs them, site identity/discovery and live acceptance are explicit remaining inputs.
- Minimal Dragonfly console defaults to nginx HTTPS on remote loopback port 4301, forwarded to Windows port 4301 and browsed as `https://localhost:4301` after certificate verification. Manager REST port 12004 is separate. The `console_port` override must avoid other remote listeners, including the optional Observability lake browser on port 4300.

## Exact revision02 toolkit ZIPs

- `tools/auto-action-trigger/auto-action-trigger.zip` — 987,133 bytes; SHA-256 `75ff6ddcea4f9c0fdd5e133b7a71d106de1551b7b1d9e19702a3b8ced57eaf59`.
- `tools/OVA_Collection_Framework/OVA_Collection_Framework.zip` — 138,220,636 bytes; SHA-256 `820abcb7d8509ca8416df1f6e6ecf3e7ca91aa1ef7bfd38c96459ab4f3721136`.
- `tools/nvisova-exemplar_recipe/nvisova-exemplar_recipe.zip` — 56,451 bytes; SHA-256 `fab35c5f7774e98fe53562cb04581485a462f85f4b30e9e3f50bf094ab1d4dd7`.
- `tools/nvis-rack-status/nvis-rack-status.zip` — 167,666,445 bytes; SHA-256 `1e42423d7737aa6f77acbc8864ab7eb38086a09106a4d345eba6698a52fb3ae7`.
- `tools/nvis-p2p/nvis-p2p.zip` — 314,579,747 bytes; SHA-256 `5124c5799237f21d6fa2a90f27d0b4e51f265be398814a73623ac757d8ef0fa8`.
- `tools/observability/observability-source.zip` — 1,813,105 bytes; SHA-256 `5dfe9c3b751817e0a1e871976fda768347c42a166e3a34dbd040211c9dc620d4`.

## Separately downloaded monitoring packs

- `linux/amd64`: `/nvidia-space/shared/IREN_MKZ/bundles/20261105-windows-native-01/tools/observability/observability-dependencies-linux-amd64.zip` — 680,949,898 bytes; SHA-256 `914991007abbbef5a66f00a01864c8c8715ed4ef5bfc110c964bc66e46fe4519`; full NVFTP readback already verified.
- `linux/arm64`: `/nvidia-space/shared/IREN_MKZ/bundles/20261105-windows-native-01/tools/observability/observability-dependencies-linux-arm64.zip` — 634,417,483 bytes; SHA-256 `1386ed791e5879d5071f0d1c97a912255c91b36052e47ec1481bc2c07a5904e3`; full NVFTP readback already verified.
