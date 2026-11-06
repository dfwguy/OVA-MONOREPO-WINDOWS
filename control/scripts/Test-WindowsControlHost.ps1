# Read-only inventory; does not enable WSL/Hyper-V, change routes, or install software.
[CmdletBinding()]
param([string]$ControllerHost, [ValidateRange(1,65535)][int]$SshPort = 22)
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
[pscustomobject]@{ Caption=$os.Caption; Version=$os.Version; Architecture=$os.OSArchitecture; PowerShell=$PSVersionTable.PSVersion.ToString() }
Get-PSDrive -PSProvider FileSystem | Select-Object Name, Root, Used, Free
foreach ($tool in @('ssh.exe','scp.exe','sftp.exe','tar.exe','python.exe','py.exe')) {
    $cmd = Get-Command $tool -ErrorAction SilentlyContinue
    [pscustomobject]@{ Tool=$tool; Available=[bool]$cmd; Path=if($cmd){$cmd.Source}else{''} }
}
if ($ControllerHost) {
    if ($ControllerHost -match 'REPLACE|[\r\n]' -or $ControllerHost.StartsWith('-')) { throw 'Set the approved controller host.' }
    Resolve-DnsName -Name $ControllerHost -ErrorAction Continue
    Test-NetConnection -ComputerName $ControllerHost -Port $SshPort -InformationLevel Detailed
}
Write-Output 'Codex is assumed installed. This workflow requires no WSL or Hyper-V.'
Write-Output 'Confirm native Python 3.11+ (py -3 --version), OpenSSH, free disk, VPN instructions, SSH host fingerprint and the approved deployment scope.'
