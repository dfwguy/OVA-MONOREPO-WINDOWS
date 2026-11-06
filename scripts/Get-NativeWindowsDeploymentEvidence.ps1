# Read-only native Windows deployment inventory. No Linux VM, WSL, service change,
# installation, GPU command, remediation action, or credential inspection occurs.
[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $env:TEMP ('ova-native-evidence-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))),
    [string]$BcmHeadNode,
    [string]$AppServer,
    [ValidateRange(1,65535)][int]$SshPort = 22
)
$ErrorActionPreference='Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Run this script natively on the deployed Windows VM.' }
foreach ($target in @($BcmHeadNode,$AppServer)) {
    if ($target -and ($target.StartsWith('-') -or $target -match '[\r\n]' -or $target -match 'REPLACE')) { throw 'Supply an approved hostname or address.' }
}
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Evidence directory already exists; choose a fresh path outside the repository.' }
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
$sections=[ordered]@{}
$failures=New-Object 'System.Collections.Generic.List[object]'
function Collect([string]$Name,[scriptblock]$Action) {
    try { $sections[$Name]=@(& $Action) }
    catch { $failures.Add([pscustomobject]@{ section=$Name; error=$_.Exception.Message }); $sections[$Name]=@() }
}
Collect 'operating_system' { Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture,LastBootUpTime,FreePhysicalMemory,TotalVisibleMemorySize }
Collect 'services' { Get-CimInstance Win32_Service | Select-Object Name,DisplayName,State,StartMode,ProcessId }
# Avoid process command lines and service PathName: those can contain credentials.
Collect 'processes' { Get-Process | Select-Object Id,ProcessName,Path,StartTime }
Collect 'tcp_listeners' { Get-NetTCPConnection -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess }
Collect 'disk_space' { Get-PSDrive -PSProvider FileSystem | Select-Object Name,Root,Used,Free }
Collect 'adapters' { Get-NetAdapter | Select-Object Name,InterfaceDescription,Status,LinkSpeed }
Collect 'vpn_profiles' { Get-VpnConnection -ErrorAction Stop | Select-Object Name,ServerAddress,TunnelType,ConnectionStatus,SplitTunneling }
Collect 'tool_paths' {
    foreach ($tool in @('ssh.exe','scp.exe','sftp.exe','python.exe','py.exe','node.exe','npm.cmd','git.exe','docker.exe')) {
        $command=Get-Command $tool -ErrorAction SilentlyContinue
        [pscustomobject]@{ name=$tool; available=[bool]$command; path=if($command){$command.Source}else{''} }
    }
}
Collect 'approved_endpoint_connectivity' {
    foreach ($target in @($BcmHeadNode,$AppServer)) {
        if ($target) { Test-NetConnection -ComputerName $target -Port $SshPort -InformationLevel Detailed | Select-Object ComputerName,RemoteAddress,RemotePort,InterfaceAlias,SourceAddress,TcpTestSucceeded }
    }
}
$report=[ordered]@{
    schema_version=1; recorded_utc=[DateTime]::UtcNow.ToString('o'); computer_name=$env:COMPUTERNAME;
    powershell_version=$PSVersionTable.PSVersion.ToString(); scope='Read-only native Windows host inventory';
    deployment_acceptance='NOT_ESTABLISHED_BY_INVENTORY'; sections=$sections; unavailable_sections=$failures.ToArray();
    omitted_for_secret_protection=@('Process command lines','Service command lines','Credential contents','Environment variable values');
    next_evidence='Match listeners and services to each tool, then run tool-specific native functional acceptance on approved targets.'
}
$path=Join-Path $OutputDirectory 'native-windows-inventory.json'
$report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $path -Encoding UTF8
Write-Output "Private inventory written to $path. Keep it outside source control."
Write-Output 'Inventory proves the observed Windows host state only; it does not prove six-tool end-to-end acceptance.'
