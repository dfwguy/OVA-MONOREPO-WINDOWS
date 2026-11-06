[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RuntimeRoot,
    [Parameter(Mandatory=$true)][string]$ReportPath,
    [ValidateRange(1024,65520)][int]$PortBase = 18000,
    [string]$PythonExe = 'python'
)
$ErrorActionPreference = 'Stop'
& $PythonExe (Join-Path $PSScriptRoot 'native_core.py') acceptance --runtime-root $RuntimeRoot --port-base $PortBase --report $ReportPath
if ($LASTEXITCODE -ne 0) { throw 'Isolated native Windows core acceptance failed. Inspect ReportPath and private runtime logs.' }
