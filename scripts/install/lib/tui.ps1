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
