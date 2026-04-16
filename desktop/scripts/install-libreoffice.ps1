# Install LibreOffice on Windows if not present.

$loPath = "C:\Program Files\LibreOffice"
if (Test-Path "$loPath\program\soffice.exe") {
    Write-Host "LibreOffice found: $loPath"
    exit 0
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
