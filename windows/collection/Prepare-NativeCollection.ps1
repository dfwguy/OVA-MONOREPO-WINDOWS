# Prepare a NEW isolated Python3.12 environment and derived runtime; no service install.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [Parameter(Mandatory=$true)][string]$VenvDirectory,
    [Parameter(Mandatory=$true)][string]$RuntimeDirectory,
    [Parameter(Mandatory=$true)][string]$ConfigPath
)
$ErrorActionPreference='Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Native Windows only.' }
$collectionDirectory=Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($path in @($VenvDirectory,$RuntimeDirectory)) {
    if (Test-Path -LiteralPath $path) { throw 'Choose new external environment/runtime directories; preserve existing state.' }
}
$python=(Resolve-Path -LiteralPath $PythonExe).Path
& $python -B (Join-Path $collectionDirectory 'check_prerequisites.py')
if($LASTEXITCODE -ne 0){throw 'Native interpreter prerequisite failed.'}
$dependencies=Get-Content -Raw -LiteralPath (Join-Path $collectionDirectory 'DEPENDENCIES.json') | ConvertFrom-Json
foreach($entry in $dependencies.files){
    $file=Join-Path $collectionDirectory $entry.path
    if((Get-Item -LiteralPath $file).Length -ne $entry.bytes -or (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash -ne $entry.sha256){throw ('Dependency digest mismatch: '+$entry.path)}
}
& $python -m venv $VenvDirectory
if($LASTEXITCODE -ne 0){throw 'Native venv creation failed.'}
$venvPython=Join-Path $VenvDirectory 'Scripts/python.exe'
& $venvPython -m pip install --no-index --only-binary=:all: --require-hashes --find-links (Join-Path $collectionDirectory 'wheelhouse') -r (Join-Path $collectionDirectory 'requirements-win.lock')
if($LASTEXITCODE -ne 0){throw 'Offline native dependency installation failed.'}
& $venvPython -m pip check
if($LASTEXITCODE -ne 0){throw 'Native dependency check failed.'}
& $venvPython -B (Join-Path $collectionDirectory 'build_runtime.py') --output $RuntimeDirectory --config $ConfigPath
if($LASTEXITCODE -ne 0){throw 'Native runtime derivation failed.'}
Write-Output 'Prepared isolated native runtime. No service registration, customer access or collection scan performed.'
