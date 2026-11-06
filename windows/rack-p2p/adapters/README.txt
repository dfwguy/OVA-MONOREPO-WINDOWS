PORTABLE WINDOWS ADAPTER SOURCE DELTA

This is source for review/import, not a deployed product or all-six Windows port.
Rack Status is based on nvis/nvis-rack-status commit337a25615c083a09f567aed3cf7e848e766b6e84,
through the source package pinned in PROVENANCE.json. It is NOT a renamed or proven equivalent
copy of the older rack-status-pythoncm fork. Original producer packaging changes precede
these local changes. Apply overlays only after checking the recorded base hashes; a pristine
upstream checkout can differ from that packaged base. Keep the NVIDIA license headers.

IMPORT / BUILD
1. Obtain the exact base project/source package independently. This export contains no base
   archive, runtime binaries, wheels, compiled SPA or model/container payloads.
2. Review MANIFEST.json and source/export hashes. Overlay rack-status/overlay onto that base
   source root. Supporting unchanged files are included for the PythonCM source closure.
3. Use CPython3.12 and a new isolated venv. Install backend/requirements.txt and
   windows/requirements.txt from an approved wheelhouse or package source. requirements-*.lock
   record the acquired native dependency versions; they are not included wheels.
4. Restore known Unix modes from MANIFEST.json for Linux/head helpers. New Windows source
   mode is explicitly unknown; .ps1 and .py need no Unix executable bit when called explicitly.
5. Build/acquire matching frontend artifacts using the base project's documented frontend build.
   For P2P separately acquire the matching console-static bundle; its test uses a synthetic SPA.
6. C:\NVIS is a reusable EXAMPLE root in copied launch/service defaults. Review and replace it
   with your chosen local Windows installation root; scripts also expose their existing parameters.
   Use a separate venv for the P2P console and its requirements.txt. Provision fresh private site
   configuration, SSH config/known_hosts, keys, TLS and bootstrap credentials outside source.
7. Acquire WinSW2.12.0 separately and verify its SHA256 in PROVENANCE.json. No EXE/XML from the
   installed services is shipped; source installers recreate the wrappers. Review installer paths,
   least-privilege identity and ACL operations before running them. No installer was run here.

SCOPE / LIMITS
Rack native changes cover Cheroot HTTPS/WebSocket serving, Windows ConPTY, file locking,
process handling and remote POSIX path handling. Existing auth/TLS gates remain in the source.
PythonCM inventory capability is established separately from execution. The head keeps its
matching SDK/session; Windows uses existing SSH transport and helper scripts. ProgramRunner
execution-session acceptance failed historically; generic workflow env/launch_mode/user forwarding
has an identified gap. The helper is command fanout, not Slurm/GRES reservation. See
PYTHONCM-CAPABILITY.json and the two porting explanation documents. Do not arm workload Tools
or claim full fork equivalence from source presence or fake-only unit tests.

P2P Windows files serve static UI and proxy Manager REST over an SSH tunnel. They do not port
Manager, scheduler, seed, PostgreSQL, Redis or nginx to Windows. The separately named
p2p/linux-compatibility-overlay is Linux-only renderer/preflight/schema/host-guard code, not a
Windows core. No AutoAction PythonCM prototype, private credential rotator or fleet operations
script is included. Other tools are outside this export.

SANITIZATION / VALIDATION
Only export copies were changed: customer identifiers/account names/private IP literals were
converted to explicit example names/documentation ranges. Sanitization counts and any fixture
adaptation are recorded without retaining original values. Installed source/services were untouched.
Historical live acceptance is not shipped and is not portable acceptance. Export-only tests,
if performed, are recorded separately in VALIDATION.json. Review on a clean base and run that
project's CI/native suites before deployment. No Git push or transfer is performed by this builder.
