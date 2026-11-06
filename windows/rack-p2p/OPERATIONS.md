# Native Rack Status and P2P console source assembly

This folder preserves a reviewed source export from the actual Windows VM and builds a fresh native Rack Status source tree from the exact packaged base. It also stages the Windows P2P console/proxy source and matching static UI. It does not install or modify existing services, copy installed state, import a customer inventory, execute a cluster command or port the Linux P2P core.

The immutable `adapters/` export contains 92 files including its self-exempt manifest: 37 native Rack modifications, 13 additions, 24 PythonCM support/reference files, four Windows P2P console files, five explicitly Linux-only compatibility files, seven portable handoff files and one validation record. Every recorded base hash matched the sanitized packaged base; each exported file matched its export hash. See `INTAKE_REVIEW.json`, `adapters/PROVENANCE.json`, `adapters/SANITIZATIONS.json` and `adapters/PYTHONCM-CAPABILITY.json`.

## Verify and assemble a fresh version

Use a complete source checkout with LFS objects materialized. The builder needs `components/nvis-rack-status/FILE_MANIFEST.json`, its `source/` files, and `components/nvis-p2p/FILE_MANIFEST.json` plus `console-static/`. It validates these pinned manifests and source hashes, the immutable adapter manifest, every adapter byte count/hash, the explicit guard patch and the Windows wheelhouse. It does not trust a filename or commit label in place of the actual bytes.

```powershell
Set-Location C:\OVA\windows\rack-p2p
$python = Join-Path $env:LOCALAPPDATA 'OVA\Python312\python.exe'
& $python .\build_runtime.py --verify-only
& $python .\build_runtime.py --destination C:\OVA-Versions\rack-p2p-v1
```

The destination must be new and outside the checkout. The builder stages into a sibling temporary directory and renames it after verification, preserving existing versions. It copies only reviewed base source, overlays the exported files, retains matching frontend assets, and records all 2,214 output files in `BUILD_RECEIPT.json`. Two independent local builds produced identical receipt bytes and output hashes. Credentials, `var/secrets`, runtime logs/state/cache and unlisted source files are rejected or never copied. Python bytecode caches are excluded. Known Unix modes are retained on POSIX builders; Windows/head deployment must explicitly preserve the helper modes recorded by the source manifests.

The assembled tree contains:

- `rack-status/`: the native Windows backend adaptation and matching base SPA.
- `p2p-console/windows-control/`: native Windows static serving/Manager proxy source.
- `p2p-console/console-static/`: matching reviewed Dragonfly UI assets.
- `config-examples/`: customer-neutral examples requiring private site values.
- `CAPABILITIES.json` and `BUILD_RECEIPT.json`: the actual build boundaries and identities.

The five Linux-only P2P compatibility changes stay preserved under `adapters/p2p/linux-compatibility-overlay`; the Windows builder does not silently apply them to a Windows management core.

## Offline CPython 3.12 x64 dependencies

`wheelhouse/` contains 78 wheels matching the VM's exported, fully hashed native Windows lock. Each file also matched its official PyPI release-file SHA-256. `WHEELHOUSE.json` records measured sizes, hashes, package metadata, license locations retained within the wheels and original PyPI asset URLs. An independent metadata check found no unsatisfied active requirements for CPython 3.12/Windows x64.

`requirements-rack-cp312-win_amd64.lock` is an unchanged copy of the exported Windows lock. `requirements-p2p-cp312-win_amd64.lock` contains the separate 16-package transitive closure for the P2P proxy's four direct requirements; it uses the same verified wheelhouse. The P2P closure also passed a network-disabled `pip download --require-hashes` check against only the staged files.

Create separate virtual environments outside Git; these commands install packages only into the chosen new environments:

```powershell
$runtime = 'C:\OVA-Runtime\rack-p2p-v1'
if (Test-Path -LiteralPath $runtime) { throw 'Choose a new runtime directory.' }
& $python -m venv (Join-Path $runtime 'rack-venv')
$rackPython = Join-Path $runtime 'rack-venv\Scripts\python.exe'
& $rackPython -m pip install --no-index --find-links .\wheelhouse --require-hashes --only-binary=:all: -r .\requirements-rack-cp312-win_amd64.lock
& $rackPython -m pip check
& $python -m venv (Join-Path $runtime 'p2p-venv')
$p2pPython = Join-Path $runtime 'p2p-venv\Scripts\python.exe'
& $p2pPython -m pip install --no-index --find-links .\wheelhouse --require-hashes --only-binary=:all: -r .\requirements-p2p-cp312-win_amd64.lock
& $p2pPython -m pip check
```

Use the optional full CPython installer in `../runtime/` when a compatible approved runtime is absent. Do not use the original Linux wheelhouses for Windows. The shared base requirements still include Gunicorn; native Windows serving uses Cheroot and does not claim Gunicorn is a Windows server.

## Native serving and private configuration

