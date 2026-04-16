#!/bin/bash
# Install LibreOffice if not present.
# Called by Tauri app on first launch or by user manually.

set -e

check_libreoffice() {
  local version=""
  if command -v libreoffice &>/dev/null; then
    version=$(libreoffice --version 2>/dev/null | head -1)
  elif [ -x "/Applications/LibreOffice.app/Contents/MacOS/soffice" ]; then
    version=$(/Applications/LibreOffice.app/Contents/MacOS/soffice --version 2>/dev/null | head -1)
  else
    return 1
  fi
  echo "LibreOffice found: $version"
  # Extract version (e.g. "LibreOffice 25.8.6.2 ..." -> "25.8.6")
  local ver=$(echo "$version" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  # Require 25.8.6+ (macOS SVG multi-slide export fix)
  if [ -z "$ver" ]; then return 1; fi
  local IFS=.
  read -r major minor patch <<< "$ver"
  if [ "$major" -lt 25 ] || \
     { [ "$major" -eq 25 ] && [ "$minor" -lt 8 ]; } || \
     { [ "$major" -eq 25 ] && [ "$minor" -eq 8 ] && [ "$patch" -lt 6 ]; }; then
    echo "LibreOffice $ver is too old. Requires 25.8.6+ for multi-slide SVG export."
    return 1
  fi
  return 0
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
