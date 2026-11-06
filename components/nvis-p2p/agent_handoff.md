# IREN MKZ — minimal Dragonfly P2P deployment, revision 02

## Start here

This is the default **basic Dragonfly P2P** deployment kit. Run its Linux services on an approved IREN management host and its small peers on approved compute nodes. The Windows VM remains the PowerShell/Codex/Fortinet/OpenSSH/browser staging workstation. No WSL, Hyper-V, local Linux VM or Windows Docker installation is required.

The initial console username is **`root`**, password **`dragonfly`**. These are Dragonfly web credentials. They are unrelated to image-registry credentials. **Neither NGC credentials nor MinIO are required for this minimal deployment.** Rotate the bootstrap password after first acceptance. NGC/Hugging Face credentials are relevant only if a later selected workload/model payload must be downloaded from those services rather than an already verified NVFTP cache.

This kit provides Manager, scheduler, one seed, PostgreSQL 16, Redis, a real matching prebuilt web console and an HTTP file origin. Normal compute peers download through Dragonfly; direct payload fallback is disabled on peers. MinIO/native `dfstore` object persistence is an optional advanced architecture described in `optional/full-stack-agent_handoff.md`; that older full-stack path must not block this basic deployment.

Local qualification passed with the exact shipped Manager binary: real PostgreSQL/Redis/Manager/scheduler/seed/peer services, HTTPS console assets and cookie login, and a fresh peer receiving 14,800,000 bytes from a warm seed while the origin supplied only its one-byte metadata probe and zero bulk payload bytes. The payload SHA-256 was `ca71dbaa46ad0ee4d9423fa233a495ed67ba85fa1584fb5285b1281a5f059b8c`. Status and exact checks are in `evidence/VALIDATION.json`. Local isolated service/console/transfer qualification is distinct from live IREN installation and GPU validation, which were not performed.

## Source and compatibility changes

Source is the exact requested `https://gitlab-master.nvidia.com/nvis-ova/nvis-p2p`, main `229032db49b40ea011c755f972f4900207473720`; core upstream is Dragonfly 2.5.1, client 1.4.9. The source has the same customer-neutral packaging corrections recorded in revision 01. This revision makes two additional compatibility changes, explicitly recorded in `PROVENANCE.json`:

1. The unavailable old PostgreSQL digest is replaced with an **actually downloaded official PostgreSQL 16.15 Linux amd64 image**, pinned to observed digest `docker.io/library/postgres@sha256:b95b87e93ceb7594715d5c71fb6e09f6fc878851ab537735d617325eb9ba8b1b`. Its actual binary reports PostgreSQL 16.15 (Debian `16.15-1.pgdg13+2`). Actual Manager database migration/startup and console authentication are tested against this version. This is a local compatibility overlay, not an assertion that the unavailable old image was recovered.
2. Manager is a documented derivative `v2.5.1-iren-authfix.1` of pinned upstream commit `5523218a3710b2d5bc8fbdb0b1473d3a4d64916d`. The upstream global JSON query cache drops the password hash (`json:"-"`) from cached User rows, breaking repeated password login. The patch makes credential lookup bypass that cache while preserving password-hash secrecy, password verification, enabled/deleted-account rejection and other API behavior. Source patch, build provenance, regression evidence and final binary SHA-256 are included under `evidence/manager-authfix/`. Do not replace it with the old Manager merely because the old binary reports the original release version.

Scheduler and all client binaries retain their verified source-release pins. The console uses the matching prebuilt NVIS-branded Dragonfly frontend, served by nginx. Its core clusters/scheduler/seed/peer pages use Manager APIs. The old NVIS **Artifact Fleet** and **Dragonfly Settings** custom fleet operations are not enabled: `/nvis/api/` returns 403, and their historical 14-SU/288-node backend is not started. Use normal Dragonfly/core operations and the approved explicit IREN inventory; do not infer generic fleet readiness from those legacy menu entries.

## Included and required outside the ZIP

Included: source without Git history; Linux amd64 Manager/scheduler; Linux x86_64 clients and Linux aarch64 64-KiB-aligned clients; prebuilt console; all three required minimal runtime images (official PostgreSQL 16.15, existing pinned Redis, existing pinned nginx); standard-library render/preflight/image-load/console-check scripts; a site template; per-file SHA-256/mode manifest; provenance and test evidence. Docker archives are loaded by verified image-config ID and tagged locally so Compose never needs an external pull.

Not included: Linux OS; Docker Engine and Compose v2; Python 3; OpenSSL; Bash/coreutils/OpenSSH; a dedicated Linux service account; IREN VPN configuration; SSH/private credential files; site TLS keys; cluster/node inventory; benchmark `.sqsh` images. Prepare those OS prerequisites for the exact management/node distributions before the offline deployment. Management host must be **Linux x86_64**, have systemd, sufficient persistent disk and compatible runtime libraries for the shipped dynamic client. Windows architecture is not evidence of compute architecture.

## Approved inputs and placement

