# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# SDPM installer for Windows. The generated dist/install.ps1 is the standalone
# irm | iex entry point.
[CmdletBinding()]
param(
    [switch]$DepsOnly,
    [switch]$NonInteractive,
    [switch]$SkipLibreOffice,
    [switch]$SkipShortcut
)
# __INSTALL_BODY_BELOW__

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$script:NonInteractive = $NonInteractive -or $env:SDPM_NON_INTERACTIVE -eq "1"
if ($env:SDPM_SKIP_LIBREOFFICE -eq "1") { $SkipLibreOffice = $true }
if ($env:SDPM_SKIP_SHORTCUT -eq "1") { $SkipShortcut = $true }
$InstallerVersion = "0.1.0"
$RepoUrl = "https://github.com/aws-samples/sample-spec-driven-presentation-maker.git"
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
    if (-not $DepsOnly) {
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
    Start-Step "Syncing local MCP dependencies" "servers/local"
    $result = Run-WithSpinner -Exe "uv" -Arguments @("sync", "--directory", (Join-Path $Checkout "servers\local"))
    if (-not $result.Success) { Fail-Step "uv sync failed" $result.Output "$RepoHelp/blob/main/docs/en/getting-started.md"; exit 1 }
    Complete-Step "MCP dependencies synced ($($result.Elapsed))"

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
    $shortcut.Arguments = "launch"
    $shortcut.WorkingDirectory = $LauncherDir
    $shortcut.Description = "Spec-Driven Presentation Maker"
    $shortcut.Save()
    Complete-Step "Desktop shortcut created"
}

function Show-Completion {
    Write-Host "`n  SDPM setup is complete.`n" -ForegroundColor Green
    Write-Host "    1. Authenticate once: kiro-cli login"
    Write-Host "    2. Launch the Web UI: sdpm launch"
    Write-Host "    3. Open http://localhost:3000 (the launcher opens it automatically)"
    Write-Host "`n    Checkout: $Checkout"
}

Show-Header -Title "SDPM Setup" -Version $InstallerVersion
Refresh-Path
$dependencies = @(Get-Dependencies)
$script:TotalSteps = if ($DepsOnly) { 0 } else { 7 + $(if ($SkipShortcut) { 0 } else { 1 }) }
Install-MissingDependencies -Dependencies $dependencies
if ($DepsOnly) { Write-Host "`n  Dependency setup complete." -ForegroundColor Green; & uv --version; return }
Setup-Checkout
Setup-Packages
Setup-IconSet -Name "AWS Architecture" -Manifest (Join-Path $Checkout "sdpm\assets\aws\manifest.json") -Script (Join-Path $Checkout "sdpm\scripts\download_aws_icons.py")
Setup-IconSet -Name "Material Symbols" -Manifest (Join-Path $Checkout "sdpm\assets\material\manifest.json") -Script (Join-Path $Checkout "sdpm\scripts\download_material_icons.py")
Setup-Launcher
Setup-Shortcut
& kiro-cli whoami *> $null
if ($LASTEXITCODE -eq 0) { Write-Host "    [OK] Kiro CLI is authenticated." -ForegroundColor Green }
else { Write-Host "    [!] Run 'kiro-cli login' before the first launch." -ForegroundColor Yellow }
Show-Completion
