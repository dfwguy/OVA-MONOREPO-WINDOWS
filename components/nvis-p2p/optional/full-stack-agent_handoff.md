> Historical optional full-stack path. For basic Dragonfly installation use ../agent_handoff.md. Its MinIO/originalPostgres dependency holds do not apply to the revision02 default minimal kit. This appendix describes advanced native-dfstore persistence and is not the default installer.

# IREN MKZ — NVIS P2P agent handoff

## Identity, contents and release state

Source: `https://gitlab-master.nvidia.com/nvis-ova/nvis-p2p`, main commit `229032db49b40ea011c755f972f4900207473720`. Dragonfly core is 2.5.1; clients 1.4.9; NVIS release 2.5.1-nvis.2. Git LFS files were materialized and their eight actual binary hashes match the independent pin set in the exact Rack Status repository's `deploy/p2p/artifacts.lock`. No P2P CI pipeline was advertised for the captured source. See `PROVENANCE.json`, `FILE_MANIFEST.json`, `SHA256SUMS`, and `evidence/VALIDATION.json`.

This is a staged candidate with a **paused, fail-closed offline installer**. It is not a dependency-complete or live-accepted fleet release. Three workload catalog digests remain inconsistent with historical NVFTP transfer receipts; two exact support service image pins could not be fetched. Do not start cluster mutation by running arbitrary legacy scripts because a ZIP exists.

`source/` contains source and Linux binaries without Git history, runtime credentials or customer inventory. Historical deployment PDFs/screenshots were omitted; known deployed IP/path examples were replaced with documentation addresses. These changes are recorded. Public `release/components.env` was restored from the prior audited deployed release and verified against shipped binary bytes; the console's default root was corrected for an extracted checkout. The renderer now creates its TLS output directory before copying supplied certificates. Release file/checksum manifests were regenerated after edits.

## Purpose and placement

P2P distributes large workload/container files once within the IREN data-center fabric using Dragonfly Manager/scheduler, seed peers, a controlled origin and dfstore/MinIO persistence. Compute nodes run lightweight Dragonfly peers and reconciliation units. It does not validate GPU performance by itself.

The Windows VM is a staging/control workstation: Codex in PowerShell, Fortinet VPN, OpenSSH, file checksums and browser. No Windows P2P server executable is provided. Do not require WSL, Hyper-V, Docker Desktop or a local Linux VM. Upload the selected files over SSH/SFTP after VPN and target identity checks. Run the backend services on an approved **Linux x86_64 IREN management/application host**, and peers on the approved IREN nodes.

Keep bulk origin/object-store/seed/peer traffic **inside IREN**. Do not make cluster peers depend on a Windows VPN client address, its reverse NAT or a route back into NVIDIA. Cross the VPN once to stage payloads and control operations; do not fan hundreds of gigabytes back across it per node. Windows VPN connectivity alone is not proof that any peer can reach a management service.

## Architecture and dependencies

Management/app host: Linux x86_64; Docker Engine + Compose v2; Python 3; Bash, coreutils, util-linux/flock, OpenSSH, rsync; systemd; an approved existing dedicated service identity; persistent object and seed storage; TLS cert/key for MinIO; exact canonical workload files/catalog; a reviewed inventory. Manager/scheduler are statically linked x86_64 Go binaries; clients are dynamic Linux ELF. The client runtime libraries must exist on actual seed/compute OS. Inspect `ldd` and reject missing libraries before starting services.

Compute binaries included:

- `dist/client-amd64-v1.4.9/{dfdaemon,dfget,dfstore}` for Linux x86_64.
- `dist/client-arm64-64k-v1.4.9/{dfdaemon,dfget,dfstore}` for Linux aarch64 with **64 KiB** ELF load alignment. Check `uname -m`, `getconf PAGESIZE`, interpreter and `readelf -lW`; do not deploy this build to arbitrary ARM systems without compatibility verification.

No workload `.sqsh` images are inside this kit. Those are a separate, potentially hundreds-of-gigabytes, architecture/workload-specific payload selection. A filename, byte count or old receipt alone is not a current payload hash verification.

Support service images in `offline/image-inventory.json`:

