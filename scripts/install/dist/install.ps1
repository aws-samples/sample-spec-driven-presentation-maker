# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# SDPM installer for Windows. The generated dist/install.ps1 is the standalone
# irm | iex entry point.
[CmdletBinding()]
param(
    [switch]$Full,
    [switch]$McpOnly,
    [switch]$Register,
    [switch]$NoRegister,
    [switch]$DepsOnly,
    [switch]$NonInteractive,
    [switch]$SkipLibreOffice,
    [switch]$SkipShortcut
)
# __INSTALL_BODY_BELOW__
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# Shared installer TUI helpers (Windows PowerShell 5.1 compatible).

$script:TotalSteps = 0
$script:CurrentStep = 0

function Show-Header {
    param([string]$Title = "SDPM Setup", [string]$Version = "")
    if ($Host.Name -ne "ServerRemoteHost" -and -not [Console]::IsOutputRedirected) {
        try { Clear-Host } catch { }
    }
    Write-Host ""
    Write-Host "  ===========================================" -ForegroundColor Cyan
    Write-Host "  $Title  v$Version" -ForegroundColor Cyan
    Write-Host "  ===========================================" -ForegroundColor Cyan
    Write-Host ""
}

function Show-Check {
    param([string]$Name, [string]$Version, [bool]$Found)
    if ($Found) {
        Write-Host "    [OK] " -ForegroundColor Green -NoNewline
        Write-Host "$Name $Version"
    } else {
        Write-Host "    [--] " -ForegroundColor Red -NoNewline
        Write-Host "$Name not installed" -ForegroundColor DarkGray
    }
}

function Start-Step {
    param([string]$Message, [string]$Detail = "")
    $script:CurrentStep++
    Write-Host ""
    Write-Host "    [>] $Message [$($script:CurrentStep)/$($script:TotalSteps)]" -ForegroundColor Cyan
    if ($Detail) { Write-Host "        $Detail" -ForegroundColor DarkGray }
}

function Complete-Step { param([string]$Message); Write-Host "    [OK] $Message" -ForegroundColor Green }

function Fail-Step {
    param([string]$Message, [string]$Log = "", [string]$HelpUrl = "")
    Write-Host "    [ERROR] $Message" -ForegroundColor Red
    if ($Log) {
        Write-Host "    ---- Last log lines ----------------------" -ForegroundColor DarkGray
        $Log -split "`r?`n" | Select-Object -Last 10 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        Write-Host "    ------------------------------------------" -ForegroundColor DarkGray
    }
    if ($HelpUrl) { Write-Host "    Recovery: $HelpUrl" -ForegroundColor Yellow }
}

function Show-Confirm {
    param([string]$Prompt)
    if ($script:NonInteractive) { return $true }
    $reply = Read-Host "$Prompt [Y/n]"
    return (-not $reply -or $reply -match '^[Yy]')
}

function Has-Command { param([string]$Name); return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user;$env:USERPROFILE\.local\bin;$env:USERPROFILE\bin"
}

