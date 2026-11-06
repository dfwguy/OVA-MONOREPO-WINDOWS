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
    [string]$BindAddress = '127.0.0.1',
    [ValidateRange(1,65535)][int]$Port = 5050,
    [string]$LogPath = 'C:\NVIS\logs\rack-status\commissioning.log'
)
$ErrorActionPreference = 'Stop'
$rackRoot = Split-Path -Parent $PSScriptRoot
$rackLogRoot = Split-Path -Parent $LogPath
New-Item -ItemType Directory -Path $rackLogRoot -Force | Out-Null
$rackOwner = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $rackLogRoot /inheritance:r /grant:r "$($rackOwner):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not protect the runtime log directory' }
Push-Location $rackRoot
try {
    # Bootstrap may issue a one-time administrator password. It stays in this
    # protected local log; do not mirror or print this log into a transcript.
    & $PythonExecutable -u (Join-Path $rackRoot 'backend\cli.py') serve --config $ConfigPath --host $BindAddress --port $Port *>> $LogPath
    if ($LASTEXITCODE -ne 0) { throw "Rack Status stopped; inspect protected log at $LogPath" }
} finally { Pop-Location }
