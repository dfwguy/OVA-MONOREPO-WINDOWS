[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RuntimeRoot,
    [string]$PythonExe = 'python'
)
$ErrorActionPreference = 'Stop'
& $PythonExe (Join-Path $PSScriptRoot 'native_core.py') stop --runtime-root $RuntimeRoot
if ($LASTEXITCODE -ne 0) { throw 'Native observability stop failed; process identity checks refused unsafe termination or the OS rejected it.' }
