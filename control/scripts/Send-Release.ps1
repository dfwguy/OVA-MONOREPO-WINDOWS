[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SshAlias,
    [Parameter(Mandatory=$true)][string]$BundleZip,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.-]*$')][string]$ReleaseId
)
$ErrorActionPreference = 'Stop'
if ($SshAlias -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$') { throw 'Use a configured OpenSSH alias.' }
$resolved = (Resolve-Path -LiteralPath $BundleZip).Path
$actual = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $ExpectedSha256.ToLowerInvariant()) { throw 'Local release checksum mismatch.' }
$remote = "/var/tmp/iren-mkz/$ReleaseId"
# This is an explicitly invoked staging operation. It creates a new directory;
# no install command or service operation is sent to the management host.
& ssh.exe -o BatchMode=yes -o StrictHostKeyChecking=yes $SshAlias "set -eu; umask 077; test ! -L /var/tmp/iren-mkz; mkdir -p /var/tmp/iren-mkz; test -O /var/tmp/iren-mkz; test -d /var/tmp/iren-mkz; mkdir '$remote'"
if ($LASTEXITCODE -ne 0) { throw 'Remote stage exists or could not be created; choose a new release ID.' }
& scp.exe -o BatchMode=yes -o StrictHostKeyChecking=yes $resolved "${SshAlias}:$remote/release.zip"
if ($LASTEXITCODE -ne 0) { throw 'SCP transfer failed; partial remote staging directory retained for inspection.' }
$observed = & ssh.exe -o BatchMode=yes -o StrictHostKeyChecking=yes $SshAlias "sha256sum '$remote/release.zip'"
if ($LASTEXITCODE -ne 0 -or ($observed -split '\s+')[0] -ne $actual) { throw 'Remote read-back checksum mismatch.' }
Write-Output "Verified $remote/release.zip. No extraction/install performed."
