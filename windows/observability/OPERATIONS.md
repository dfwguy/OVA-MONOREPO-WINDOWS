# Native Windows observability core

This profile runs Grafana OSS 11.1.4, Prometheus 2.54.1, Loki 3.5.12 and Grafana Alloy 1.5.1 as Windows x64 processes. It preserves the component versions in the supplied Linux observability delivery. It uses no WSL, Linux containers or remote Linux backend for these four services. The original control bundle and Linux profile remain separate.

This is a bounded native core implementation. An isolated health test establishes process and telemetry flow on the tested Windows host; it does not establish customer commissioning, fleet capacity, reboot recovery or compatibility of every historical dashboard. See `VALIDATION.json` and the actual private acceptance receipt for what ran.

## Prerequisites and dependency verification

Use Windows x64, a 64-bit Python 3.10 or newer interpreter, an NTFS runtime volume, and permission to start user processes and set ACLs on a new private runtime directory. No administrator privileges, Windows service installation or firewall changes are requested. Keep the launching console open during use; this profile does not install unattended service supervision.

`DEPENDENCIES.json` pins four official Windows ZIPs, their upstream download/checksum URLs, exact SHA-256 and measured sizes. The downloaded archive set is approximately 395 MB; allow additional room for extraction, logs and retained telemetry. Each archive matched its publisher checksum over HTTPS. No Authenticode or detached signature verification is claimed.

```powershell
Set-Location C:\OVA\windows\observability
python .\native_core.py verify
```

All archives are already staged under `dependencies/`; runtime startup performs no network download. Missing or modified bytes fail before execution. Official release licenses remain inside the ZIPs and extracted binary directories. These are compatibility pins from the supplied source, rather than a claim that the versions are the vendors' current releases or have undergone a new vulnerability qualification.

## Start and stop

Select a new runtime directory outside the source checkout. Keep private site discovery/configuration, databases, user identities and logs there. Preparation refuses an existing directory; normal restart accepts its previously prepared profile and preserves data. The first initialization restricts the directory ACL to the current Windows account and SYSTEM.

```powershell
.\Start-NativeObservability.ps1 -RuntimeRoot C:\OVA-Runtime\observability -PortBase 18000 -PythonExe python
```

The startup wrapper securely prompts for the `ova-admin` Grafana password; use at least 16 characters. Automated launch can supply `OVA_OBS_ADMIN_PASSWORD` through a private environment. The wrapper restores that environment afterward; the supervisor sends the secret only to the Grafana child environment. It does not write the plaintext password to the profile or source. Grafana persists its normal credential database under the private runtime directory. The bootstrap environment sets the initial password only; it does not reset an existing database's password.

The supervisor verifies archive/executable hashes, checks native configurations, refuses occupied ports, then starts the four processes. `profile.json` records executable identities, ports and binary hashes; `processes.json` records kernel creation times and paths for owned PIDs. A directory lock prevents concurrent operations on the same runtime. If a crash leaves a lock, first establish that no operation is active, then remove only that profile's `.NAME.ova-observability-operation.lock` directory in its parent.

| Offset from PortBase | Default | Service |
| --- | --- | --- |
| +1 | 18001 | Grafana browser and authenticated API |
| +2 | 18002 | Prometheus API and remote-write receiver |
| +3 | 18003 | Loki HTTP API |
| +4 | 18004 | Loki internal gRPC |
| +5 | 18005 | Alloy readiness and metrics |
| +6 | 18006 | Alloy Loki push `/loki/api/v1/push` |
| +7 | 18007 | Alloy remote write `/api/v1/metrics/write` |

Every listener binds to `127.0.0.1`. Open `http://127.0.0.1:18001` on the Windows VM. Grafana anonymous access and sign-up are disabled. Prometheus, Loki and Alloy ingestion remain unauthenticated inside this loopback boundary. Remote access requires an approved authenticated tunnel or separately reviewed TLS/authentication ingress; changing a listener to `0.0.0.0` is not part of this profile.

```powershell
.\Stop-NativeObservability.ps1 -RuntimeRoot C:\OVA-Runtime\observability -PythonExe python
```

Stop checks each kernel creation timestamp and executable path before acting; it refuses PID reuse or paths outside the profile's binaries. It requests a console control break, waits five seconds, and uses bounded process termination if a child does not stop. The receipt reports whether the fallback was necessary. That fallback is not a proof of graceful database shutdown; restart/durability qualification remains separate. State and telemetry are preserved, and unrelated processes are untouched. Closing the launching console is not an unattended-service lifecycle guarantee. This profile does not install WinSW/NSSM/SCM services or promise automatic reboot start.

## Metrics, logs and cluster collectors

Prometheus scrapes the four local services every five seconds. `config/targets/cluster.json` starts as an empty file-discovery list, so no cluster or historical customer endpoint is contacted. The native core dashboard shows the local scrape targets.

The Windows VM can later pull approved Linux node/DCGM/other exporter endpoints over the configured customer VPN. Put only authorized targets and labels into the private runtime discovery file, for example:

```json
[{"targets":["APPROVED_EXPORTER_HOST:9100"],"labels":{"cluster":"APPROVED_CLUSTER","job":"node-exporter"}}]
```

