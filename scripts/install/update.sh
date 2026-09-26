#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${SDPM_LAUNCHER_DIR:-$HOME/.local/bin}/sdpm"
if [[ -x "$LAUNCHER" ]]; then exec "$LAUNCHER" update; fi
exec bash "$SCRIPT_DIR/launcher.sh" update