Use an approved non-production/management host and exact IREN controller, node/partition and test limits from the overall handoff. Stage over trusted SSH/SFTP after Fortinet is configured; never scan a subnet or reuse another customer's connection profile. All substantial origin/seed/peer data transfer stays within IREN. Do not put the canonical origin on Windows or require compute nodes to route back through the Windows VPN.

Extract this ZIP with executable modes preserved into a dedicated directory on Linux, for example `/srv/iren-mkz/nvis-p2p`. Set `install_root` to that exact extracted kit directory. Keep immutable staging separate from the private rendered `site/` and persistent `state/`. Verify the outer ZIP and `SHA256SUMS` before executing anything.

Create a private copy of `templates/site.example.json`. Set the actual compute-facing local IPv4 address, bounded compute-origin allow CIDR, existing dedicated service user/group and matching UID/GID, private one-line PostgreSQL password/JWT files and TLS certificate/key paths. The example documentation address is not a target. Set `console_port` if needed; default is **4301**, which avoids Observability's optional lake-browser port 4300.

Generate a fresh self-signed certificate with a **localhost SAN**, or use the approved CA. An example on the Linux management host is:

```bash
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout /secure/iren-mkz/p2p-localhost.key \
  -out /secure/iren-mkz/p2p-localhost.crt \
  -subj /CN=localhost -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' -days 365
chmod 600 /secure/iren-mkz/p2p-localhost.key
```

Generate independent random PostgreSQL/JWT strings into mode-0600 files; never print them to a chat/transcript or put private rendered files into a distributable ZIP. The renderer copies private runtime material into its mode-0700 output, owned by the configured service identity when run as root.

## Check, render and install the management backend

These commands run on the **approved remote Linux management host**, from the extracted kit directory. Replace the private config path with the actual approved path.

```bash
python3 scripts/load-images.py
python3 scripts/render-minimal.py --config /secure/iren-mkz/p2p-site.json
sudo python3 scripts/preflight-minimal.py --config /secure/iren-mkz/p2p-site.json
```

The first two verify inputs/archive hashes without starting services. Preflight is read-only and rejects incompatible platform, UID/GID mismatch, unbindable local IP, occupied ports, existing P2P containers/volumes/units and nonempty state/origin paths. It does not silently adopt or overwrite an existing installation. Review and back up existing deployments separately.

Load local images, then render into a **new private directory**, which must not already exist:

```bash
sudo python3 scripts/load-images.py --apply
sudo python3 scripts/render-minimal.py --config /secure/iren-mkz/p2p-site.json \
  --output /srv/iren-mkz/nvis-p2p/site
```

The `.yaml` files contain JSON, which is a YAML subset, so the offline target needs no PyYAML package. Review `site/site-plan.json`, Compose and the unit files privately. The output contains passwords/keys and must remain private. Set these shell variables for the remaining commands:

```bash
P2P_KIT=/srv/iren-mkz/nvis-p2p
P2P_SITE="$P2P_KIT/site"
```

Create `state/{manager/logs,manager/plugins,scheduler/logs,scheduler/plugins,scheduler/data,seed/logs,seed/plugins,seed/cache,seed/storage}` and an initially **empty** `origin/`, owned by the configured dedicated service UID/GID and mode 0750. Restore executable mode on the verified binaries if Windows extraction lost it. Do not recursively chown a shared container store or a parent such as `/srv`, `/opt` or `/`.

Validate Compose and prepare the two new persistent volumes only after the new-install preflight succeeds:

```bash
sudo docker compose -f "$P2P_SITE/compose.yaml" config --quiet
sudo docker volume create iren-mkz-p2p-postgres-data
sudo docker volume create iren-mkz-p2p-redis-data
sudo docker compose -f "$P2P_SITE/compose.yaml" up -d --pull never --wait --wait-timeout 90
```

Compose starts PostgreSQL, Redis and nginx. PostgreSQL/Redis have health checks; nginx provides the loopback HTTPS console and the bounded origin on the compute-facing address. It never pulls from a registry during this step. Copy the three generated units into `/etc/systemd/system`, then reload and start them in order:

```bash
sudo install -m 0644 "$P2P_SITE"/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iren-mkz-p2p-manager.service
sudo systemctl enable --now iren-mkz-p2p-scheduler.service
sudo systemctl enable --now iren-mkz-p2p-seed.service
```

A listener alone is not readiness. Wait for Manager to connect/migrate, for the scheduler's first keepalive to mark it active, and for the seed to register. The seed can initially report “available schedulers not found” before that keepalive; the unit retries every five seconds. Require it to become stable/active and visible in Manager before proceeding. Do not count indefinite restarts as success.

## Windows web access and root/dragonfly login

From Windows PowerShell, after the approved Fortinet route and trusted SSH alias exist:

```powershell
ssh.exe -N -T -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=yes `
  -L 127.0.0.1:4301:127.0.0.1:4301 iren-management
```

Open **`https://localhost:4301`**. Independently verify/trust the certificate fingerprint or CA; do not disable validation to hide a routing/certificate error. Sign in as **root / dragonfly**, verify the basic cluster/scheduler/seed views, then rotate the bootstrap password under Profile/Password and store it privately. Both local and remote port can be changed deliberately; a local forward port change alone does not resolve a remote listener collision.

