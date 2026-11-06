# Native Windows Exemplar preparation

The upstream kit already provides standard-library preparation, configuration and payload-integrity tools. `build_helper.py` produces a pinned Windows control-host variant. The two adaptations validate **remote Linux destination paths** independently of the Windows filesystem; local payload manifests still inspect real local files. The original component source and its manifest remain unchanged.

```powershell
python.exe windows\exemplar\build_helper.py C:\OVA\work\exemplar-preparation
python.exe C:\OVA\work\exemplar-preparation\prepare.py validate-config C:\OVA\private\exemplar-site.json
python.exe C:\OVA\work\exemplar-preparation\prepare.py manifest C:\OVA\payload C:\OVA\private\payload-manifest.json
python.exe C:\OVA\work\exemplar-preparation\prepare.py verify C:\OVA\payload C:\OVA\private\payload-manifest.json
```

The source kit's schema, source pin, hardware/scale checks and credential restrictions are preserved. Its storage and credential references describe the remote Linux workload installation. Use the original component's agent handoff and execution runbook for SSH-controlled installation and Slurm/Enroot/Pyxis workloads. This helper does not introduce guessed Exemplar CLI flags, move GPU computation onto Windows or qualify a diagnostic adaptation as an official recipe.

Windows extraction does not certify Linux modes or symbolic-link preservation. Verify the original payload again on the Linux recipient using the reviewed source/runbook before running workloads. Keep native Windows preparation acceptance distinct from actual recipe support, image/model closure, site readiness and a bounded GPU canary.
