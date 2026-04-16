#!/bin/bash
# Install LibreOffice if not present.
# Called by Tauri app on first launch or by user manually.

set -e

check_libreoffice() {
  if command -v libreoffice &>/dev/null; then
    echo "LibreOffice found: $(libreoffice --version 2>/dev/null | head -1)"
    return 0
  fi
  # macOS: check /Applications
  if [ -d "/Applications/LibreOffice.app" ]; then
    echo "LibreOffice found: /Applications/LibreOffice.app"
    return 0
  fi
  return 1
}

if check_libreoffice; then
  exit 0
fi

echo "LibreOffice is required for slide preview and PPTX generation."

OS="$(uname -s)"
case "$OS" in
  Darwin)
    if command -v brew &>/dev/null; then
      echo "Installing via Homebrew..."
      brew install --cask libreoffice
    else
      echo "Please install LibreOffice from https://www.libreoffice.org/download/"
      open "https://www.libreoffice.org/download/"
      exit 1
    fi
    ;;
  Linux)
    if command -v apt-get &>/dev/null; then
      echo "Installing via apt..."
      sudo apt-get update && sudo apt-get install -y libreoffice-impress
    elif command -v dnf &>/dev/null; then
      echo "Installing via dnf..."
      sudo dnf install -y libreoffice-impress
    else
      echo "Please install LibreOffice: https://www.libreoffice.org/download/"
      exit 1
    fi
    ;;
  *)
    echo "Please install LibreOffice: https://www.libreoffice.org/download/"
    exit 1
    ;;
esac

if check_libreoffice; then
  echo "Installation complete."
else
  echo "Installation failed. Please install manually."
  exit 1
fi