Replace placeholders in private configuration; never run against placeholders or copy a previous customer's inventory. Linux GPU/RDMA/DCGM exporters and scheduler collectors stay on their supported cluster hosts. This profile supplies Windows storage/UI/gateway processes; it does not convert Linux GPU or InfiniBand collectors into Windows processes.

Log collectors and remote-write clients need a permitted route to the Windows ingestion boundary. The default does not expose a VPN listener or open Windows Firewall. Use an approved authenticated tunnel/gateway and verify that topology separately before collector enrollment.

Alloy's local metric receiver forwards to Prometheus; its log receiver forwards to Loki. This native profile uses Prometheus for metrics storage because the original VictoriaMetrics Linux container is not a Windows binary. Grafana's `nvis-victoriametrics` and `nvis-otel-victoriametrics` datasource UIDs are explicitly named compatibility aliases pointing at Prometheus. They do not implement VictoriaMetrics-specific APIs or MetricsQL. No VictoriaMetrics process runs here.

## Isolated native acceptance

Use a fresh runtime directory and an external receipt location. A successful run starts real Windows executables and tests real HTTP/data paths; it does not reuse a preexisting observability instance.

```powershell
.\Test-NativeObservability.ps1 `
  -RuntimeRoot C:\OVA-Acceptance\observability-unique `
  -ReportPath C:\OVA-Acceptance\observability-unique-result.json `
  -PortBase 19000 -PythonExe python
```

The test generates an ephemeral Grafana password in memory, verifies all four readiness endpoints, authenticates to Grafana, posts a real Snappy/protobuf remote-write sample through Alloy and queries it in Prometheus, posts a uniquely marked log through Alloy and queries it in Loki, checks provisioned Grafana dashboard and datasource health, then stops owned processes. A nonzero return or cleanup failure means failure. Logs and databases remain in the private test directory for diagnosis; the receipt contains no password. Import only a reviewed, redacted receipt into shared evidence.

## Limits and remaining qualification

- The 106 historical dashboards, Infinity plugin, data-lake writer/browser, DuckDB/Parquet paths and backend-specific queries are not automatically restored or qualified by this four-service profile. One native-core dashboard is supplied. Review and import compatible dashboards after qualifying their real datasources.
- There is no production-scale capacity, retention, disk-exhaustion, backup/restore, service-account, reboot or high-availability qualification. Prometheus local retention is two days; Loki local filesystem retention is seven days.
- Native configuration checks and isolated telemetry success do not establish a working customer VPN, correct BCM/app-server discovery, correct collector labels, complete cluster capture or GPU validation.
- Prometheus remote-write reception is provided for this bounded profile; it is not evidence that Prometheus reproduces VictoriaMetrics' scale or semantics.
- TLS/authentication gateways, site certificates, service supervision and collector enrollment require actual site inputs. No credentials, private keys or customer inventory belong in this source directory.

## Official implementation references

- [Grafana standalone Windows installation](https://grafana.com/docs/grafana/latest/setup-grafana/installation/windows/) and [the pinned OSS 11.1.4 Windows download/checksum](https://grafana.com/grafana/download/11.1.4?edition=oss&platform=windows).
- [Loki native installation, including the Windows command](https://grafana.com/docs/loki/latest/setup/install/local/) and [Loki 3.5.12 release](https://github.com/grafana/loki/releases/tag/v3.5.12).
- [Prometheus official download platforms](https://prometheus.io/download/) and [Prometheus 2.54.1 release](https://github.com/prometheus/prometheus/releases/tag/v2.54.1).
- [Alloy Windows installation](https://grafana.com/docs/alloy/latest/set-up/install/windows/), [Alloy 1.5.1 release](https://github.com/grafana/alloy/releases/tag/v1.5.1), and [the pinned receiver API source documentation](https://github.com/grafana/alloy/blob/v1.5.1/docs/sources/reference/components/prometheus/prometheus.receive_http.md).

## Optional Windows service wrapper source

`native_core.py serve` keeps a foreground supervisor alive, notices component exit, handles Windows console/service stop signals and stops only its recorded children in `finally`. Use this blocking action for a service wrapper; using `start` as the service executable would return immediately.

`WinSW.NativeObservability.example.xml` is a portable template only. Replace every absolute-path placeholder and choose a unique service ID in a private reviewed copy beside the site's vetted WinSW binary. XML-escape paths as necessary. The wrapper binary and service-account configuration are external prerequisites; no service is installed, changed or registered by this package. The template assumes a runtime previously initialized interactively and a service account with access to its private directory. It includes no plaintext credentials. Configure startup/recovery policy and verify service stop, child cleanup, restart and reboot behavior on the approved host before treating that path as commissioned. Default `serve` startup can reuse the previously initialized Grafana credential database without passing the bootstrap password again. Do not run manual `stop` concurrently with `serve`; stop the foreground supervisor or the service wrapper instead.

The acceptance command also stops and restarts the same four processes, then re-queries the original metric, original log marker and authenticated Grafana API. That qualifies the bounded restart/storage path only when the real Windows receipt reports it passed. It does not establish power-loss durability or SCM/reboot lifecycle behavior.
