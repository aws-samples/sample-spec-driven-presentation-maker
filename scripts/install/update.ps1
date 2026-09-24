# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
$launcherDir = if ($env:SDPM_LAUNCHER_DIR) { $env:SDPM_LAUNCHER_DIR } else { Join-Path $env:USERPROFILE "bin" }
$installed = Join-Path $launcherDir "sdpm.ps1"
if (Test-Path $installed) { & $installed update; exit $LASTEXITCODE }
& (Join-Path $PSScriptRoot "launcher.ps1") update
exit $LASTEXITCODE
