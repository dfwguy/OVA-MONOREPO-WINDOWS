# Windows validation and commissioning status

The native software scopes below passed on real Windows hosts. This release does not certify customer connectivity, all upstream feature parity, persistent service installation, GPU execution or reboot/power-loss recovery.

| Scope | Actual result | Authoritative evidence |
| --- | --- | --- |
| Control delivery | 7 checks passed on Server 2019 / PowerShell 5.1, pipeline 79725803, job 531758252 | [CI receipt](evidence/windows-control-ci.json), [summary](evidence/windows-control-ci-summary.json) |
| Exemplar preparation and one-node orchestration | 9 tests passed on native Server 2025 / CPython 3.12.10; transports mocked, no jobs submitted | [Native compatibility](docs/NATIVE_WINDOWS_COMPATIBILITY.md) |
| Rack Status and P2P console/proxy | 21 tests passed, zero failures/errors/skips; fresh offline environments, TLS/WebSocket auth/origin checks, full 45-second stability, ConPTY, locks, workflow guard and mock Manager | [Acceptance](evidence/native-rack-p2p-acceptance.json), [source binding](evidence/native-rack-p2p-source-binding.json) |
| Observability | 7 checks passed using four real native processes, authenticated APIs, actual metrics/log ingestion and restart persistence | [Acceptance](evidence/native-observability-acceptance.json) |
| Collection | 6 tests passed, zero skips; real process locks, held-reader replacement contention, read-only denial, concurrent generation publication and authenticated ingest/query/export/restart | [Acceptance](evidence/native-collection-acceptance.json), [source binding](evidence/native-collection-source-binding.json) |
| Optional runtime prerequisites | Three binaries matched pinned hashes; Python installer signature valid; WinSW binaries unsigned as documented | [Windows verification](evidence/runtime-prerequisites-windows.json) |

Tests used isolated runtime directories and retained the existing Rack and P2P services. The recorded first failed attempts remain available; their corrected reruns, rather than preparation claims, establish the final results. Read profile-specific receipts for exact assertions and exclusions. The source-binding report separates a metadata-only canonical build-receipt ordering correction from the application bytes used in the Rack/P2P runtime tests.

## Deployment boundaries

- **P2P:** the Windows console/proxy is qualified within its stated scope. Dragonfly Manager, scheduler, seed, PostgreSQL/Redis and peers remain Linux-side. No WSL or local Linux VM is used.
- **PythonCM:** inventory capability does not establish ProgramRunner/workflow execution equivalence. Unqualified PythonCM workflow submissions fail closed; environment/user/launch-mode and execution-session contracts need separate qualification.
- **Observability:** the native profile uses Prometheus in place of the original VictoriaMetrics deployment. Full legacy dashboard/plugin/lake parity is not established. Loki required a recorded forced-stop fallback; restart persistence passed, graceful Loki shutdown is unqualified.
- **Customer connectivity:** corrected probes with the original jump chains and strict trust checks timed out. No changed SSH host key was established. An approved FortiClient connection and operator authentication are still required before BCM/app-server acceptance. No credentials, trust bypass or firewall changes are included.
- **Service and workload commissioning:** WinSW/Task Scheduler definitions are supplied, with action scheduling disabled. Persistent SCM installation, reboot recovery, customer collectors, real GPU jobs and cluster-wide operations were not performed by these isolated tests.

## Source and publication integrity

The original NVFTP release was checked against its release index. Intake removed six generated Rack credential/runtime files and rebuilt affected toolkits/manifests; see [sanitation evidence](evidence/sanitization-removals.json), [artifact provenance](evidence/sanitized-artifact-provenance.json) and [component integrity](evidence/published-component-integrity.json). Existing deployed credentials were not rotated by this packaging work.

The [bounded recursive scan](evidence/recursive-secret-scan.json) records coverage and classified vendor/test matches. A vendor PostgreSQL image retains its standard example snakeoil key; it must not be used for production TLS. This is not an exhaustive security certification.

The offline release builder creates an embedded `RELEASE_MANIFEST.json` with every shipped file's SHA-256 and size, rejects unsafe paths and external links, and excludes Git metadata, runtime secrets, caches and duplicate top-level archives. Its verifier checks the actual archive payload against that manifest. Source, offline dependencies, guide, PDF, NVIDIA assets and acceptance evidence are included.

The [23-page operator PDF](docs/OVA-MONOREPO-WINDOWS-User-Guide.pdf), [PDF checks](docs/PDF_VALIDATION.json) and [branding provenance](docs/branding/ASSET_PROVENANCE.json) accompany the source. The animated diagram explicitly shows the Linux P2P core and commissioning boundaries.

## Native checkout storage policy

The versioned `.lfsconfig` limits default Git LFS downloads to `windows/**` and `control/windows/**`. Native Windows builds retain their existing commands and pinned payload bytes. Historical control acceptance automatically materializes `control/**`; the offline release builder automatically materializes `control/**`, `components/**` and `windows/**` before its existing manifest checks. It continues to exclude the duplicate top-level control archive and both historical Linux observability packs. Full offline releases need no Git/LFS/network at deployment.

This changes retrieval and packaging preparation, not accepted application inputs, immutable component manifests or runtime behavior. Earlier Windows receipts retain their original scope; they do not establish Windows acceptance of this retrieval change. Existing clones keep downloaded payloads and caches. The published `2026.11.06-native-r1` Generic Package Registry release is preserved, including its SHA-256 and provenance; it predates this checkout policy.

[Checkout storage verification](evidence/native-checkout-storage.json) records a real fresh local clone at **1.13 GiB**, about **86% less** than the original 8.1 GiB workspace, including independent Git/LFS storage. Rack/P2P input verification passed on that clone; all six historical control tests passed after automatic hydration; the full release plan fetched its remaining inputs and preserved component manifest integrity. The root suite passed 26 tests, and GitLab CI configuration lint passed. These are local preparation checks, not a new Windows runtime or commissioning receipt.
