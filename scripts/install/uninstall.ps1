# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
[CmdletBinding()]
param([switch]$NonInteractive)
$sdpmHome = if ($env:SDPM_HOME) { $env:SDPM_HOME } else { Join-Path $env:USERPROFILE ".sdpm" }
$launcherDir = if ($env:SDPM_LAUNCHER_DIR) { $env:SDPM_LAUNCHER_DIR } else { Join-Path $env:USERPROFILE "bin" }
$shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "SDPM.lnk"
if (-not $NonInteractive -and $env:SDPM_NON_INTERACTIVE -ne "1") {
    $reply = Read-Host "Remove $sdpmHome, $launcherDir\sdpm.*, and the SDPM desktop shortcut? [y/N]"
    if ($reply -notmatch '^[Yy]') { Write-Host "Cancelled."; return }
}
Remove-Item $sdpmHome -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $launcherDir "sdpm.ps1") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $launcherDir "sdpm.cmd") -Force -ErrorAction SilentlyContinue
Remove-Item $shortcut -Force -ErrorAction SilentlyContinue
Write-Host "SDPM was removed. Shared dependencies were kept." -ForegroundColor Green
