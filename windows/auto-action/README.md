# Native Windows Auto Action scheduling adapter

This standard-library Python adapter places the timer, invocation guard and receipts on Windows. The supplied Auto Action framework's **original** `actions/launch_job.sh` still owns test selection, safety gates, retry logic and verdicts on one approved Linux compute node. Its thin node-side scripts and GPU jobs remain cluster-side. Windows reaches the head through trusted OpenSSH, sources the framework's existing `fanout.sh` abstraction and selects its `clush` or `pdsh` provider; Windows never fans out directly to the nodes.

This is a bounded one-node adapter, not a port of every fleet supervisor or recovery capability. It does not install or enable the upstream Linux watchdog. Review the original source's deployment and privilege documentation before using the execution mode. The existing source must already be staged at the same reviewed path on the selected node; this adapter performs no file copy, runtime installation or sudo-policy changes.

Copy `site.example.json` to a private location, replace every placeholder, set one exact node and test, and pin the remote `launch_job.sh` SHA-256. Keep the state directory outside the repository with access restricted to the service identity.

```powershell
python.exe windows\auto-action\controller.py plan --config C:\OVA\private\auto-action.json
python.exe windows\auto-action\controller.py cycle --config C:\OVA\private\auto-action.json
python.exe windows\auto-action\controller.py render-task --config C:\OVA\private\auto-action.json --python C:\Python312\python.exe --output C:\OVA\private\auto-action-task.xml
```

`preview` invokes the original launcher's `--explain --test` path; it does not submit work. The generated Task Scheduler definition is **disabled** and is not registered automatically. The VM owner must select the approved Windows identity, inspect the task/configuration and explicitly register/enable it when commissioning is authorized.

`execute` additionally requires `execute_authorized: true` in the private site configuration. That invokes the upstream `--test` path, whose documented semantics force the selected test and may drain the chosen node on a validation failure. It is not an observational probe. Do not enable it until exact node/test/runtime/privilege scope is accepted. This adapter never enables cluster-wide recovery or clears existing drains.

SQLite guards overlapping cycles and retains attempts. An SSH error, timeout or missing per-invocation node completion marker is recorded as **uncertain**, because remote work may already exist and fanout tools can mask a node exit status. A subsequent cycle refuses to replay an unresolved attempt. A completed execution scope is also not repeated by later timer ticks: review results before authorizing another campaign. Preview cycles may repeat. Inspect the scheduler and retained logs before resolving the private database through the service owner's recovery procedure; never delete the database to hide uncertain work. A zero transport exit code does not establish a passing GPU test.

Native Windows unit/fixture acceptance is separate from the required live one-node scheduler canary. Retain that distinction in release evidence.
