[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RuntimeRoot,
    [ValidateRange(1024,65520)][int]$PortBase = 18000,
    [string]$PythonExe = 'python'
)
$ErrorActionPreference = 'Stop'
$previousPassword = $env:OVA_OBS_ADMIN_PASSWORD
$bstr = [IntPtr]::Zero
try {
    if (-not $env:OVA_OBS_ADMIN_PASSWORD) {
        $secure = Read-Host 'Grafana ova-admin password (at least 16 characters)' -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $env:OVA_OBS_ADMIN_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    & $PythonExe (Join-Path $PSScriptRoot 'native_core.py') start --runtime-root $RuntimeRoot --port-base $PortBase
    if ($LASTEXITCODE -ne 0) { throw 'Native observability startup failed; inspect the private runtime logs.' }
}
finally {
    $env:OVA_OBS_ADMIN_PASSWORD = $previousPassword
    if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
