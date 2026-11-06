[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$SftpUser,
    [Parameter(Mandatory=$true)][string]$IdentityFile,
    [Parameter(Mandatory=$true)][ValidatePattern('^/nvidia-space/shared/IREN_MKZ/[A-Za-z0-9_./-]+\.zip$')][string]$RemoteZip,
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSha256
)
$ErrorActionPreference = 'Stop'
if ($Destination -match '["\r\n]' -or $IdentityFile -match '[\r\n]' -or $RemoteZip -match '/\.\./') { throw 'Invalid transfer path.' }
if (Test-Path -LiteralPath $Destination) { throw 'Destination exists; choose a new path.' }
$key = (Resolve-Path -LiteralPath $IdentityFile).Path
$absoluteDestination = [System.IO.Path]::GetFullPath($Destination)
$parent = [System.IO.Path]::GetDirectoryName($absoluteDestination)
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$batch = [System.IO.Path]::GetTempFileName()
try {
    $localForSftp = $absoluteDestination.Replace('\','/')
    $command = 'get "' + $RemoteZip + '" "' + $localForSftp + '"'
    [System.IO.File]::WriteAllText($batch, $command + "`n", [System.Text.UTF8Encoding]::new($false))
    & sftp.exe -o BatchMode=yes -o StrictHostKeyChecking=yes -i $key -b $batch "${SftpUser}@transfer.nvftp.nvidia.com"
    if ($LASTEXITCODE -ne 0) { throw 'NVFTP download failed; partial file may remain.' }
    $actual = (Get-FileHash -LiteralPath $absoluteDestination -Algorithm SHA256).Hash
    if ($actual -ne $ExpectedSha256) { throw 'Downloaded release checksum mismatch; do not extract.' }
    Write-Output "Verified $absoluteDestination. Extract into a short path such as C:\IREN\release."
} finally {
    Remove-Item -LiteralPath $batch -Force -ErrorAction SilentlyContinue
}
