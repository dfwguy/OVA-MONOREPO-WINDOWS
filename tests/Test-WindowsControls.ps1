# Native Windows acceptance for the supplied control layer. Transports are mocked;
# this does not qualify Linux backends, customer VPN, cluster jobs, or remediation.
[CmdletBinding()]
param(
    [string]$RepositoryRoot = '',
    [string]$EvidenceDirectory
)
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 may not initialize PSScriptRoot during parameter defaults.
if (-not $RepositoryRoot) {
    $testScriptPath=$MyInvocation.MyCommand.Path
    if (-not $testScriptPath) { throw 'Pass -RepositoryRoot explicitly when invoking without a script file.' }
    $RepositoryRoot=Split-Path -Parent (Split-Path -Parent $testScriptPath)
}
Set-StrictMode -Version Latest
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'This acceptance entry point requires native Windows.' }
$RepositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$control = Join-Path $RepositoryRoot 'control'
if (-not $EvidenceDirectory) { $EvidenceDirectory = Join-Path $RepositoryRoot 'artifacts/windows-controls' }
New-Item -ItemType Directory -Force -Path $EvidenceDirectory | Out-Null
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('ova-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$results = New-Object 'System.Collections.Generic.List[object]'
$global:OvaTransportCalls = New-Object 'System.Collections.Generic.List[object]'
function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Expect-Rejection([scriptblock]$Action) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    Assert-True $rejected 'Expected the invalid request to be rejected.'
}
function Check([string]$Name, [scriptblock]$Action) {
    try { & $Action; $results.Add([pscustomobject]@{ name=$Name; status='passed' }); Write-Output "PASS: $Name" }
    catch { $results.Add([pscustomobject]@{ name=$Name; status='failed'; error=$_.Exception.Message }); Write-Output "FAIL: $Name - $($_.Exception.Message)" }
}
try {
    Check 'PowerShell parser accepts every delivered script' {
        foreach ($file in (Get-ChildItem -LiteralPath $RepositoryRoot -Filter '*.ps1' -File -Recurse)) {
            $tokens=$null; $errors=$null
            [System.Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors) | Out-Null
            Assert-True ($errors.Count -eq 0) ("Parser error in " + $file.FullName + ': ' + ($errors | Out-String))
        }
    }
    Check 'Bundled native Python archive checksum and startup' {
        $pythonArchive = Join-Path $control 'windows/python-3.14.10-embed-amd64.zip'
        $manifest = Get-Content -Raw -LiteralPath (Join-Path $control 'FILE_MANIFEST.json') | ConvertFrom-Json
        $entry = @($manifest.files | Where-Object { $_.path -eq 'windows/python-3.14.10-embed-amd64.zip' })[0]
        Assert-True ((Get-FileHash -Algorithm SHA256 -LiteralPath $pythonArchive).Hash -eq $entry.sha256) 'Native Python archive digest mismatch.'
        $pythonDirectory = Join-Path $tempRoot 'python'
        Expand-Archive -LiteralPath $pythonArchive -DestinationPath $pythonDirectory
        $script:pythonExe = Join-Path $pythonDirectory 'python.exe'
        & $script:pythonExe --version
        Assert-True ($LASTEXITCODE -eq 0) 'Bundled Windows Python cannot start.'
    }
    Check 'Actual Windows manifest verification and six-toolkit extraction' {
        Assert-True ([bool]$script:pythonExe) 'Python startup did not succeed.'
        $env:OVA_CONTROL_ROOT=$control
        $stderrFile=Join-Path $tempRoot 'python-stderr.txt'
        $savedPreference=$ErrorActionPreference
        try {
            $ErrorActionPreference='Continue'
            & $script:pythonExe -B (Join-Path $RepositoryRoot 'tests/test_control_helpers.py') 2> $stderrFile
            $pythonExit=$LASTEXITCODE
        } finally { $ErrorActionPreference=$savedPreference }
        if (Test-Path -LiteralPath $stderrFile) { Get-Content -LiteralPath $stderrFile | ForEach-Object { Write-Output "$_" } }
        Assert-True ($pythonExit -eq 0) 'Native Windows Python acceptance failed.'
    }
    # These functions deliberately shadow executables, preventing network traffic.
    $global:OvaFixture = Join-Path $tempRoot 'fixture.zip'
    [IO.File]::WriteAllBytes($global:OvaFixture,[byte[]](1,2,3,4,5))
    $global:OvaExpectedDigest=(Get-FileHash -Algorithm SHA256 -LiteralPath $global:OvaFixture).Hash.ToLowerInvariant()
    $global:OvaSftpBatch=''
    function global:ssh.exe {
        $global:OvaTransportCalls.Add([pscustomobject]@{ tool='ssh'; arguments=@($args) })
        $global:LASTEXITCODE=0
        if ($args[-1] -like 'sha256sum*') { Write-Output ($global:OvaExpectedDigest + '  release.zip') }
    }
    function global:scp.exe {
        $global:OvaTransportCalls.Add([pscustomobject]@{ tool='scp'; arguments=@($args) })
        $global:LASTEXITCODE=0
    }
    function global:sftp.exe {
        $global:OvaTransportCalls.Add([pscustomobject]@{ tool='sftp'; arguments=@($args) })
        $batchIndex=[Array]::IndexOf($args,'-b')
        $global:OvaSftpBatch=Get-Content -Raw -LiteralPath $args[$batchIndex+1]
        Assert-True ($global:OvaSftpBatch -match '^get "[^"]+" "([^"]+)"\s*$') 'Unexpected SFTP command.'
        Copy-Item -LiteralPath $global:OvaFixture -Destination $Matches[1]
        $global:LASTEXITCODE=0
    }
    Check 'Native download path quoting and digest verification (mock transport)' {
        $key=Join-Path $tempRoot 'fixture key'; [IO.File]::WriteAllText($key,'NOT A KEY; MOCK ONLY')
        $download=Join-Path $tempRoot 'space directory/download.zip'
        & (Join-Path $control 'scripts/Download-Release.ps1') -SftpUser 'fixture-user' -IdentityFile $key -RemoteZip '/nvidia-space/shared/IREN_MKZ/fixture.zip' -Destination $download -ExpectedSha256 $global:OvaExpectedDigest
        Assert-True (Test-Path -LiteralPath $download) 'Download fixture was not created.'
        Expect-Rejection { & (Join-Path $control 'scripts/Download-Release.ps1') -SftpUser 'fixture-user' -IdentityFile $key -RemoteZip '/nvidia-space/shared/IREN_MKZ/fixture.zip' -Destination $download -ExpectedSha256 $global:OvaExpectedDigest }
    }
    Check 'Native upload read-back and scoped staging (mock transport)' {
        & (Join-Path $control 'scripts/Send-Release.ps1') -SshAlias 'fixture-host' -BundleZip $global:OvaFixture -ExpectedSha256 $global:OvaExpectedDigest -ReleaseId 'fixture-1'
        $before=$global:OvaTransportCalls.Count
        Expect-Rejection { & (Join-Path $control 'scripts/Send-Release.ps1') -SshAlias 'fixture-host' -BundleZip $global:OvaFixture -ExpectedSha256 ('0'*64) -ReleaseId 'fixture-2' }
        Assert-True ($before -eq $global:OvaTransportCalls.Count) 'Bad digest reached transport.'
    }
    Check 'Native tunnel and remote-inventory construction (mock transport)' {
        & (Join-Path $control 'scripts/Open-ToolTunnel.ps1') -SshAlias 'fixture-host' -LocalPort 14301 -RemotePort 4301
        & (Join-Path $control 'scripts/Test-RemoteLinux.ps1') -SshAlias 'fixture-host'
        $before=$global:OvaTransportCalls.Count
        Expect-Rejection { & (Join-Path $control 'scripts/Open-ToolTunnel.ps1') -SshAlias '-bad' -LocalPort 14301 -RemotePort 4301 }
        Expect-Rejection { & (Join-Path $control 'scripts/Test-RemoteLinux.ps1') -SshAlias "bad`ncommand" }
        Assert-True ($before -eq $global:OvaTransportCalls.Count) 'Invalid alias reached transport.'
        foreach ($call in $global:OvaTransportCalls) {
            Assert-True ($call.arguments -contains 'StrictHostKeyChecking=yes') 'SSH host trust was not enforced.'
            Assert-True ($call.arguments -contains 'BatchMode=yes') 'Unattended SSH batch mode missing.'
        }
        $tunnels=@($global:OvaTransportCalls | Where-Object { $_.arguments -contains '-L' })
        Assert-True ($tunnels.Count -eq 1) 'Expected one mocked tunnel.'
        Assert-True ($tunnels[0].arguments -contains '127.0.0.1:14301:127.0.0.1:4301') 'Tunnel was not limited to local loopback.'
    }
} finally {
    foreach ($name in @('ssh.exe','scp.exe','sftp.exe')) { Remove-Item -LiteralPath ('Function:\' + $name) -ErrorAction SilentlyContinue }
    $failed=@($results | Where-Object { $_.status -eq 'failed' }).Count
    $report=[ordered]@{
        schema_version=1; recorded_utc=[DateTime]::UtcNow.ToString('o'); platform=[Environment]::OSVersion.ToString();
        commit_sha=$env:CI_COMMIT_SHA; pipeline_url=$env:CI_PIPELINE_URL; job_id=$env:CI_JOB_ID;
        powershell=$PSVersionTable.PSVersion.ToString(); architecture=$env:PROCESSOR_ARCHITECTURE;
        scope='Native Windows control helpers, hashes, Python archive verification and tool extraction; mocked transport commands';
        excluded=@('Customer VPN','Live SSH/SFTP','Six backend runtime acceptance','GPU jobs','Remediation');
        status=if($failed -eq 0 -and $results.Count -eq 6){'passed'}else{'failed'}; checks=$results.ToArray()
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'windows-controls.json') -Encoding UTF8
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
if ($report.status -ne 'passed') { throw 'Windows control acceptance failed; inspect windows-controls.json.' }
