[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$serviceName = 'NVISP2PConsole'
$identity = 'NT SERVICE\NVISP2PConsole'
$serviceRoot = 'C:\NVIS\runtime\p2p-console-service'
$logRoot = 'C:\NVIS\logs\p2p-console'
$codeRoot = $PSScriptRoot
$python = 'C:\NVIS\runtime\rack-status-venv\Scripts\python.exe'
$wrapperSource = 'C:\NVIS\runtime\downloads\WinSW.NET461.exe'
$expectedHash = 'B5066B7BBDFBA1293E5D15CDA3CAAEA88FBEAB35BD5B38C41C913D492AADFC4F'
if (Get-Service -Name $serviceName -ErrorAction SilentlyContinue) { throw 'Existing P2P console service preserved; review before changing it.' }
if ((Get-FileHash -LiteralPath $wrapperSource -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Unexpected WinSW wrapper hash' }
foreach ($port in @(4301,14304)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port is already occupied" }
}
$owner = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
New-Item -ItemType Directory -Path $serviceRoot,$logRoot -Force | Out-Null
foreach ($private in @($serviceRoot,$logRoot)) {
    & icacls.exe $private /inheritance:r /grant:r "$($owner):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Cannot protect $private" }
}
$wrapper = Join-Path $serviceRoot 'NVISP2PConsole.exe'
Copy-Item -LiteralPath $wrapperSource -Destination $wrapper
$xml = @'
<service>
  <id>NVISP2PConsole</id>
  <name>NVIS P2P Console</name>
  <description>Native Windows Dragonfly console with loopback Manager API over the example SSH chain.</description>
  <executable>C:\NVIS\runtime\rack-status-venv\Scripts\python.exe</executable>
  <arguments>-u C:\NVIS\p2p-r2\windows-control\console.py --config C:\NVIS\config\p2p-console.json</arguments>
  <workingdirectory>C:\NVIS\p2p-r2\windows-control</workingdirectory>
  <stopexecutable>C:\NVIS\runtime\rack-status-venv\Scripts\python.exe</stopexecutable>
  <stoparguments>C:\NVIS\p2p-r2\windows-control\service_control.py</stoparguments>
  <stoptimeout>30 sec</stoptimeout>
  <startmode>Automatic</startmode><delayedAutoStart>true</delayedAutoStart>
  <onfailure action="restart" delay="10 sec" /><onfailure action="restart" delay="60 sec" /><onfailure action="none" />
  <logpath>C:\NVIS\logs\p2p-console</logpath>
  <log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>5</keepFiles></log>
</service>
'@
[System.IO.File]::WriteAllText((Join-Path $serviceRoot 'NVISP2PConsole.xml'),$xml,[System.Text.UTF8Encoding]::new($false))
& $wrapper install
if ($LASTEXITCODE -ne 0) { throw 'P2P console service registration failed' }
& "$env:WINDIR\System32\sc.exe" config $serviceName obj= $identity
if ($LASTEXITCODE -ne 0) { throw 'Virtual service identity setup failed; service remains stopped' }
foreach ($read in @($codeRoot,$serviceRoot,'C:\NVIS\p2p-r2\nvis-p2p\console-static','C:\NVIS\runtime','C:\NVIS\config')) {
    & icacls.exe $read /grant "$($identity):(OI)(CI)RX" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Cannot grant service read access: $read" }
}
& icacls.exe $logRoot /grant "$($identity):(OI)(CI)M" | Out-Null
$secretRoot = 'C:\NVIS\secrets\p2p-console'
& icacls.exe $secretRoot /grant "$($identity):(OI)(CI)RX" | Out-Null
$sshKey = Join-Path $secretRoot 'id_ed25519'
& icacls.exe $sshKey /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' "$($identity):R" | Out-Null
& icacls.exe $sshKey /remove:g $owner | Out-Null
& icacls.exe $sshKey /setowner $identity | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'P2P console SSH identity permissions failed' }
& icacls.exe 'C:\NVIS\config\p2p_known_hosts' /grant "$($identity):M" | Out-Null
Start-Service -Name $serviceName
Get-CimInstance Win32_Service -Filter "Name='NVISP2PConsole'" | Select-Object Name,State,StartName
