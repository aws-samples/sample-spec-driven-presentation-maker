# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# SDPM installer for Windows. The generated dist/install.ps1 is the standalone
# irm | iex entry point.
[CmdletBinding()]
param(
    [switch]$Full,
    [switch]$McpOnly,
    [switch]$Register,
    [string]$AgentName = "",
    [string]$Channel = "",
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

# Two-row checklist matching the client picker: MCP server always on, Web UI toggles.
# Returns $true when the Web UI is selected. Falls back to Show-Confirm without a console.
function Show-SurfacePicker {
    if ($script:NonInteractive) { return $true }
    if ([Console]::IsOutputRedirected -or [Console]::IsInputRedirected) {
        return (Show-Confirm "Also install the browser Web UI?")
    }
    $webui = $true
    $top = [Console]::CursorTop
    $render = {
        [Console]::SetCursorPosition(0, $top)
        Write-Host "  What to install   " -NoNewline; Write-Host "space toggle - enter confirm" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "        [x] MCP server        for your AI agent - always installed" -ForegroundColor DarkGray
        Write-Host "  " -NoNewline; Write-Host ">" -ForegroundColor Cyan -NoNewline
        if ($webui) { Write-Host " [x]" -ForegroundColor Green -NoNewline } else { Write-Host " [ ]" -NoNewline }
        Write-Host " Browser Web UI    " -NoNewline; Write-Host "needs Node.js 20+; a few minutes of build   " -ForegroundColor DarkGray
    }
    [Console]::CursorVisible = $false
    try {
        & $render
        while ($true) {
            $key = [Console]::ReadKey($true)
            if ($key.Key -eq "Spacebar") { $webui = -not $webui }
            elseif ($key.Key -eq "Enter") { break }
            & $render
        }
    } finally { [Console]::CursorVisible = $true }
    [Console]::SetCursorPosition(0, $top)
    for ($i = 0; $i -lt 4; $i++) { Write-Host (" " * ([Console]::WindowWidth - 1)) }
    [Console]::SetCursorPosition(0, $top)
    if ($webui) { Write-Host "  What to install: MCP server, Browser Web UI" } else { Write-Host "  What to install: MCP server" }
    Write-Host ""
    return $webui
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

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
# The one rule for asking anything: a console that is neither redirected in nor out. Without
# it the installer runs exactly as with -NonInteractive and never waits for input.
$script:NonInteractive = $NonInteractive -or $env:SDPM_NON_INTERACTIVE -eq "1" -or
    -not [Environment]::UserInteractive -or [Console]::IsInputRedirected -or [Console]::IsOutputRedirected
if ($env:SDPM_SKIP_LIBREOFFICE -eq "1") { $SkipLibreOffice = $true }
if ($env:SDPM_SKIP_SHORTCUT -eq "1") { $SkipShortcut = $true }
# Profile: full | mcp. Asked interactively when neither switch nor SDPM_PROFILE is given.
$script:Profile = if ($Full) { "full" } elseif ($McpOnly) { "mcp" } elseif ($env:SDPM_PROFILE) { $env:SDPM_PROFILE } else { "" }
if ($script:Profile -and $script:Profile -notin @("full", "mcp")) { Write-Host "SDPM_PROFILE must be full or mcp, not '$($script:Profile)'." -ForegroundColor Red; exit 2 }
# The Kiro agent name and the channel go to the setup only when given; it keeps what the
# install has otherwise.
if (-not $AgentName -and $env:SDPM_AGENT_NAME) { $AgentName = $env:SDPM_AGENT_NAME }
if (-not $Channel -and $env:SDPM_CHANNEL) { $Channel = $env:SDPM_CHANNEL }
if ($Channel -and $Channel -notin @("release", "main")) { Write-Host "-Channel must be release or main, not '$Channel'." -ForegroundColor Red; exit 2 }
# Registration: default | yes | no
$script:RegisterMode = if ($Register) { "yes" } elseif ($NoRegister) { "no" } elseif ($env:SDPM_REGISTER -in @("yes", "no")) { $env:SDPM_REGISTER } else { "default" }
$InstallerVersion = "0.1.0"
$RepoUrl = if ($env:SDPM_REPO_URL) { $env:SDPM_REPO_URL } else { "https://github.com/aws-samples/sample-spec-driven-presentation-maker.git" }
$RepoHelp = "https://github.com/aws-samples/sample-spec-driven-presentation-maker"
$SdpmHome = if ($env:SDPM_HOME) { $env:SDPM_HOME } else { Join-Path $env:USERPROFILE ".sdpm" }
$Checkout = Join-Path $SdpmHome "checkout"
$LauncherDir = if ($env:SDPM_LAUNCHER_DIR) { $env:SDPM_LAUNCHER_DIR } else { Join-Path $env:USERPROFILE "bin" }
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }

# Over an existing install, keep its profile unless told otherwise. An old sdpm command can
# write .profile=full after state.json said mcp (`sdpm update --with-webui`); full wins.
function Get-RecordedProfile {
    $legacyFile = Join-Path $SdpmHome ".profile"
    $legacy = if (Test-Path $legacyFile) { (Get-Content $legacyFile -Raw).Trim() } else { "" }
    if ($legacy -eq "full") { return "full" }
    $stateFile = Join-Path $SdpmHome "state.json"
    if (Test-Path $stateFile) {
        try { $recorded = (Get-Content $stateFile -Raw | ConvertFrom-Json).profile } catch { $recorded = "" }
        if ($recorded -in @("full", "mcp")) { return $recorded }
    }
    if ($legacy -in @("full", "mcp")) { return $legacy }
    return ""
}
if (-not $script:Profile) { $script:Profile = Get-RecordedProfile }
$script:Existing = $false   # this run is over an install that exists (its manifest counts as an update)

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
        if ($env:SDPM_SKIP_KIRO_CLI -ne "1") { $items += @{ Name="kiro-cli"; Found=(Has-Command "kiro-cli"); Version=$(if (Has-Command "kiro-cli") { "installed" } else { "" }); Reason="Local ACP agent"; Id=""; Url="https://kiro.dev/docs/cli/setup/" } }
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
    # winget downloads from the package's own host (poppler: GitHub Releases), where a timeout
    # or a 5xx usually passes on the next try. Retry only those (HTTP 500-511 as 0x801901F4-FF,
    # WinINet timeout / cannot connect / aborted / reset); anything else fails at once.
    $delays = @(5, 10)
    for ($attempt = 0; ; $attempt++) {
        $result = Run-WithSpinner -Exe "winget" -Arguments @("install", "--exact", "--id", $Dependency.Id, "--silent", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity")
        Refresh-Path
        $installed = $result.Success -and (Test-DependencyAvailable -Name $Dependency.Name)
        $transient = $result.Output -match '0x(801901f[4-9a-f]|80072ee2|80072ef[d-f])\b'
        if ($installed -or -not $transient -or $attempt -ge $delays.Count) { break }
        Write-Host "        Download failed ($($Matches[0])); retrying in $($delays[$attempt]) s" -ForegroundColor DarkGray
        Start-Sleep -Seconds $delays[$attempt]
    }
    if (-not $installed) {
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
        $script:Existing = $true
        # The sdpm command's fetch: origin's main and tags, local tags mirroring origin's.
        $result = Run-WithSpinner -Exe "git" -Arguments @("-C", $Checkout, "fetch", "--quiet", "--prune", "origin", "+refs/heads/main:refs/remotes/origin/main", "+refs/tags/*:refs/tags/*")
        if (-not $result.Success) { Fail-Step "SDPM fetch failed" $result.Output $RepoHelp; exit 1 }
        Complete-Step "SDPM fetched ($($result.Elapsed))"
    } elseif (Test-Path $Checkout) {
        Fail-Step "$Checkout exists but is not a git checkout" "Move it aside and retry." $RepoHelp; exit 1
    } else {
        $result = Run-WithSpinner -Exe "git" -Arguments @("clone", "--branch", "main", "--single-branch", $RepoUrl, $Checkout)
        if (-not $result.Success) { Fail-Step "SDPM clone failed" $result.Output $RepoHelp; exit 1 }
        Complete-Step "SDPM checkout created ($($result.Elapsed))"
    }
}

# main's checkout_update.py (this installer is main's code too), run before anything is
# checked out: it picks the latest release (or main), moves the checkout there, then hands
# over to that version's own setup: Python environment, Web UI, icons, the sdpm command,
# clients, state.json. Start-Process: the child gets this console as it is, so uv, npm and
# the client picker show (and read keys) unwrapped.
function Invoke-Setup {
    $uv = (Get-Command uv).Source
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("sdpm-install-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        & git -C $Checkout "--work-tree=$tmp" restore --source=refs/remotes/origin/main --worktree -- servers/local/checkout_update.py | Out-Null
        if ($LASTEXITCODE -ne 0) { return 1 }
        $setupArgs = @("run", "--no-project", "--isolated", "--python", ">=3.11", "python",
            (Join-Path $tmp "servers\local\checkout_update.py"), "--checkout", $Checkout, "--uv", $uv, "install",
            "--launcher", (Join-Path $LauncherDir "sdpm.ps1"), "--register", $script:RegisterMode, "--profile", $script:Profile)
        if (-not $script:Existing) { $setupArgs += "--new-checkout" }
        if ($AgentName) { $setupArgs += @("--agent-name", $AgentName) }
        if ($Channel) { $setupArgs += @("--channel", $Channel) }
        if ($script:NonInteractive) { $setupArgs += "--non-interactive" }
        $quoted = ($setupArgs | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join " "
        Write-Host ""
        $proc = Start-Process -FilePath $uv -ArgumentList $quoted -NoNewWindow -Wait -PassThru
        return $proc.ExitCode
    } finally { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
}

# The command a new terminal finds: sdpm.cmd next to the sdpm.ps1 the setup wrote, and that
# directory on the user's PATH.
function Setup-CommandShim {
    New-Item -ItemType Directory -Force -Path $LauncherDir | Out-Null
    '@powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0sdpm.ps1" %*' | Set-Content -Path (Join-Path $LauncherDir "sdpm.cmd") -Encoding ASCII
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($userPath -split ';') -notcontains $LauncherDir) { [Environment]::SetEnvironmentVariable("Path", (($userPath.TrimEnd(';') + ";" + $LauncherDir).Trim(';')), "User") }
    Refresh-Path
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
    $script:Profile = if (Show-SurfacePicker) { "full" } else { "mcp" }
}

# The client table above is the part that matters; nothing here repeats it.
function Show-Completion {
    param([int]$SetupStatus)
    $installedProfile = Get-RecordedProfile
    if (-not $installedProfile) { $installedProfile = $script:Profile }
    Write-Host ""
    Write-Host "  SDPM is installed" -ForegroundColor Green -NoNewline; Write-Host " in $Checkout`n"
    if ($installedProfile -eq "full") {
        Write-Host "    Browser:   sdpm webui"
        & kiro-cli whoami *> $null
        if ($LASTEXITCODE -ne 0) { Write-Host "               (the Web UI uses Kiro CLI - run 'kiro-cli login' once first)" }
    } else {
        Write-Host "    Browser:   not installed - sdpm update --with-webui"
    }
    Write-Host "    Agents:    ask for slides in a registered client (table above)"
    Write-Host "    Later:     sdpm  |  sdpm register  |  sdpm update  |  sdpm uninstall"
    Write-Host "    Open a new terminal so 'sdpm' is on PATH."
    if ($SetupStatus -eq 4) {
        Write-Host "    Some steps did not finish (see above). Fix client registrations with 'sdpm register <client>'." -ForegroundColor Yellow
        exit 1
    }
}

Show-Header -Title "SDPM Setup" -Version $InstallerVersion
Refresh-Path
if (-not $DepsOnly) { Choose-Profile }
$dependencies = @(Get-Dependencies)
$script:TotalSteps = if ($DepsOnly) { 0 } elseif ($script:Profile -eq "full" -and -not $SkipShortcut) { 2 } else { 1 }
Install-MissingDependencies -Dependencies $dependencies
if ($DepsOnly) { Write-Host "`n  Dependency setup complete." -ForegroundColor Green; & uv --version; return }
Setup-Checkout
$setupStatus = Invoke-Setup
if ($setupStatus -ne 0 -and $setupStatus -ne 4) {
    Write-Host ""
    Fail-Step "SDPM setup failed (see above)" "" "$RepoHelp/blob/main/docs/en/getting-started.md#sdpm-update-stops"
    exit $setupStatus
}
Setup-CommandShim
if ($script:Profile -eq "full") { Setup-Shortcut }
Show-Completion -SetupStatus $setupStatus
