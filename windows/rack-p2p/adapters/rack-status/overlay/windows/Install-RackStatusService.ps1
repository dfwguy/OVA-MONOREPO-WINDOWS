# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
[CmdletBinding()]
param(
    [string]$PythonExecutable = 'C:\NVIS\runtime\rack-status-venv\Scripts\python.exe',
    [string]$ConfigPath = 'C:\NVIS\config\rackstatus.toml',
    [string]$WrapperSource = 'C:\NVIS\runtime\downloads\WinSW.NET461.exe',
    [string]$ServiceRoot = 'C:\NVIS\runtime\rack-status-service',
    [string]$LogRoot = 'C:\NVIS\logs\rack-status',
    [string]$BindAddress = '127.0.0.1',
    [ValidateRange(1,65535)][int]$Port = 5050
)
$ErrorActionPreference = 'Stop'
$rackRoot = Split-Path -Parent $PSScriptRoot
$rackService = 'NVISRackStatus'
$rackIdentity = 'NT SERVICE\NVISRackStatus'
$rackWrapperHash = 'B5066B7BBDFBA1293E5D15CDA3CAAEA88FBEAB35BD5B38C41C913D492AADFC4F'
if ((Get-FileHash -LiteralPath $WrapperSource -Algorithm SHA256).Hash -ne $rackWrapperHash) { throw 'WinSW wrapper does not match the reviewed 2.12.0 binary' }
if (Get-Service -Name $rackService -ErrorAction SilentlyContinue) { throw 'Existing service preserved. Stop and review it before changing the installation.' }
New-Item -ItemType Directory -Path $ServiceRoot,$LogRoot -Force | Out-Null
$rackOwner = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
foreach ($rackPrivate in @($ServiceRoot,$LogRoot)) {
    & icacls.exe $rackPrivate /inheritance:r /grant:r "$($rackOwner):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not protect $rackPrivate" }
}
$rackWrapper = Join-Path $ServiceRoot 'NVISRackStatus.exe'
Copy-Item -LiteralPath $WrapperSource -Destination $rackWrapper -Force
function Escape-RackXml([string]$Value) { [System.Security.SecurityElement]::Escape($Value) }
$rackExecutableXml = Escape-RackXml $PythonExecutable
$rackCwdXml = Escape-RackXml $rackRoot
$rackConfigXml = Escape-RackXml $ConfigPath
$rackLogXml = Escape-RackXml $LogRoot
$rackArgumentsXml = Escape-RackXml ('-u "' + (Join-Path $rackRoot 'backend\cli.py') + '" serve --config "' + $ConfigPath + '" --host ' + $BindAddress + ' --port ' + $Port)
$rackStopXml = Escape-RackXml ('"' + (Join-Path $PSScriptRoot 'service_control.py') + '"')
$rackXml = @"
<service>
  <id>NVISRackStatus</id>
  <name>NVIS Rack Status</name>
  <description>Native Windows HTTPS Rack Status control plane; Linux execution through the configured trusted SSH chain.</description>
  <executable>$rackExecutableXml</executable>
  <arguments>$rackArgumentsXml</arguments>
  <workingdirectory>$rackCwdXml</workingdirectory>
  <env name="NVIS_RACKSTATUS_CONFIG" value="$rackConfigXml" />
  <env name="PYTHONUNBUFFERED" value="1" />
  <env name="NVIS_WINDOWS_STOP_EVENT" value="Local\NVISRackStatusStop" />
  <stopexecutable>$rackExecutableXml</stopexecutable>
  <stoparguments>$rackStopXml</stoparguments>
  <stoptimeout>45 sec</stoptimeout>
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>
  <onfailure action="restart" delay="10 sec" />
  <onfailure action="restart" delay="60 sec" />
  <onfailure action="none" />
  <logpath>$rackLogXml</logpath>
  <log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>5</keepFiles></log>
</service>
"@
[System.IO.File]::WriteAllText((Join-Path $ServiceRoot 'NVISRackStatus.xml'),$rackXml,[System.Text.UTF8Encoding]::new($false))
& $rackWrapper install
if ($LASTEXITCODE -ne 0) { throw 'WinSW service registration failed' }
# Registration defaults to LocalSystem; change to the dedicated virtual account
# BEFORE any start. No password is created, stored or needed for a virtual account.
& "$env:WINDIR\System32\sc.exe" config $rackService obj= $rackIdentity
if ($LASTEXITCODE -ne 0) { throw 'Virtual service account configuration failed; service left stopped' }
foreach ($rackRead in @($rackRoot,'C:\NVIS\runtime','C:\NVIS\config',$ServiceRoot)) {
    & icacls.exe $rackRead /grant "$($rackIdentity):(OI)(CI)RX" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not grant runtime read permission to $rackRead" }
}
foreach ($rackWrite in @((Join-Path $rackRoot 'var'),$LogRoot)) {
    & icacls.exe $rackWrite /inheritance:r /grant:r "$($rackOwner):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "$($rackIdentity):(OI)(CI)M" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not grant state/log permission to $rackWrite" }
}
$rackPrivateKey = 'C:\NVIS\secrets\rack-status\id_ed25519'
if (Test-Path -LiteralPath $rackPrivateKey) {
    & icacls.exe (Split-Path -Parent $rackPrivateKey) /grant "$($rackIdentity):(OI)(CI)RX" | Out-Null
    & icacls.exe $rackPrivateKey /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' "$($rackIdentity):R" | Out-Null
    & icacls.exe $rackPrivateKey /remove:g $rackOwner | Out-Null
    & icacls.exe $rackPrivateKey /setowner $rackIdentity | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not grant service SSH-key read permission' }
}
$rackKnownHosts = 'C:\NVIS\config\known_hosts'
if (Test-Path -LiteralPath $rackKnownHosts) {
    & icacls.exe $rackKnownHosts /grant "$($rackIdentity):M" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not grant service known-host update permission' }
}
Start-Service -Name $rackService
& (Join-Path $PSScriptRoot 'Test-RackStatus.ps1') -PythonExecutable $PythonExecutable -Hostname 'localhost' -Port $Port
Get-CimInstance Win32_Service -Filter "Name='NVISRackStatus'" | Select-Object Name,State,StartMode,StartName
