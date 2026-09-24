# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# Shared installer TUI helpers (Windows PowerShell 5.1 compatible).

$script:TotalSteps = 0
$script:CurrentStep = 0

function Show-Header {
    param([string]$Title = "SDPM Setup", [string]$Version = "")
    if ($Host.Name -ne "ServerRemoteHost") { Clear-Host }
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