The command-line browser-path smoke check verifies real static assets, three fresh cookie logins and authenticated cluster queries without printing JWTs:

```bash
python3 scripts/check-console.py --url https://localhost:4301 \
  --ca /secure/iren-mkz/p2p-localhost.crt --bootstrap
```

After rotation, replace `--bootstrap` with `--password-file /secure/iren-mkz/current-p2p-console-password`. Check that unauthenticated and incorrect-password requests are rejected. This is distinct from a complete interactive browser workflow or live fleet acceptance.

## One approved canary peer and verified file transfer

Prepare a peer JSON with the **exact approved** `hostname`, `node_ip`, `rack`, `architecture` (`x86_64` or `aarch64-64k`), actual `page_size`, and dedicated `peer_root` such as `/opt/containers/.nvis-p2p`. Check `uname -m`, `getconf PAGESIZE` and runtime library compatibility on that node. The aarch64 binary requires its tested 64-KiB page compatibility; never choose architecture from the filename of a workload alone.

```bash
python3 scripts/render-minimal.py --config /secure/iren-mkz/p2p-site.json \
  --peer-config /secure/iren-mkz/p2p-canary.json --output /srv/iren-mkz/p2p-canary-render
```

This contacts no node. Read the generated peer plan. Before any peer write, use approved SSH to that exact node for read-only checks: host-key verification, architecture/page size/runtime libraries, existing loaded peer unit, existing process/listeners, service UID/GID, directory ownership/mode, free space and existing cached content. Stop for an installed unit, conflicting binary/config or wrong owner; preserve state and review an upgrade rather than overwriting it. Never assume management-host preflight covers a node. Then copy only the correct hash-verified client binaries, `peer.yaml` and generated peer unit to that one node. Use the dedicated service identity and narrowly approved sudo. Preserve existing peer storage, valid images and receipts. Create the `bin`, `run`, `logs`, `plugins`, `cache` and `storage` subdirectories under the reviewed peer root, then install/start `iren-mkz-p2p-peer.service`. The peer `dfget` invocation also uses `--disable-back-to-source` to disable the CLI’s separate fallback path. The rendered compute configuration keeps `scheduler.enableBackToSource=false` and `proxy.disableBackToSource=true`.

For the first canary, stage only a small synthetic or independently verified file under `origin/`. Record its size/SHA-256. Warm the seed with its local socket, then request the same URL through the canary's local peer socket:

```bash
# Management host: warm its seed first.
source/dist/client-amd64-v1.4.9/dfget http://IREN_CONTROL_IP:12130/canary.bin \
  --endpoint "$P2P_KIT/state/seed/dfdaemon.sock" --output /tmp/iren-seed-canary.bin --timeout 60s
# Exact approved compute node, using its selected binary/root:
/opt/containers/.nvis-p2p/bin/dfget http://IREN_CONTROL_IP:12130/canary.bin \
  --endpoint /opt/containers/.nvis-p2p/run/dfdaemon.sock \
  --output /tmp/iren-peer-canary.bin --timeout 60s --disable-back-to-source
```

Compare exact bytes and SHA-256 on both outputs. Require seed/peer visibility, correct architecture, stable units, valid cache and correct byte count. The shipped HTTP backend obtains metadata using a one-byte `GET Range: bytes=0-0` probe (and may use HEAD/ETag/length in other paths) even when payload bytes are served from a cached peer. An unavailable IREN-internal origin is a different requirement from an Internet-disconnected cluster; do not make Internet access a dependency.

Do not start a fleet rollout, benchmark or GPU workload as part of this canary. Expand only after its evidence passes and against the explicit approved inventory. Workload images require separate architecture/recipe/size/hash verification; three old catalog/receipt disagreements remain relevant to those payloads, not to installing basic Dragonfly itself.

## Networking, persistence and rollback

Default internal endpoints: Manager gRPC12003, scheduler12002, scheduler metrics12001; seed upload12110, proxy12111, TCP storage12112, UDP12113, metrics12114, health12115, stats12116; origin12130. Normal peers use their rendered upload/storage/proxy/metrics ports12200/12202/12201/12204 (and configured UDP12203). PostgreSQL15432, Redis15379, Manager REST12004 and console4301 stay on management loopback. Apply the reviewed IREN firewall/CIDR policy; do not open every port broadly. Windows needs only its trusted SSH route for controls/tunnel plus one-time file staging.

Keep PostgreSQL/Redis named volumes, `state/`, private `site/` and verified workload artifacts persistent. Basic seed/peer caches are not the advanced MinIO/native-dfstore persistence service. For upgrades, preserve prior source/binary hashes, units and consistent metadata backups; review schema compatibility before reverting a database version. Stop admission of new operations, test one canary and preserve existing cache/images/receipts. No broad data deletion or cluster state change is part of rollback.

Rack Status can query/use this separately installed P2P instance through the reviewed cluster settings. Do not blindly use its old provisioning workflow or old binary `artifacts.lock` to overwrite the auth-fixed Manager: that lock names the original buggy Manager. Any future integrated provisioning update must carry the explicit new Manager digest and its compatibility evidence.
