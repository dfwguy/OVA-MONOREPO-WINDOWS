# Optional native Windows Python verifier

The CPython embeddable x64 ZIP in this directory was downloaded from Python.org over verified HTTPS. `PYTHON_PROVENANCE.json` records the exact URL/version, bytes and measured SHA-256. It is a convenience runtime for the root **stdlib verification/extraction helpers**, not a Linux backend, a replacement for the existing Codex installation, or a pip environment.

Use your already installed native Python 3.11+ if present. Otherwise, on a compatible Windows x64 host, verify the ZIP checksum, extract this embeddable ZIP into a new private directory such as `C:\IREN\python`, and invoke:

```powershell
C:\IREN\python\python.exe C:\IREN\release\scripts\verify_bundle.py C:\IREN\release
```

Do not extract it inside the verified release tree, because extra files should fail strict manifest verification. No PATH, registry, admin feature, virtualization or global installation change is required. The official package's Windows execution and signature validation have not been tested on this Linux packaging host. Inspect the Python.org release/support requirements for your exact Windows OS before use. The kit includes no ARM64 Windows runtime; choose an approved matching interpreter if the control VM is ARM64.

Official source: https://www.python.org/downloads/windows/
