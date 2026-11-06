[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SshAlias,
    [Parameter(Mandatory=$true)][ValidateRange(1024,65535)][int]$LocalPort,
    [Parameter(Mandatory=$true)][ValidateRange(1,65535)][int]$RemotePort,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]*$')][string]$RemoteHost = '127.0.0.1'
)
$ErrorActionPreference = 'Stop'
if ($SshAlias -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$') { throw 'Use a configured OpenSSH alias.' }
Write-Output "Keep this terminal open. Browse http://127.0.0.1:$LocalPort only if the service uses HTTP; preserve TLS when configured. Ctrl+C closes this tunnel."
& ssh.exe -o BatchMode=yes -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -N -L "127.0.0.1:${LocalPort}:${RemoteHost}:${RemotePort}" $SshAlias
if ($LASTEXITCODE -ne 0) { throw "SSH tunnel exited with $LASTEXITCODE." }
