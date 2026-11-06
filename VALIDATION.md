# Validation status

## Completed preparation

- Original control ZIP and both external Observability archives matched the NVFTP release index.
- Intake found generated Rack runtime credential/state files. Six files were removed from the publication copy and the Rack toolkit, control manifests and root control archive were rebuilt. See [sanitation evidence](evidence/sanitization-removals.json) and [new artifact identities](evidence/sanitized-artifact-provenance.json).
- [Published component integrity](evidence/published-component-integrity.json) checks the five supplied component file manifests. Observability and the added PythonCM snapshot have their source identities recorded separately.
- Six portable control-helper tests passed on Linux: all-six toolkit extraction, strict manifest verification, tamper/unlisted/traversal rejection, unsafe ZIP names, collision/symlink refusal and existing-destination refusal. This verifies these helpers on Linux only.
- A bounded recursive credential scan covers compressed payloads and reports its exclusions and classified vendor/test matches in [the scan report](evidence/recursive-secret-scan.json). This is not an exhaustive security certification.
- The [user guide PDF](docs/OVA-MONOREPO-WINDOWS-User-Guide.pdf) was rendered and inspected separately from application runtime validation.

## Windows control acceptance

The GitLab `windows-control-acceptance` job runs the native Windows PowerShell/Python harness. Its output artifact is `artifacts/windows-controls/windows-controls.json`. Consult the actual pipeline result before reporting success; the presence of the job definition is not evidence that it ran.

Transport argument/guard tests explicitly mock SSH, SCP and SFTP. The job does not contact customer hosts, configure a VPN, run GPU workloads or validate all six application backends.

## Actual deployed VM acceptance

Pending direct coordination with the existing Windows Codex session through `codex queue --remote`. The app-server endpoint and target session ID are required. No GitLab-based agent handoff is used.

The user requires native Windows services and excludes Linux virtualization. The [compatibility assessment](docs/NATIVE_WINDOWS_COMPATIBILITY.md) identifies source-level blockers and distinguishes the supplied Linux backend path from that requirement. Reconcile adaptations already installed on the actual VM before replacing or porting services.

For each tool, acceptance still requires native executable/service identity, exact source/build, startup and functional result, durable state/restart evidence, and its approved cluster collector/workload boundary. VPN/DNS/SSH reachability to both BCM and app-server must be proven on the actual VM. Until those results exist, this delivery is a sanitized source/control candidate, not a certified six-service native Windows installation.
