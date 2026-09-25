# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# sdpm — the one launcher for a local SDPM installation (%USERPROFILE%\.sdpm).
#   sdpm webui      browser surface
#   sdpm mcp        MCP surface (terminal check; clients get the uv command directly)
#   sdpm register   wire the MCP server into the clients on this machine
# Client detection, configuration rendering and registration commands live once in
# servers/local/client_config.py; this file and launcher.sh only delegate to it.
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Command = "",
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest = @()
)

$ErrorActionPreference = "Stop"
$SdpmHome = if ($env:SDPM_HOME) { $env:SDPM_HOME } else { Join-Path $env:USERPROFILE ".sdpm" }
$Checkout = Join-Path $SdpmHome "checkout"
$ProfileFile = Join-Path $SdpmHome ".profile"
$UvPathFile = Join-Path $SdpmHome ".uv-path"
$RepoUrl = "https://github.com/aws-samples/sample-spec-driven-presentation-maker.git"
$WebUiPort = if ($env:SDPM_WEBUI_PORT) { [int]$env:SDPM_WEBUI_PORT } else { 3000 }
$ServerDir = Join-Path $Checkout "servers\local"

# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

function Assert-Checkout {
    if (-not (Test-Path (Join-Path $Checkout ".git"))) { throw "SDPM is not installed at $Checkout. Re-run the installer." }
}

function Get-Profile {
    if (Test-Path $ProfileFile) { return (Get-Content $ProfileFile -Raw).Trim() }
    return "full"
}

function Test-WebUiInstalled {
    return ((Get-Profile) -eq "full") -and (Test-Path (Join-Path $Checkout "web-ui\build"))
}

# Absolute path of uv, recorded by the installer; re-resolved and re-recorded if stale.
function Resolve-Uv {
    if (Test-Path $UvPathFile) {
        $recorded = (Get-Content $UvPathFile -Raw).Trim()
        if ($recorded -and (Test-Path $recorded)) { return $recorded }
    }
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    $found = if ($cmd) { $cmd.Source } else { Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
    if (-not (Test-Path $found)) { throw "uv not found. Re-run the installer (it installs uv)." }
    $found = [System.IO.Path]::GetFullPath($found)
    New-Item -ItemType Directory -Force -Path $SdpmHome | Out-Null
    $found | Set-Content -Path $UvPathFile -Encoding ASCII
    return $found
}

# Run a Python entry point inside the local server's environment. The native command's
# output flows straight through; the caller reads $LASTEXITCODE. Nothing of our own on stdout.
function Invoke-Py {
    param([string[]]$PyArgs)
    $uv = Resolve-Uv
    & $uv run --directory $ServerDir python @PyArgs
}

# client_config.py, told exactly which uv and checkout the clients must point at.
function Invoke-Cfg {
    param([string[]]$CfgArgs)
    $uv = Resolve-Uv
    & $uv run --directory $ServerDir python client_config.py --uv $uv --checkout $Checkout @CfgArgs
}

# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------

function Test-Port {
    $client = New-Object Net.Sockets.TcpClient
    try { $client.Connect("127.0.0.1", $WebUiPort); return $true } catch { return $false } finally { $client.Dispose() }
}

function Invoke-WebUi {
    Assert-Checkout
    if (-not (Test-WebUiInstalled)) {
        Write-Host "The browser Web UI is not installed in this profile ($(Get-Profile))." -ForegroundColor Yellow
        Write-Host "Add it with:  sdpm update --with-webui   (needs Node.js 20+)"
        exit 1
    }
    if (Test-Port) { Start-Process "http://localhost:$WebUiPort"; return }
    Start-Job -ScriptBlock {
        param($Port)
        for ($i = 0; $i -lt 240; $i++) {
            $client = New-Object Net.Sockets.TcpClient
            try { $client.Connect("127.0.0.1", $Port); $client.Dispose(); Start-Process "http://localhost:$Port"; return }
            catch { $client.Dispose(); Start-Sleep -Milliseconds 500 }
        }
    } -ArgumentList $WebUiPort | Out-Null
    Push-Location (Join-Path $Checkout "web-ui")
    try {
        $env:NEXT_PUBLIC_MODE = "local"
        & npm run start -- --hostname 127.0.0.1 --port $WebUiPort
        if ($LASTEXITCODE -ne 0) { throw "Next.js server exited with code $LASTEXITCODE" }
    } finally { Pop-Location }
}

function Invoke-Mcp {
    Assert-Checkout
    # Foreground stdio server. The child inherits this process's stdin/stdout handles
    # directly (no PowerShell pipeline in the byte path), so JSON-RPC framing survives.
    $uv = Resolve-Uv
    # -ArgumentList joins with spaces and drops PowerShell's quotes; quote each argument ourselves
    # so a checkout under a path with spaces survives.
    $quoted = @("run", "--directory", $ServerDir, "python", "server.py") | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }
    $proc = Start-Process -FilePath $uv -ArgumentList ($quoted -join " ") -NoNewWindow -Wait -PassThru
    exit $proc.ExitCode
}

# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

function Invoke-Step {
    param([string]$What, [scriptblock]$Action)
    Write-Host "> $What..."
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "SDPM update failed while $What (exit $LASTEXITCODE). Review the output above and repair the checkout at $Checkout, then rerun 'sdpm update'."
    }
}

