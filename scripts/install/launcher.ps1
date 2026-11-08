# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# sdpm — the one launcher for a local SDPM installation (%USERPROFILE%\.sdpm).
# sdpm-bootstrap 1
#
# A bootstrap: it finds the checkout and uv, and hands every command to the checkout.
#   sdpm update   fetch, then the checkout's servers\local\checkout_update.py (it follows the
#                 latest release, or main with --channel main, and never moves backwards)
#   anything else servers\local\sdpm_command.py (status, webui, mcp, register, doctor, ...)
# Everything that can change between versions lives in those two files, so this one stays
# as it is. launcher.sh is the same file for macOS and Linux, line for line.

$ErrorActionPreference = "Continue"   # native commands report through $LASTEXITCODE
$SdpmHome = if ($env:SDPM_HOME) { $env:SDPM_HOME } else { Join-Path $env:USERPROFILE ".sdpm" }
$Checkout = Join-Path $SdpmHome "checkout"
$UvPathFile = Join-Path $SdpmHome ".uv-path"
# This file, as installed (the copy `sdpm update` refreshes).
$Self = $PSCommandPath

# Absolute path of uv, recorded at install time; re-resolved and re-recorded if stale.
function Resolve-Uv {
    if (Test-Path $UvPathFile) {
        $recorded = (Get-Content $UvPathFile -Raw).Trim()
        if ($recorded -and (Test-Path $recorded)) { return $recorded }
    }
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    $found = if ($cmd) { $cmd.Source } else { Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
    if (-not (Test-Path $found)) { Write-Host "uv not found. Re-run the installer (it installs uv)." -ForegroundColor Red; exit 1 }
    $found = [System.IO.Path]::GetFullPath($found)
    New-Item -ItemType Directory -Force -Path $SdpmHome | Out-Null
    $found | Set-Content -Path $UvPathFile -Encoding ASCII
    return $found
}

# Start-Process joins its arguments with spaces; quote each one so paths with spaces survive.
function Join-Arguments {
    param([string[]]$Values)
    return (($Values | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join " ")
}

if (-not (Test-Path (Join-Path $Checkout ".git"))) { Write-Host "SDPM is not installed at $Checkout. Re-run the installer." -ForegroundColor Red; exit 1 }
$uv = Resolve-Uv
# No project, a fresh environment (never a .venv or VIRTUAL_ENV), Python 3.11+.
$py = @("run", "--no-project", "--isolated", "--python", ">=3.11", "python")
$rest = @($args)

if ($rest.Count -gt 0 -and $rest[0] -eq "update") {
    $rest = @($rest | Select-Object -Skip 1)
    & git -C $Checkout fetch --quiet --prune origin "+refs/heads/main:refs/remotes/origin/main" "+refs/tags/*:refs/tags/*"
    if ($LASTEXITCODE -ne 0) {
        $origin = "$(& git -C $Checkout remote get-url origin 2>$null)".Trim()
        Write-Host "sdpm update could not fetch from $origin; nothing was changed." -ForegroundColor Red; exit 1
    }
    $updater = Join-Path $Checkout "servers\local\checkout_update.py"
    if ((Test-Path $updater) -and (Select-String -Path $updater -Pattern '^UPDATER_CONTRACT = ' -Quiet)) {
        & $uv @py $updater --checkout $Checkout --uv $uv update --launcher $Self @rest
        exit $LASTEXITCODE
    }
    # Only a checkout reset by hand gets here: run origin/main's file from a temp dir.
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("sdpm-update-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        & git -C $Checkout "--work-tree=$tmp" restore --source=refs/remotes/origin/main --worktree -- servers/local/checkout_update.py
        if ($LASTEXITCODE -ne 0) { exit 1 }
        & $uv @py (Join-Path $tmp "servers\local\checkout_update.py") --checkout $Checkout --uv $uv update --launcher $Self @rest
        $rc = $LASTEXITCODE
    } finally { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
    exit $rc
}

$cmd = Join-Path $Checkout "servers\local\sdpm_command.py"
if (-not (Test-Path $cmd)) { Write-Host "This checkout predates the sdpm command; run: sdpm update" -ForegroundColor Red; exit 1 }
if ($rest.Count -gt 0 -and $rest[0] -eq "mcp") {
    # The stdio server: the child inherits this process's handles (no PowerShell pipeline in
    # the byte path), so JSON-RPC framing survives.
    $proc = Start-Process -FilePath $uv -ArgumentList (Join-Arguments (@($py) + @($cmd, "--checkout", $Checkout, "--uv", $uv, "--launcher", $Self) + $rest)) -NoNewWindow -Wait -PassThru
    exit $proc.ExitCode
}
& $uv @py $cmd --checkout $Checkout --uv $uv --launcher $Self @rest
exit $LASTEXITCODE
