# Isolated native Python3.12 acceptance; no customer access or service registration.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory,
    [string]$WorkDirectory
)
$ErrorActionPreference='Stop'
if([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT){throw 'Native Windows required.'}
$collectionDirectory=Split-Path -Parent $MyInvocation.MyCommand.Path
if(-not $WorkDirectory){$WorkDirectory=Join-Path $env:TEMP ('ova-collection-acceptance-'+[Guid]::NewGuid().ToString('N').Substring(0,8))}
if(Test-Path -LiteralPath $WorkDirectory){throw 'Choose a new work directory; existing data are preserved.'}
if(Test-Path -LiteralPath $EvidenceDirectory){throw 'Choose a new external evidence directory.'}
New-Item -ItemType Directory -Path $WorkDirectory | Out-Null
New-Item -ItemType Directory -Path $EvidenceDirectory | Out-Null
$python=(Resolve-Path -LiteralPath $PythonExe).Path
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PIP_DISABLE_PIP_VERSION_CHECK='1'
& $python -B (Join-Path $collectionDirectory 'check_prerequisites.py')
if($LASTEXITCODE -ne 0){throw 'Interpreter prerequisite failed.'}
$dependencies=Get-Content -Raw -LiteralPath (Join-Path $collectionDirectory 'DEPENDENCIES.json') | ConvertFrom-Json
foreach($entry in $dependencies.files){
    $file=Join-Path $collectionDirectory $entry.path
    if((Get-Item -LiteralPath $file).Length -ne $entry.bytes -or (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash -ne $entry.sha256){throw ('Dependency integrity mismatch: '+$entry.path)}
}
$venv=Join-Path $WorkDirectory 'venv'
& $python -m venv $venv
if($LASTEXITCODE -ne 0){throw 'Isolated venv creation failed.'}
$testPython=Join-Path $venv 'Scripts/python.exe'
& $testPython -m pip install --no-index --only-binary=:all: --require-hashes --find-links (Join-Path $collectionDirectory 'wheelhouse') -r (Join-Path $collectionDirectory 'requirements-win.lock')
if($LASTEXITCODE -ne 0){throw 'Offline Windows dependency installation failed.'}
& $testPython -m pip check
if($LASTEXITCODE -ne 0){throw 'Offline Windows dependency check failed.'}
& $testPython -B (Join-Path $collectionDirectory 'tests/test_native_collection.py') --evidence (Join-Path $EvidenceDirectory 'collection-native-acceptance.json')
if($LASTEXITCODE -ne 0){throw 'Native collection acceptance failed; inspect external JSON and console output.'}
Write-Output ('Native isolated acceptance passed. Evidence: '+$EvidenceDirectory)
Write-Output ('Only the new isolated test environment was created: '+$WorkDirectory)
