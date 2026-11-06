# IREN MKZ deployment agent entry point

Read `agent_handoff.md`, `RELEASE_INVENTORY.json`, `DEPENDENCIES.json` and the selected tool handoff before deployment.

Codex already runs in native Windows PowerShell. WSL/Hyper-V/local Linux containers are unavailable. Use native verification/OpenSSH/browser access; place Linux backends and collectors on the user's designated Linux hosts through the Fortinet VPN instructions they provide.

This is an immutable staging tree. Verify its manifest, then extract tools, download external dependencies, write private site configuration and collect evidence **outside** this tree. Use fresh versioned installation paths and preserve existing service/data state.

The default P2P path is the dedicated minimal Dragonfly kit. Its bootstrap console login is root/dragonfly. Public core setup requires neither NGC nor MinIO; Rack's older full-stack P2P provisioning action is a separate unqualified integration. Check existing NVFTP assets before requesting credentials for any selected protected benchmark/model download.

Proceed with authorized preparation and compatible installation. Obtain missing actual host/SSH/OS/CPU/storage/inventory inputs before dependent steps. Keep Auto Trigger actions/recovery paused and run GPU jobs only within the user's supplied node/partition/workload/time/GPU scope. Do not borrow old source customer targets or fixed-fleet assumptions.

Record actual versions, checksums, commands, service state, acceptance results and rollback locations. Preparation tests and healthy endpoints are not IREN live acceptance. Read per-tool AGENTS.md files after extracting their source.
