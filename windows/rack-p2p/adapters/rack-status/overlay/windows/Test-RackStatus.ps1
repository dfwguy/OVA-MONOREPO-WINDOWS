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
    [string]$CertificatePath = '',
    [string]$Hostname = 'localhost',
    [ValidateRange(1,65535)][int]$Port = 5050,
    [ValidateRange(1,45)][int]$ReadyTimeoutSeconds = 30
)
$ErrorActionPreference = 'Stop'
if (-not $CertificatePath) { $CertificatePath = Join-Path (Split-Path -Parent $PSScriptRoot) 'var\secrets\tls\server.crt' }
& $PythonExecutable (Join-Path $PSScriptRoot 'verify_runtime.py') --host $Hostname --port $Port --certificate $CertificatePath --timeout $ReadyTimeoutSeconds
if ($LASTEXITCODE -ne 0) { throw 'Rack Status HTTPS/auth/frontend verification failed' }
Get-CimInstance Win32_Service -Filter "Name='NVISRackStatus'" | Select-Object Name,State,StartMode,StartName
