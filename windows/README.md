# Native Windows profiles

These profiles keep management code on native Windows. They do not require WSL, a Linux VM or Linux containers. Their isolated acceptance results must be recorded before release; source preparation is not site commissioning.

| Profile | What runs on Windows | What remains cluster-side |
| --- | --- | --- |
| `observability/` | Grafana, Prometheus, Loki and Alloy; pinned offline Windows binaries; private local storage | Approved thin exporters/collectors; source routing requires VPN/SSH commissioning |
| `collection/` | Derived collector/processing/browser runtime, real Windows locks, durable generations, native scheduling and offline Python wheels | Read-only scheduler/source access and explicitly selected thin capture hooks |
| `auto-action/` | One-node scheduling, exclusive invocation and receipts; disabled Task Scheduler definition | Original reviewed Auto Action launcher, its thin node-side scripts and GPU tests |
| `exemplar/` | Pinned preparation helper, configuration validation and local payload integrity | Official supported recipe/runtime, Slurm/Enroot/Pyxis and GPU workloads |

The existing VM's native Rack and P2P console/proxy adaptations are being exported for source reconciliation. The P2P management core remains on the Linux app-server; a Windows console does not move that core. This placement exception must remain explicit.

Application profiles target **64-bit CPython 3.12**, matching the audited Windows VM. The separate CPython 3.14 embeddable interpreter in `control/windows/` supplies standard-library control verification only; it is not the application venv/Python dependency closure.

Use fresh runtime and evidence directories outside the repository. Each profile documents its startup, acceptance and cleanup commands and limits. Do not register/enable persistent services or point collectors at customer sources merely to run isolated acceptance. Keep existing services and jobs intact while qualifying a candidate.