| Service | Exact source pin | Staged result |
| --- | --- | --- |
| Scheduler base | `ubuntu@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517` | Linux amd64 archive staged |
| Redis | `redis@sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf` | Linux amd64 archive staged |
| Origin/console base | `nginx@sha256:72ba65eb42c10344912a84ff42408db7d34f2feb642204570ab8fc5ffd29f1d3` | Linux amd64 archive staged |
| PostgreSQL | `postgres@sha256:2992a3f8fd266125e19507a5ab9efa95ba0ec0a88688341354015b897147234d` | Not staged: manifest unknown on Docker Hub, NVIDIA mirror and ECR mirror |
| MinIO | `quay.io/minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e` | Not staged: registry unauthorized; alternate Docker Hub path denied |

A registry denial does not prove an image is absent. Obtain an authorized export of the exact image from its owner, or review/select a replacement pin with compatibility/security evidence and update the manifest. Never quietly replace it with `latest`. Both the standalone release and Rack Status's P2P provisioning use these dependencies.

The successful archives are Docker archives with no retained repository digest tags. The installer therefore checks their archive hashes, checks the loaded config IDs, applies per-image receipt-recorded local tags, rewrites only the rendered Compose image fields and uses `--pull never`. This avoids an apparently offline deployment performing an unexpected registry pull.

## Site contract

Copy `source/configs/cluster.env.example` to a private, non-published file. Set all fields from approved IREN data. The reserved example addresses are deliberately unusable as production targets. Required fields include install root; existing service user/group and matching UID/GID; compute-facing Manager and appserver IPs; console loopback binding; explicit inventory source/pattern and NVIS_COMPUTE_CIDR origin allow-list; canonical image/catalog paths; peer path; persistent object/seed paths; secret file references; TLS certificate/key references; and systemd directory.

Secret files must be mode 0600 or stricter and stored outside shared staging. They contain PostgreSQL password, Manager JWT key, MinIO root password and **read-only** dfstore export settings. Use a separate server-only import credential. Set the dfstore endpoint to the **actual published TLS object API**, normally `https://<IREN appserver>:19000`, with trusted CA and valid hostname/IP SAN. Port `9000` is the MinIO container-internal listener; it is not the host's published port. Never copy the import/root credential to compute nodes.

Validate host/compute routes, exact roster, SU mapping, disk budget, service account ownership and narrowly required sudo before mutation. A seed/origin can contact controlled source; compute peers must have back-to-source disabled. Preserve valid images, receipts, peer cache, seed cache and object-store data across upgrades.

## Default read-only report and paused install

On the approved Linux management host, after verifying the package:

```bash
python3 scripts/control-plane.py
```

With the delivered inventory this exits **78**, enumerating the two unavailable exact images. `--install` follows the same gate and also exits 78 **before any subprocess or persistent filesystem write**. This behavior is verified offline. Do not treat that as a deployed backend or suppress it to force progress.

Once the exact missing archives have been obtained, independently verified and added with their source reference, archive SHA-256, config ID and local tag to `offline/image-inventory.json`, review the updated outer manifest and run:

```bash
sudo python3 scripts/control-plane.py --install --env /secure/iren-mkz/p2p.env
```

The installer is an explicit **new-install**, co-located management/appserver path. Both configured addresses must bind locally, service ports must be free, and `/etc/systemd/system` is the supported unit directory. It rejects symlink ancestry, `..`, broad data/origin/cache roots, nonempty data/cache/origin directories, fixed container/volume names and installed/loaded unit collisions. Start with an empty approved origin and add only independently verified workload payloads after service acceptance. It refuses an existing `<install-root>/current` or unit name collision, requires an existing matching dedicated service account, explicit TLS files, real target IPs and Linux x86_64. It validates the renderer and Compose before writing an isolated timestamped release. It creates the `current` symlink; installs only Manager and both seed units; starts PostgreSQL/Redis; waits for the loopback Manager REST listener; starts scheduler, object store and origin; then starts both seeds. All Compose starts use `--pull never`. It does not change Slurm, install GPU software, drain nodes, import workload images, deploy peers, start a fleet rollout or activate the standalone console API. Service startup requests are not acceptance: run independent health/TLS/API checks afterward.