function Build-Mcp {
    $uv = Resolve-Uv
    Invoke-Step "Syncing the MCP server environment" { & $uv sync --directory $ServerDir }
    Invoke-Step "Installing icon catalogs" { & $uv run --directory $ServerDir python -m sdpm.knowledge.assets.download --sources aws,material }
}

function Build-WebUi {
    Push-Location (Join-Path $Checkout "web-ui")
    try {
        Invoke-Step "Installing Web UI dependencies" { & npm ci }
        $env:NEXT_PUBLIC_MODE = "local"
        Invoke-Step "Building the Web UI (Local mode)" { & npm run build }
    } finally { Pop-Location }
}

function Invoke-Update {
    Assert-Checkout
    $withWebUi = $Rest -contains "--with-webui"
    Write-Host "> Fetching main from $RepoUrl"
    Invoke-Step "Fetching main" { & git -C $Checkout fetch --tags --prune origin main }
    Invoke-Step "Checking out main" { & git -C $Checkout checkout -q main }
    Invoke-Step "Fast-forwarding main" { & git -C $Checkout pull -q --ff-only origin main }
    Build-Mcp
    if ($withWebUi) {
        if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js 20+ is required for the Web UI: https://nodejs.org/" }
        "full" | Set-Content -Path $ProfileFile -Encoding ASCII
    }
    if ((Get-Profile) -eq "full") { Build-WebUi }
    Write-Host "Update complete." -ForegroundColor Green
    if ((Get-Profile) -eq "full") { Write-Host "  sdpm webui     open the browser Web UI" }
    else { Write-Host "  sdpm webui     (not installed - sdpm update --with-webui)" }
    Write-Host "  sdpm register  connect your MCP clients"
}

function Invoke-Uninstall {
    Assert-Checkout
    Write-Host "This removes $SdpmHome, the sdpm command and shortcuts."
    $answer = Read-Host "Continue? [y/N]"
    if ($answer -notmatch '^[Yy]$') { Write-Host "Aborted."; return }
    try { Invoke-Cfg @("unregister") } catch { }
    $launcherDir = if ($env:SDPM_LAUNCHER_DIR) { $env:SDPM_LAUNCHER_DIR } else { Join-Path $env:USERPROFILE "bin" }
    Remove-Item (Join-Path $launcherDir "sdpm.cmd"), (Join-Path $launcherDir "sdpm.ps1") -ErrorAction SilentlyContinue
    Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "SDPM.lnk") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $SdpmHome -ErrorAction SilentlyContinue
    Write-Host "SDPM removed."
}

function Get-Version {
    Assert-Checkout
    $ref = (& git -C $Checkout describe --tags --always 2>$null)
    $commit = (& git -C $Checkout rev-parse --short HEAD)
    return "$ref ($commit)"
}

function Show-Status {
    Assert-Checkout
    Write-Host "SDPM $(Get-Version)"
    Write-Host "  checkout   $Checkout"
    Write-Host "  profile    $(Get-Profile)"
    if (Test-WebUiInstalled) { Write-Host "  webui      installed        -> sdpm webui" }
    else { Write-Host "  webui      not installed    -> sdpm update --with-webui" }
    Write-Host "  mcp        installed        -> sdpm register  (connect your MCP clients)"
    Write-Host ""
    try { Invoke-Cfg @("status") } catch { }
}

function Show-Help {
@"
Usage: sdpm [COMMAND]

Surfaces
  webui                 Start the browser Web UI and open it
  mcp                   Run the MCP server on stdio (terminal check)

MCP clients
  register [CLIENT..]   Register the server with detected (or named) clients
  unregister [CLIENT..] Remove it again
  mcp-config [CLIENT..] Print the configuration with this machine's paths (--json, --all)

Maintenance
  update [--with-webui] Pull main, sync dependencies, rebuild what is installed
  doctor                Check the local environment
  uninstall             Remove SDPM from this machine
  version | path | help

No command: show status.
"@ | Write-Host
}

switch ($Command.ToLowerInvariant()) {
    "" { Show-Status }
    "webui" { Invoke-WebUi }
    "launch" { Invoke-WebUi }
    "mcp" { Invoke-Mcp }
    "register" { Assert-Checkout; Invoke-Cfg (@("register") + $Rest); exit $LASTEXITCODE }
    "unregister" { Assert-Checkout; Invoke-Cfg (@("unregister") + $Rest); exit $LASTEXITCODE }
    "mcp-config" { Assert-Checkout; Invoke-Cfg (@("print") + $Rest); exit $LASTEXITCODE }
    "update" { Invoke-Update }
    "doctor" { Assert-Checkout; Push-Location $Checkout; try { & uv run python scripts/doctor.py; exit $LASTEXITCODE } finally { Pop-Location } }
    "uninstall" { Invoke-Uninstall }
    "version" { Write-Output (Get-Version) }
    "--version" { Write-Output (Get-Version) }
    "-v" { Write-Output (Get-Version) }
    "path" { Write-Output $Checkout }
    "help" { Show-Help }
    "--help" { Show-Help }
    "-h" { Show-Help }
    default { Write-Error "Unknown command: $Command"; Show-Help; exit 2 }
}
