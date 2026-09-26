#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
set -uo pipefail
SDPM_HOME="${SDPM_HOME:-$HOME/.sdpm}"
LAUNCHER_DIR="${SDPM_LAUNCHER_DIR:-$HOME/.local/bin}"
NON_INTERACTIVE="${SDPM_NON_INTERACTIVE:-0}"
[[ "${1:-}" == "--non-interactive" ]] && NON_INTERACTIVE=1
if [[ "$NON_INTERACTIVE" != "1" ]]; then
  printf 'Remove %s, %s/sdpm, and the SDPM desktop shortcut? [y/N] ' "$SDPM_HOME" "$LAUNCHER_DIR"
  read -r reply
  case "${reply:-n}" in [Yy]*) ;; *) echo "Cancelled."; exit 0 ;; esac
fi
rm -rf "$SDPM_HOME"
rm -f "$LAUNCHER_DIR/sdpm" "$HOME/Desktop/SDPM.command" "$HOME/.local/share/applications/sdpm.desktop"
echo "SDPM was removed. Shared dependencies (git, uv, Node.js, Kiro CLI, LibreOffice, poppler) were kept."