function ConvertTo-ProcessArgument {
    param([string]$Value)
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

function Run-WithSpinner {
    param([string]$Exe, [string[]]$Arguments, [string]$WorkDir = "", [hashtable]$Env = @{})
    $resolved = (Get-Command $Exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    if (-not $resolved) { $resolved = (Get-Command $Exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source }
    if (-not $resolved) { $resolved = $Exe }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $argLine = (($Arguments | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join ' ')
    if ($resolved -match '\.(cmd|bat)$') {
        $psi.FileName = "cmd.exe"
        $psi.Arguments = "/d /s /c `"`"$resolved`" $argLine`""
    } else {
        $psi.FileName = $resolved
        $psi.Arguments = $argLine
    }
    if ($WorkDir) { $psi.WorkingDirectory = $WorkDir }
    foreach ($key in $Env.Keys) { $psi.EnvironmentVariables[$key] = [string]$Env[$key] }

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    try { $process = [Diagnostics.Process]::Start($psi) } catch {
        return @{ Success=$false; Output=$_.Exception.Message; Elapsed="00:00"; ExitCode=-1 }
    }
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    while (-not $process.HasExited) { Start-Sleep -Milliseconds 100 }
    $process.WaitForExit(); $stopwatch.Stop()
    return @{
        Success = ($process.ExitCode -eq 0)
        Output = "$($stdout.Result)`n$($stderr.Result)"
        Elapsed = $stopwatch.Elapsed.ToString('mm\:ss')
        ExitCode = $process.ExitCode
    }
}

$script:EmbeddedLauncher = @'
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
    $proc = Start-Process -FilePath $uv -ArgumentList @("run", "--directory", $ServerDir, "python", "server.py") -NoNewWindow -Wait -PassThru
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
'@

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$script:NonInteractive = $NonInteractive -or $env:SDPM_NON_INTERACTIVE -eq "1"
if ($env:SDPM_SKIP_LIBREOFFICE -eq "1") { $SkipLibreOffice = $true }
if ($env:SDPM_SKIP_SHORTCUT -eq "1") { $SkipShortcut = $true }
# Profile: full | mcp. Asked interactively when neither switch nor SDPM_PROFILE is given.
$script:Profile = if ($Full) { "full" } elseif ($McpOnly) { "mcp" } elseif ($env:SDPM_PROFILE) { $env:SDPM_PROFILE } else { "" }
# Registration: ask | yes | no
$script:RegisterMode = if ($Register) { "yes" } elseif ($NoRegister) { "no" } elseif ($env:SDPM_REGISTER) { $env:SDPM_REGISTER } else { "ask" }
$InstallerVersion = "0.1.0"
$RepoUrl = if ($env:SDPM_REPO_URL) { $env:SDPM_REPO_URL } else { "https://github.com/aws-samples/sample-spec-driven-presentation-maker.git" }
$RepoHelp = "https://github.com/aws-samples/sample-spec-driven-presentation-maker"
$SdpmHome = if ($env:SDPM_HOME) { $env:SDPM_HOME } else { Join-Path $env:USERPROFILE ".sdpm" }
$Checkout = Join-Path $SdpmHome "checkout"
$LauncherDir = if ($env:SDPM_LAUNCHER_DIR) { $env:SDPM_LAUNCHER_DIR } else { Join-Path $env:USERPROFILE "bin" }
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }

if (-not (Get-Command Show-Header -ErrorAction SilentlyContinue)) {
    $tuiPath = Join-Path $ScriptDir "lib\tui.ps1"
    if (-not (Test-Path $tuiPath)) { throw "Installer TUI library is missing. Run scripts/install/build.sh and use dist/install.ps1." }
    . $tuiPath
}

function Get-Dependencies {
    $items = @()
    $items += @{ Name="winget"; Found=(Has-Command "winget"); Version="package manager"; Reason="dependency installation"; Id=""; Url="https://aka.ms/getwinget" }
    $items += @{ Name="git"; Found=(Has-Command "git"); Version=$(if (Has-Command "git") { (& git --version) -replace '^git version ','' } else { "" }); Reason="source checkout"; Id="Git.Git"; Url="https://git-scm.com/download/win" }
    $items += @{ Name="uv"; Found=(Has-Command "uv"); Version=$(if (Has-Command "uv") { & uv --version } else { "" }); Reason="Python environment"; Id=""; Url="https://docs.astral.sh/uv/" }
    if (-not $SkipLibreOffice) {
        $soffice = Join-Path $env:ProgramFiles "LibreOffice\program\soffice.exe"
        $items += @{ Name="LibreOffice"; Found=(Test-Path $soffice); Version=$(if (Test-Path $soffice) { "installed" } else { "" }); Reason="slide previews"; Id="TheDocumentFoundation.LibreOffice"; Url="https://www.libreoffice.org/download/" }
    }
    $items += @{ Name="poppler"; Found=(Has-Command "pdftoppm"); Version=$(if (Has-Command "pdftoppm") { "installed" } else { "" }); Reason="PDF previews"; Id="oschwartz10612.Poppler"; Url="https://github.com/oschwartz10612/poppler-windows/releases" }
    if (-not $DepsOnly -and $script:Profile -eq "full") {
        $hasNode = Has-Command "node"
        $nodeVersion = if ($hasNode) { (& node --version).TrimStart('v') } else { "" }
        $nodeSupported = $hasNode -and ([int]($nodeVersion -split '\.')[0] -ge 20)
        $items += @{ Name="Node.js"; Found=$nodeSupported; Version=$(if ($nodeSupported) { "v$nodeVersion" } elseif ($hasNode) { "v$nodeVersion (20+ required)" } else { "" }); Reason="Web UI"; Id="OpenJS.NodeJS.LTS"; Url="https://nodejs.org/" }
        $items += @{ Name="kiro-cli"; Found=(Has-Command "kiro-cli"); Version=$(if (Has-Command "kiro-cli") { "installed" } else { "" }); Reason="Local ACP agent"; Id=""; Url="https://kiro.dev/docs/cli/setup/" }
    }
    return $items
}

function Test-DependencyAvailable {
    param([string]$Name)
    switch ($Name) {
        "git" { return (Has-Command "git") }
        "Node.js" {
            if (-not (Has-Command "node")) { return $false }
            return ([int](((& node --version).TrimStart('v') -split '\.')[0]) -ge 20)
        }
        "LibreOffice" { return (Test-Path (Join-Path $env:ProgramFiles "LibreOffice\program\soffice.exe")) }
        "poppler" { return (Has-Command "pdftoppm") }
        default { return $false }
    }
}

function Install-WingetDependency {
    param([hashtable]$Dependency)
    Start-Step "Installing $($Dependency.Name)" $Dependency.Reason
    $result = Run-WithSpinner -Exe "winget" -Arguments @("install", "--exact", "--id", $Dependency.Id, "--silent", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity")
    Refresh-Path
    if (-not $result.Success -or -not (Test-DependencyAvailable -Name $Dependency.Name)) {
        Fail-Step "$($Dependency.Name) installation failed or is not on PATH" $result.Output $Dependency.Url
        exit 1
    }
    Complete-Step "$($Dependency.Name) installed ($($result.Elapsed))"
}

function Install-Uv {
    Start-Step "Installing uv" "Python package and runtime manager"
    try {
        Invoke-RestMethod "https://astral.sh/uv/install.ps1" | Invoke-Expression
        Refresh-Path
        if (-not (Has-Command "uv")) { throw "uv command is still unavailable" }
        Complete-Step "uv installed"
    } catch { Fail-Step "uv installation failed" $_.Exception.Message "https://docs.astral.sh/uv/"; exit 1 }
}

function Install-KiroCli {
    Start-Step "Installing Kiro CLI" "Local Web UI ACP backend"
    try {
        Invoke-RestMethod "https://cli.kiro.dev/install.ps1" | Invoke-Expression
        Refresh-Path
        if (-not (Has-Command "kiro-cli")) { throw "kiro-cli command is still unavailable" }
        Complete-Step "Kiro CLI installed"
    } catch { Fail-Step "Kiro CLI installation failed" $_.Exception.Message "https://kiro.dev/docs/cli/setup/"; exit 1 }
}

function Install-MissingDependencies {
    param([object[]]$Dependencies)
    foreach ($dependency in $Dependencies) { Show-Check -Name $dependency.Name -Version $dependency.Version -Found $dependency.Found }
    $missing = @($Dependencies | Where-Object { -not $_.Found })
    if ($missing.Count -eq 0) { Write-Host "`n    All required dependencies are available." -ForegroundColor Green; return }
    $winget = $Dependencies | Where-Object { $_.Name -eq "winget" } | Select-Object -First 1
    $wingetPackages = @($missing | Where-Object { $_.Id })
    if ($wingetPackages.Count -gt 0 -and -not $winget.Found) {
        Fail-Step "winget is required to install missing dependencies" "Install App Installer from Microsoft Store." $winget.Url
        exit 1
    }
    Write-Host "`n    Missing dependencies:"
    foreach ($item in $missing) { if ($item.Name -ne "winget") { Write-Host "      - $($item.Name) ($($item.Reason))" } }
    if (-not (Show-Confirm "Install missing dependencies?")) { Write-Host "Installation cancelled."; exit 0 }
    $script:TotalSteps += @($missing | Where-Object { $_.Name -ne "winget" }).Count
    foreach ($item in $missing) {
        switch ($item.Name) {
            "winget" { }
            "uv" { Install-Uv }
            "kiro-cli" { Install-KiroCli }
            default { Install-WingetDependency -Dependency $item }
        }
    }
}

function Setup-Checkout {
    Start-Step "Downloading SDPM" $Checkout
    New-Item -ItemType Directory -Force -Path $SdpmHome | Out-Null
    if (Test-Path (Join-Path $Checkout ".git")) {
        $result = Run-WithSpinner -Exe "git" -Arguments @("-C", $Checkout, "fetch", "--tags", "--prune", "origin", "main")
        if (-not $result.Success) { Fail-Step "SDPM fetch failed" $result.Output $RepoHelp; exit 1 }

        $result = Run-WithSpinner -Exe "git" -Arguments @("-C", $Checkout, "checkout", "main")
        if (-not $result.Success) { Fail-Step "SDPM checkout failed" $result.Output $RepoHelp; exit 1 }

        $result = Run-WithSpinner -Exe "git" -Arguments @("-C", $Checkout, "pull", "--ff-only", "origin", "main")
        if (-not $result.Success) { Fail-Step "SDPM pull failed" $result.Output $RepoHelp; exit 1 }
        Complete-Step "SDPM checkout updated ($($result.Elapsed))"
    } elseif (Test-Path $Checkout) {
        Fail-Step "$Checkout exists but is not a git checkout" "Move it aside and retry." $RepoHelp; exit 1
    } else {
        $result = Run-WithSpinner -Exe "git" -Arguments @("clone", "--branch", "main", "--single-branch", $RepoUrl, $Checkout)
        if (-not $result.Success) { Fail-Step "SDPM clone failed" $result.Output $RepoHelp; exit 1 }
        Complete-Step "SDPM checkout created ($($result.Elapsed))"
    }
}

function Setup-Packages {
    Start-Step "Syncing the MCP server environment" "servers/local"
    $result = Run-WithSpinner -Exe "uv" -Arguments @("sync", "--directory", (Join-Path $Checkout "servers\local"))
    if (-not $result.Success) { Fail-Step "uv sync failed" $result.Output "$RepoHelp/blob/main/docs/en/getting-started.md"; exit 1 }
    Complete-Step "MCP server ready ($($result.Elapsed))"
    $script:Profile | Set-Content -Path (Join-Path $SdpmHome ".profile") -Encoding ASCII
    (Get-Command uv).Source | Set-Content -Path (Join-Path $SdpmHome ".uv-path") -Encoding ASCII
    if ($script:Profile -ne "full") { return }

    Start-Step "Installing Web UI dependencies" "npm ci"
    $result = Run-WithSpinner -Exe "npm" -Arguments @("ci") -WorkDir (Join-Path $Checkout "web-ui")
    if (-not $result.Success) { Fail-Step "npm ci failed" $result.Output "$RepoHelp/tree/main/web-ui"; exit 1 }
    Complete-Step "Web UI dependencies installed ($($result.Elapsed))"

    Start-Step "Building Web UI" "NEXT_PUBLIC_MODE=local npm run build"
    $result = Run-WithSpinner -Exe "npm" -Arguments @("run", "build") -WorkDir (Join-Path $Checkout "web-ui") -Env @{ NEXT_PUBLIC_MODE="local" }
    if (-not $result.Success) { Fail-Step "Local Web UI build failed" $result.Output "$RepoHelp/tree/main/web-ui"; exit 1 }
    Complete-Step "Local Web UI built ($($result.Elapsed))"
}

function Setup-IconSet {
    param([string]$Name, [string]$Manifest, [string]$Script)
    if (Test-Path $Manifest) { Start-Step "$Name icons" "already available"; Complete-Step "$Name icons skipped"; return }
    Start-Step "Downloading $Name icons" "official icon source"
    $result = Run-WithSpinner -Exe "uv" -Arguments @("run", "--directory", (Join-Path $Checkout "sdpm"), "python", $Script)
    if ($result.Success) { Complete-Step "$Name icons downloaded ($($result.Elapsed))" }
    else { Fail-Step "$Name icon download failed; retry after installation" $result.Output $RepoHelp }
}

function Setup-Launcher {
    Start-Step "Installing sdpm command" (Join-Path $LauncherDir "sdpm.cmd")
    New-Item -ItemType Directory -Force -Path $LauncherDir | Out-Null
    $launcherPath = Join-Path $LauncherDir "sdpm.ps1"
    if ($script:EmbeddedLauncher) { $script:EmbeddedLauncher | Set-Content -Path $launcherPath -Encoding UTF8 }
    else {
        $source = Join-Path $ScriptDir "launcher.ps1"
        if (-not (Test-Path $source)) { Fail-Step "Launcher source is missing" "" $RepoHelp; exit 1 }
        Copy-Item $source $launcherPath -Force
    }
    '@powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0sdpm.ps1" %*' | Set-Content -Path (Join-Path $LauncherDir "sdpm.cmd") -Encoding ASCII
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($userPath -split ';') -notcontains $LauncherDir) { [Environment]::SetEnvironmentVariable("Path", (($userPath.TrimEnd(';') + ";" + $LauncherDir).Trim(';')), "User") }
    Refresh-Path
    Complete-Step "sdpm command installed"
}

function Setup-Shortcut {
    if ($SkipShortcut) { return }
    Start-Step "Creating desktop shortcut" "SDPM Web UI"
    $desktop = [Environment]::GetFolderPath("Desktop")
    if (-not $desktop) { Complete-Step "Desktop folder not found; shortcut skipped"; return }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $desktop "SDPM.lnk"))
    $shortcut.TargetPath = Join-Path $LauncherDir "sdpm.cmd"
    $shortcut.Arguments = "webui"
    $shortcut.WorkingDirectory = $LauncherDir
    $shortcut.Description = "Spec-Driven Presentation Maker"
    $shortcut.Save()
    Complete-Step "Desktop shortcut created"
}

function Choose-Profile {
    if ($script:Profile) { return }
    if ($script:NonInteractive) { $script:Profile = "full"; return }
    Write-Host ""
    Write-Host "  SDPM has two surfaces on one installation:"
    Write-Host "    - your own AI agent (Kiro CLI, Claude Code, Cursor, ...) through the MCP server"
    Write-Host "    - a browser Web UI (needs Node.js 20+; adds a few minutes of build time)"
    $script:Profile = if (Show-Confirm "Also install the browser Web UI?") { "full" } else { "mcp" }
}

function Invoke-Launcher {
    param([string[]]$LauncherArgs)
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $LauncherDir "sdpm.ps1") @LauncherArgs
}

