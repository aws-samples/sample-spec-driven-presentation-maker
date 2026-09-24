# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
[CmdletBinding()]
param([Parameter(Position=0)][string]$Command = "launch")

$ErrorActionPreference = "Stop"
$SdpmHome = if ($env:SDPM_HOME) { $env:SDPM_HOME } else { Join-Path $env:USERPROFILE ".sdpm" }
$Checkout = Join-Path $SdpmHome "checkout"
$MarkerFile = Join-Path $SdpmHome ".update-available"
$LastCheckFile = Join-Path $SdpmHome ".last-update-check"
$RepoUrl = "https://github.com/aws-samples/sample-spec-driven-presentation-maker.git"

function Test-Port3000 {
    $client = New-Object Net.Sockets.TcpClient
    try { $client.Connect("127.0.0.1", 3000); return $true } catch { return $false } finally { $client.Dispose() }
}

function Get-CurrentRevision { return (& git -C $Checkout rev-parse HEAD 2>$null) }
function Get-RemoteRevision {
    $line = (& git -C $Checkout ls-remote origin refs/heads/main 2>$null | Select-Object -First 1)
    if ($line) { return ($line -split '\s+')[0] }
    return $null
}

function Start-UpdateCheck {
    if (-not (Test-Path (Join-Path $Checkout ".git"))) { return }
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $last = 0
    if (Test-Path $LastCheckFile) { [long]::TryParse((Get-Content $LastCheckFile -Raw), [ref]$last) | Out-Null }
    if (($now - $last) -lt 86400) { return }
    Start-Job -ScriptBlock {
        param($CheckoutPath, $Marker, $LastCheck)
        $latestLine = (& git -C $CheckoutPath ls-remote origin refs/heads/main 2>$null | Select-Object -First 1)
        $latest = if ($latestLine) { ($latestLine -split '\s+')[0] } else { $null }
        $current = (& git -C $CheckoutPath rev-parse HEAD 2>$null)
        [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() | Set-Content $LastCheck
        if ($latest -and $latest -ne $current) { $latest | Set-Content $Marker } else { Remove-Item $Marker -ErrorAction SilentlyContinue }
    } -ArgumentList $Checkout, $MarkerFile, $LastCheckFile | Out-Null
}

function Build-Checkout {
    Write-Host "> Syncing local MCP dependencies..."
    & uv sync --directory (Join-Path $Checkout "servers\local")
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
    Push-Location (Join-Path $Checkout "web-ui")
    try {
        & npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
        $env:NEXT_PUBLIC_MODE = "local"
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "Web UI build failed" }
    } finally { Pop-Location }
}

function Invoke-Launch {
    if (-not (Test-Path (Join-Path $Checkout ".git"))) { throw "SDPM is not installed at $Checkout. Re-run the installer." }
    if (Test-Path $MarkerFile) {
        Write-Host "A newer SDPM checkout is available. Run 'sdpm update'." -ForegroundColor Yellow
    }
    if (Test-Port3000) { Start-Process "http://localhost:3000"; return }
    if (-not (Test-Path (Join-Path $Checkout "web-ui\build"))) { throw "Web UI build missing. Run 'sdpm update'." }
    Start-UpdateCheck
    Start-Job -ScriptBlock {
        for ($i = 0; $i -lt 240; $i++) {
            $client = New-Object Net.Sockets.TcpClient
            try {
                $client.Connect("127.0.0.1", 3000); $client.Dispose()
                Start-Process "http://localhost:3000"; return
            } catch { $client.Dispose(); Start-Sleep -Milliseconds 500 }
        }
    } | Out-Null
    Push-Location (Join-Path $Checkout "web-ui")
    try {
        $env:NEXT_PUBLIC_MODE = "local"
        & npm run start -- --hostname 127.0.0.1 --port 3000
        if ($LASTEXITCODE -ne 0) { throw "Next.js server exited with code $LASTEXITCODE" }
    } finally { Pop-Location }
}

function Invoke-Update {
    if (-not (Test-Path (Join-Path $Checkout ".git"))) { throw "Not a git checkout: $Checkout" }
    & git -C $Checkout fetch --tags --prune origin main
    if ($LASTEXITCODE -ne 0) { throw "git fetch failed. Repair the checkout at $Checkout, then rerun 'sdpm update'." }
    & git -C $Checkout checkout main
    if ($LASTEXITCODE -ne 0) { throw "git checkout failed. Repair the checkout at $Checkout, then rerun 'sdpm update'." }
    & git -C $Checkout pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw "git pull failed. Repair the checkout at $Checkout, then rerun 'sdpm update'." }
    Build-Checkout
    Remove-Item $MarkerFile -ErrorAction SilentlyContinue
    Write-Host "Update complete. Run 'sdpm launch'." -ForegroundColor Green
}

function Invoke-Doctor {
    if (-not (Test-Path (Join-Path $Checkout "scripts\doctor.py"))) { throw "SDPM is not installed at $Checkout. Re-run the installer." }
    Push-Location $Checkout
    try {
        & uv run python scripts/doctor.py
        if ($LASTEXITCODE -ne 0) { throw "SDPM doctor failed with exit code $LASTEXITCODE" }
    } finally { Pop-Location }
}

function Invoke-CheckUpdate {
    $latest = Get-RemoteRevision; $current = Get-CurrentRevision
    [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() | Set-Content $LastCheckFile
    if (-not $latest) { throw "Could not query $RepoUrl" }
    if ($latest -eq $current) {
        Write-Host "SDPM is up to date."; Remove-Item $MarkerFile -ErrorAction SilentlyContinue
    } else {
        Write-Host "A newer SDPM checkout is available. Run 'sdpm update'." -ForegroundColor Yellow
        $latest | Set-Content $MarkerFile
    }
}

function Show-Version {
    if (-not (Test-Path (Join-Path $Checkout ".git"))) { throw "Not a git checkout: $Checkout" }
    $ref = (& git -C $Checkout describe --tags --always 2>$null)
    $commit = (& git -C $Checkout rev-parse --short HEAD)
    Write-Host "SDPM version: $ref ($commit)"
}

function Show-Help {
@"
Usage: sdpm [COMMAND]

Commands:
  launch        Start the built Local Web UI (default) and open a browser
  update        Pull main, sync dependencies, and rebuild the Local Web UI
  check-update  Check whether the installed checkout is behind main
  doctor        Run the repository environment doctor
  version       Show the installed revision
  path          Print the checkout path
  help          Show this help
"@ | Write-Host
}

switch ($Command.ToLowerInvariant()) {
    "launch" { Invoke-Launch }
    "update" { Invoke-Update }
    "check-update" { Invoke-CheckUpdate }
    "doctor" { Invoke-Doctor }
    "version" { Show-Version }
    "--version" { Show-Version }
    "-v" { Show-Version }
    "path" { Write-Output $Checkout }
    "help" { Show-Help }
    "--help" { Show-Help }
    "-h" { Show-Help }
    default { Write-Error "Unknown command: $Command"; Show-Help; exit 2 }
}
