#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# sdpm — the one launcher for a local SDPM installation (~/.sdpm).
# sdpm-bootstrap 1
#
# A bootstrap: it finds the checkout and uv, and hands every command to the checkout.
#   sdpm update   fetch, then the checkout's servers/local/checkout_update.py (it follows the
#                 latest release, or main with --channel main, and never moves backwards)
#   anything else servers/local/sdpm_command.py (status, webui, mcp, register, doctor, …)
# Everything that can change between versions lives in those two files, so this one stays
# as it is. launcher.ps1 is the same file for Windows, line for line.
set -uo pipefail

SDPM_HOME="${SDPM_HOME:-$HOME/.sdpm}"
CHECKOUT="$SDPM_HOME/checkout"
UV_PATH_FILE="$SDPM_HOME/.uv-path"
# This file, as installed (the copy `sdpm update` refreshes).
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

# Absolute path of uv, recorded at install time; re-resolved and re-recorded if stale.
resolve_uv() {
  local recorded="" found
  [[ -f "$UV_PATH_FILE" ]] && recorded=$(cat "$UV_PATH_FILE" 2>/dev/null || true)
  if [[ -n "$recorded" && -x "$recorded" ]]; then echo "$recorded"; return 0; fi
  found=$(command -v uv 2>/dev/null || true)
  [[ -z "$found" && -x "$HOME/.local/bin/uv" ]] && found="$HOME/.local/bin/uv"
  [[ -n "$found" ]] || { echo "uv not found. Re-run the installer (it installs uv)." >&2; return 1; }
  case "$found" in /*) ;; *) found="$(cd "$(dirname "$found")" && pwd)/$(basename "$found")" ;; esac
  mkdir -p "$SDPM_HOME" && echo "$found" > "$UV_PATH_FILE"
  echo "$found"
}

[[ -d "$CHECKOUT/.git" ]] || { echo "SDPM is not installed at $CHECKOUT. Re-run the installer." >&2; exit 1; }
uv=$(resolve_uv) || exit 1
# No project, a fresh environment (never a .venv or VIRTUAL_ENV), Python 3.11+.
py=("$uv" run --no-project --isolated --python ">=3.11" python)

if [[ "${1:-}" == "update" ]]; then
  shift
  git -C "$CHECKOUT" fetch --quiet --prune origin \
      '+refs/heads/main:refs/remotes/origin/main' '+refs/tags/*:refs/tags/*' \
    || { echo "sdpm update could not fetch from $(git -C "$CHECKOUT" remote get-url origin 2>/dev/null); nothing was changed." >&2; exit 1; }
  updater="$CHECKOUT/servers/local/checkout_update.py"
  if grep -q '^UPDATER_CONTRACT = ' "$updater" 2>/dev/null; then
    exec "${py[@]}" "$updater" --checkout "$CHECKOUT" --uv "$uv" update --launcher "$SELF" "$@"
  fi
  # Only a checkout reset by hand gets here: run origin/main's file from a temp dir.
  tmp=$(mktemp -d) || exit 1
  git -C "$CHECKOUT" --work-tree="$tmp" restore --source=refs/remotes/origin/main --worktree \
      -- servers/local/checkout_update.py || { rm -rf "$tmp"; exit 1; }
  "${py[@]}" "$tmp/servers/local/checkout_update.py" --checkout "$CHECKOUT" --uv "$uv" update --launcher "$SELF" "$@"
  rc=$?; rm -rf "$tmp"; exit "$rc"
fi

cmd="$CHECKOUT/servers/local/sdpm_command.py"
[[ -f "$cmd" ]] || { echo "This checkout predates the sdpm command; run: sdpm update" >&2; exit 1; }
exec "${py[@]}" "$cmd" --checkout "$CHECKOUT" --uv "$uv" --launcher "$SELF" "$@"
