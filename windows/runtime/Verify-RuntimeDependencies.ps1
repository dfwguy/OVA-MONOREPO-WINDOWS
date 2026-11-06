[CmdletBinding()]
param([string]$ReportPath)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this read-only signature check on Windows.' }
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'DEPENDENCIES.json') -Raw | ConvertFrom-Json
$checks = @()
$pythonSignatureValid = $false
$hashesValid = $true
foreach ($asset in $manifest.assets) {
    $path = Join-Path (Join-Path $PSScriptRoot 'dependencies') $asset.filename
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing runtime asset: $($asset.filename)" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    $hashMatch = $actual -eq $asset.sha256.ToLowerInvariant()
    if (-not $hashMatch) { $hashesValid = $false }
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    $subject = $null
    $thumbprint = $null
    $timestampSubject = $null
    if ($signature.SignerCertificate) {
        $subject = $signature.SignerCertificate.Subject
        $thumbprint = $signature.SignerCertificate.Thumbprint
    }
    if ($signature.TimeStamperCertificate) { $timestampSubject = $signature.TimeStamperCertificate.Subject }
    if ($asset.component -eq 'python') {
        $pythonSignatureValid = $signature.Status.ToString() -eq 'Valid' -and $subject -match '(^|,\s*)O=Python Software Foundation(,|$)'
    }
    $checks += [pscustomobject]@{
        filename = $asset.filename
        version_pin = $asset.version
        bytes = (Get-Item -LiteralPath $path).Length
        measured_sha256 = $actual
        recorded_sha256_matches = $hashMatch
        publisher_sha256_available = $false
        authenticode_status = $signature.Status.ToString()
        signer_subject = $subject
        signer_thumbprint = $thumbprint
        timestamp_signer_subject = $timestampSubject
        installed_or_executed = $false
    }
}
$result = [pscustomobject]@{
    checked_utc = [DateTime]::UtcNow.ToString('o')
    action = 'Read file bytes and Windows Authenticode metadata only; no installer or service wrapper executed.'
    recorded_hashes_match = $hashesValid
    python_psf_authenticode_valid = $pythonSignatureValid
    assets = $checks
}
$json = $result | ConvertTo-Json -Depth 6
if ($ReportPath) {
    if (Test-Path -LiteralPath $ReportPath) { throw 'Choose a new ReportPath; existing evidence is preserved.' }
    $parent = Split-Path -Parent ([IO.Path]::GetFullPath($ReportPath))
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($ReportPath), $json, (New-Object System.Text.UTF8Encoding($false)))
}
$json
if (-not $hashesValid) { throw 'Recorded artifact hash mismatch. No asset was executed.' }
if (-not $pythonSignatureValid) { throw 'Python installer signature is not Valid for Python Software Foundation. Resolve trust/signature validation before using the installer.' }