Read the base project's instructions and the preserved export README before selecting commands. Rack's `windows/Start-RackStatus.ps1` starts its native Cheroot HTTPS application; its TLS/WebSocket adapter exposes the real socket through the existing authenticated middleware. Its Windows ConPTY and kernel byte-range lock implementations preserve real process and concurrency behavior. They are not no-op replacements for POSIX interfaces.

Supply a private configuration file, exact interpreter path, trusted SSH identity/known-hosts, site inventory and TLS/bootstrap inputs. Keep generated secrets and state under protected runtime directories. The exported `C:\NVIS` values are reusable examples, not deployment discovery. Review every source installer path and service ID before use. The package does not run `Install-RackStatusService.ps1` or `Install-ConsoleService.ps1`; those scripts register/start services and can collide with existing service names. Use isolated tests first and never run them against the already deployed VM merely to validate source.

The supplied WinSW `.NET461` variant under `../runtime/` matches the saved actual VM wrapper hash; it requires a compatible installed .NET Framework. A separately supplied standalone x64 wrapper is an alternative requiring its own lifecycle qualification. Matching the wrapper version does not establish service account/ACL/SSH identity correctness.

## Explicit PythonCM execution boundary

Read-only PythonCM inventory support is distinct from workload execution. The Windows process uses existing SSH transport and matching SDK helpers on the BCM head; it does not import a version-locked PythonCM SDK locally.

The reviewed VM export identifies two concrete execution gaps: the workflow's `JobSpec` construction omits explicit `env`, `launch_mode` and `execution_user`, while its saved real ProgramRunner probe rejected the execution-session cookie. Successful inventory access did not qualify task submission/status/cancellation/results. ProgramRunner command fanout also does not implement Slurm GPU/GRES/exclusive reservation semantics, and `SBATCH` comments or Slurm-only script bodies do not become a native PythonCM workload contract.

The builder applies one explicit execution-policy patch only to the fresh output's `backend/workflow_engine.py`. Before `sched.submit(spec)`, it rejects `sched.kind == "pythoncm"` with the known forwarding/session qualification reason. There is no override switch. The immutable exported source and packaged base stay unchanged. Inventory and other providers remain separate capabilities; the Slurm workflow boundary retains identical outputs and job arguments in the focused regression test. This does not qualify Slurm on a particular customer cluster.

`patches/pythoncm-workflow-guard.json` pins the exact preimage, replacement and resulting source hashes; the companion `.patch` is a readable diff. A changed preimage fails the build. Tests prove PythonCM never calls `submit`, the Slurm boundary is unchanged and a modified preimage is rejected. Low-level helper presence is not permission to invoke it or evidence that live PythonCM execution works.

## P2P scope

The Windows proxy serves the matching console and forwards only Manager HTTP API traffic over the Windows-initiated trusted SSH tunnel. It does not run Dragonfly Manager, scheduler, seeds/peers, PostgreSQL, Redis or origin/nginx natively on Windows. Those core and data-plane components retain their documented supported Linux placement. Use private configuration matching the source's loopback/TLS boundary. Mock proxy tests do not establish a successful real Manager login or seed/peer transfer.

## Fresh isolated Windows acceptance

```powershell
& $python .\acceptance.py --runtime-root C:\OVA-Acceptance\native-rack-p2p-unique
```

This command requires native Windows x64 CPython 3.12 and a new external directory. It restricts runtime ACLs, verifies/builds source, creates two new virtual environments, installs only staged fully hashed wheels with no index, runs `pip check`, and exercises the real kernel lock implementation, TLS/WebSocket transport, ConPTY input/resize/cleanup, the fail-closed workflow boundary and the P2P proxy's loopback mock Manager boundary. It scrubs inherited customer tool configuration and writes `acceptance-result.json` plus protected diagnostic logs. It does not register services, change existing VM services, import customer state, create a real BCM execution session or contact the customer cluster.

The native TLS/WebSocket test uses a generated temporary fixture certificate and a synthetic application; it does not replace full application SRP/login/SSH/head-terminal acceptance. The full configured UI/auth and service identity still require their separate fresh-install check. `VALIDATION.json` distinguishes the preparation checks, exporter-recorded Windows tests and actual fresh Windows acceptance receipt. Preserve failed receipts and inspect their private logs before changing source.


## Derived test-only cleanup correction

The first actual fresh Windows run encountered one harness error after16 unit-test passes across its main and separately run follow-up checks. A successful TLS/WebSocket echo was followed by a normal peer close (reason1000) racing the client cleanup call. This was not recorded as an overall passing run. The immutable VM export stays unchanged. A second deterministic, derived test-only patch (`patches/native-tls-test-normal-close.json` and its readable diff) permits only `ConnectionClosed` reason1000 from the client `websocket.close()` cleanup. Unexpected close codes such as1006 and unrelated exceptions still fail. Echo, authentication, origin checks and the full45-second service-health loop are unchanged. Four focused cleanup-policy tests cover this boundary. The official isolated Windows harness must be rerun in full on this revision; passing follow-ups do not replace that receipt.
