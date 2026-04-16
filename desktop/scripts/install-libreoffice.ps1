# Install LibreOffice on Windows if not present.

$loPath = "C:\Program Files\LibreOffice"
$soffice = "$loPath\program\soffice.exe"
if (Test-Path $soffice) {
    $verOutput = & $soffice --version 2>&1 | Select-Object -First 1
    Write-Host "LibreOffice found: $verOutput"
    if ($verOutput -match '(\d+)\.(\d+)\.(\d+)') {
        $major = [int]$Matches[1]; $minor = [int]$Matches[2]; $patch = [int]$Matches[3]
        # Require 25.8.6+ (macOS SVG multi-slide export fix; applied cross-platform for consistency)
        if ($major -gt 25 -or ($major -eq 25 -and $minor -gt 8) -or ($major -eq 25 -and $minor -eq 8 -and $patch -ge 6)) {
            exit 0
        }
        Write-Host "LibreOffice $($Matches[0]) is too old. Requires 25.8.6+."
    }
}

Write-Host "LibreOffice is required for slide preview and PPTX generation."

if (Get-Command choco -ErrorAction SilentlyContinue) {
    Write-Host "Installing via Chocolatey..."
    choco install libreoffice-fresh -y
} elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Installing via winget..."
    winget install TheDocumentFoundation.LibreOffice
} else {
    Write-Host "Please install LibreOffice from https://www.libreoffice.org/download/"
    Start-Process "https://www.libreoffice.org/download/"
    exit 1
}
