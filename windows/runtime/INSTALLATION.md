# Optional offline Windows runtime prerequisites

This folder stages the full CPython 3.12.10 Windows x64 installer, WinSW 2.12.0 standalone x64 wrapper, and the WinSW 2.12.0 .NET461 variant. The .NET461 variant matches the saved inspected-VM wrapper SHA-256 exactly; the standalone x64 file is an alternative with its runtime bundled. Preparing this package did not run the installer, execute WinSW, change an existing Python installation, register a service or change a firewall rule.

`DEPENDENCIES.json` records exact official HTTPS sources, versions, measured bytes, SHA-256 and license provenance. Its SHA-256 values were measured after download; no independent publisher SHA-256 manifest was available for these executable files. The Python installer is additionally checked with Windows Authenticode before use. The original release licenses remain included by the vendor distribution; pinned source license texts are copied under `licenses/`.

## Verify before use

Run the read-only verifier on the Windows VM. The report includes hashes and public certificate metadata; it executes neither downloaded program.

```powershell
Set-Location C:\OVA\windows\runtime
.\Verify-RuntimeDependencies.ps1 -ReportPath C:\OVA-Acceptance\runtime-signatures-unique.json
```

The verifier requires all recorded hashes to match and Python's Authenticode status to be `Valid` with a Python Software Foundation organization identity. If offline certificate-chain or revocation checks fail, resolve the Windows trust environment through the approved ITSS process before installation. A measured SHA-256 alone does not authenticate a publisher. WinSW's actual Authenticode status is recorded separately; the package does not claim it is publisher-signed. The source URLs and preserved hashes support the site's normal executable intake review.

## Optional per-user CPython installation

Skip installation if a compatible approved Python runtime is already available. Inspect it with its explicit path; do not replace a working installation or change a system-wide PATH just to run these tools.

For a fresh per-user runtime, open the verified `dependencies\python-3.12.10-amd64.exe` interactively and choose **Customize installation**. Keep pip selected. Unselect the launcher, documentation, test suite, Tcl/Tk/IDLE, debug binaries and debug symbols when they are unnecessary. In Advanced Options, leave installation for all users, file associations, shortcuts and PATH changes disabled. Choose a new directory under the current user's local application data, such as `%LOCALAPPDATA%\OVA\Python312`. Use the full offline installer; do not enable optional downloads on an isolated VM.

An operator can instead run the following documented installer options after verifying the signature. This is an explicit manual installation step, not something the package executes automatically:

```powershell
$installer = Join-Path $PWD 'dependencies\python-3.12.10-amd64.exe'
$pythonRoot = Join-Path $env:LOCALAPPDATA 'OVA\Python312'
if (Test-Path -LiteralPath $pythonRoot) { throw 'Choose a new per-user Python installation directory.' }
$installerArguments = @(
    '/passive', 'InstallAllUsers=0', 'Include_launcher=0', 'Include_pip=1',
    'Include_test=0', 'Include_doc=0', 'Include_tcltk=0', 'Include_tools=0',
    'Include_debug=0', 'Include_symbols=0', 'AssociateFiles=0', 'Shortcuts=0',
    'PrependPath=0', ('TargetDir="{0}"' -f $pythonRoot)
)
$install = Start-Process -FilePath $installer -ArgumentList $installerArguments -Wait -PassThru
if ($install.ExitCode -notin @(0, 3010)) { throw "Python installer failed: $($install.ExitCode)" }
if ($install.ExitCode -eq 3010) { Write-Output 'Installer requested a reboot; coordinate it through ITSS before further qualification.' }
$python = Join-Path $pythonRoot 'python.exe'
& $python -c 'import sys, struct, venv; assert sys.version_info[:3] == (3, 12, 10); assert struct.calcsize("P") == 8; print(sys.version); print(sys.executable)'
& $python -m pip --version
```

Use the resulting explicit interpreter path in component wrappers or create component-specific virtual environments. Installing Python does not install every component's wheels. Use each component's pinned offline wheelhouse with `--no-index --find-links`; do not fetch packages from the customer cluster. Windows wheels must match CPython 3.12 and x64. Never use the supplied Linux wheelhouses as Windows dependencies.

The version is pinned for reproducibility and compatibility with the inspected VM. It is not a claim that 3.12.10 is the current Python security release; the upstream release page identifies subsequent releases. Any runtime upgrade needs the component checks to run again.

## Optional WinSW wrapper staging

`dependencies\WinSW-x64-2.12.0.exe` is the upstream `WinSW-x64.exe` asset, renamed locally to make its version explicit. It is a standalone wrapper, not an installer. Use a private runtime/service directory outside Git. Copy it there and rename the executable and XML configuration to the same basename; for example `OVA-Observability.exe` beside `OVA-Observability.xml`.

Use a reviewed component-specific XML template. For native observability, the wrapper must launch `native_core.py serve`, whose lifetime includes supervision; the `start` action returns and is unsuitable as the long-running service process. Initialize the private component runtime first, grant only its intended service account access, and keep credentials outside XML distributed in Git.

Copying these files does not install a service. Windows service registration, account assignment and lifecycle qualification are separate operator/ITSS steps requiring the site's administrative scope. Do not run `install`, `start`, `stop`, `uninstall` or rename an existing production wrapper during package verification. This package performs none of those actions. The standalone x64 release packages its runtime; the .NET2/.NET4/.NET461 variants are different upstream assets and are not silently substituted.

## Official sources

- [Python 3.12.10 release](https://www.python.org/downloads/release/python-31210/), [full installer](https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe), and [Python's Windows installer options](https://docs.python.org/3.12/using/windows.html#installing-without-ui).
- [CPython 3.12.10 license source](https://github.com/python/cpython/blob/v3.12.10/LICENSE).
- [WinSW 2.12.0 release](https://github.com/winsw/winsw/releases/tag/v2.12.0), [standalone x64 asset](https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe), [pinned usage documentation](https://github.com/winsw/winsw/tree/v2.12.0), and [MIT license](https://github.com/winsw/winsw/blob/v2.12.0/LICENSE.txt).


The exact inspected-VM wrapper is also supplied as `dependencies\WinSW.NET461-2.12.0.exe` (upstream `WinSW.NET461.exe`), whose measured SHA-256 matches the exported VM receipt. It requires an existing approved Microsoft .NET Framework 4.6.1 or newer compatible runtime. Choose this variant to reproduce that wrapper environment, or qualify the standalone x64 alternative separately. Matching versions alone does not make the two binaries byte-identical. No .NET installation is performed or included.


Actual read-only verification on Windows Server2025/CPython3.12.10 passed all three recorded hashes and validated the Python Software Foundation Authenticode signature. Both WinSW variants reported `NotSigned`; no publisher signature is claimed. No installer or wrapper was executed. See `evidence/runtime-prerequisites-windows.json`.