function Register-Clients {
    Write-Host ""
    if ($script:RegisterMode -eq "no") { try { Invoke-Launcher @("mcp-config") } catch { }; return }
    if ($script:RegisterMode -eq "yes") { try { Invoke-Launcher @("register", "--yes") } catch { }; return }
    if ($script:NonInteractive) { try { Invoke-Launcher @("mcp-config") } catch { }; return }
    Write-Host "  Connect your MCP clients now? Each one is asked separately; nothing is written"
    Write-Host "  without your yes, and 'sdpm register' does the same later."
    try { Invoke-Launcher @("register") } catch { }
}

function Show-Completion {
    Write-Host "`n  SDPM is installed.`n" -ForegroundColor Green
    Write-Host "    Your agent:   ask it `"Make slides about ...`" - it finds SDPM through MCP."
    if ($script:Profile -eq "full") {
        Write-Host "    Browser:      sdpm webui"
        & kiro-cli whoami *> $null
        if ($LASTEXITCODE -ne 0) { Write-Host "                  (the Web UI uses Kiro CLI: run 'kiro-cli login' once first)" }
    } else {
        Write-Host "    Browser:      not installed - add it any time with 'sdpm update --with-webui'"
    }
    Write-Host "    Later:        sdpm            status      sdpm register   connect more clients"
    Write-Host "                  sdpm update     upgrade     sdpm uninstall  remove"
    Write-Host "`n    Checkout: $Checkout"
    Write-Host "    Open a new terminal so 'sdpm' is on PATH."
}

Show-Header -Title "SDPM Setup" -Version $InstallerVersion
Refresh-Path
if (-not $DepsOnly) { Choose-Profile }
$dependencies = @(Get-Dependencies)
$script:TotalSteps = if ($DepsOnly) { 0 } elseif ($script:Profile -eq "full") { 7 + $(if ($SkipShortcut) { 0 } else { 1 }) } else { 5 }
Install-MissingDependencies -Dependencies $dependencies
if ($DepsOnly) { Write-Host "`n  Dependency setup complete." -ForegroundColor Green; & uv --version; return }
Setup-Checkout
Setup-Packages
Setup-IconSet -Name "AWS Architecture" -Manifest (Join-Path $Checkout "sdpm\assets\aws\manifest.json") -Script (Join-Path $Checkout "sdpm\scripts\download_aws_icons.py")
Setup-IconSet -Name "Material Symbols" -Manifest (Join-Path $Checkout "sdpm\assets\material\manifest.json") -Script (Join-Path $Checkout "sdpm\scripts\download_material_icons.py")
Setup-Launcher
if ($script:Profile -eq "full") { Setup-Shortcut }
Register-Clients
Show-Completion