This post-gate install path was reviewed and statically checked but not executed against a real management host; registry failures prevent a complete local stack test. Keep the exact command output and partial-install state on any failure. The installer never deletes existing image/cache data as cleanup. Do not rerun it over an existing `current`; inspect the transaction and use a reviewed upgrade/recovery procedure.

## Integration with Rack Status

The Rack Status kit can stage these same verified binaries into its P2P asset tree:

```bash
P2P_ARTIFACT_SOURCE_DIR=/absolute/path/to/this-kit/source/dist \
  /absolute/path/to/rack-kit/source/deploy/p2p/bin/stage-artifacts.sh
```

This is an offline copy/hash step, not deployment. Configure one Project/Cluster record for IREN and one P2P instance, with backend credentials/paths local to that Linux gateway. The Rack Status UI is the preferable long-term inventory/catalog control surface, but its upstream `nvis-p2p-provision` workflow is **not complete end-to-end acceptance**: it runs Compose bring-up but does not install/start the separate Manager/seed systemd units, and its generated readonly dfstore endpoint defaults to HTTP/9000 rather than the host's published TLS/19000. Use the gated kit installer and the explicit dfstore endpoint above for this delivery; do not run the upstream provisioning workflow unreviewed. A future release should integrate those changes into the owning workflow mechanism and requalify it.

The standalone `services/console-api` and several legacy fleet scripts retain site-specific 14-SU/288-node inventory assumptions and hostname guards. These are not adapted by simply substituting an IP. The kit intentionally starts neither that API nor the standalone fleet controls. Do not rename arbitrary IREN hosts to satisfy a legacy guard. Use the reviewed Rack Status per-cluster model or implement/test an explicit inventory adapter before enabling those controls.

## Container catalog integrity gate

Do not import/distribute the following ARM payloads from this kit's default catalog until current remote bytes have been recomputed and reconciled with authoritative release metadata:

- `nvbandwidth-v0.9-arm.sqsh`: catalog starts `e1d1a983…`; preserved receipt starts `0b275fd4…`.
- `nvidia+hpc-benchmarks+26.02-arm.sqsh`: catalog starts `cf1281e8…`; receipt starts `b84a6b2b…`.
- `nvidia+nemo+26.04.01-arm.sqsh`: catalog starts `8b79bc8e…`; receipt starts `55130500…`.

Keep the original disagreement as evidence. Do not fix a digest by trusting whichever copy is most convenient. Confirm architecture, image format, byte count, SHA-256, recipe compatibility and storage budget for the actual IREN hardware. Make JSON and TSV agree after reviewed reconciliation and regenerate the release manifest. A standalone P2P service control plane can be installed before workload distribution is qualified, but peer distribution must stay paused.

## Network and operational acceptance

Windows needs trusted SSH/SFTP to the management host over Fortinet; browser access is via loopback SSH forwarding. Compute-facing services stay within IREN: Manager gRPC12003, scheduler12002, configured scheduler metrics12001; seeds use configured12110/12120 and piece/download/health ports from their YAML; MinIO host object API19000; controlled origin12130; peers use configured12200/12201/12202/12204. Read the rendered configs for the exact listeners/protocols rather than opening this entire list indiscriminately. MinIO admin19001, PostgreSQL15432, Redis15379, Manager REST12004 and optional console-operations14300 remain loopback. Enable only required approved interface/port flows; no peer callback to Windows is assumed.

Require, in order: dependency/runtime checks; exact binaries; reviewed redacted renderer output; Compose config; healthy database/Redis; Manager API and scheduler; MinIO **HTTPS** including authenticated readonly/import policy separation; controlled origin; both seed sockets/readiness; independent canonical payload hashes; one approved canary peer; one digest-verified native dfstore import/export; reboot/reconcile persistence; then bounded expansion across the explicit approved roster. Verify actual file bytes and SHA-256 receipts, not service active/file presence alone. Track requested/eligible/complete/deferred/unreachable counts and exact exceptions.

Rollback starts by stopping new P2P operations and waiting for active transfers to reach a safe point. Preserve previous source/config/unit definitions and a consistent metadata backup. Restore one canary first. Keep existing images, receipts, quarantine, caches, object-store and database data. No shared-data deletion is authorized by this handoff.
