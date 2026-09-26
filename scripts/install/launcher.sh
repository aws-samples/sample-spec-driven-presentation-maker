#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# sdpm — the one launcher for a local SDPM installation (~/.sdpm).
#   sdpm webui      browser surface
#   sdpm mcp        MCP surface (for a terminal check; clients get the uv command directly)
#   sdpm register   wire the MCP server into the clients on this machine
# Anything that could drift between this file and launcher.ps1 (client detection,
# configuration rendering, registration commands) lives once in
# servers/local/client_config.py; both launchers only delegate to it.
set -uo pipefail

SDPM_HOME="${SDPM_HOME:-$HOME/.sdpm}"
CHECKOUT="$SDPM_HOME/checkout"
PROFILE_FILE="$SDPM_HOME/.profile"
UV_PATH_FILE="$SDPM_HOME/.uv-path"
# Kiro agent name chosen at install time (--agent-name); SDPM_AGENT_NAME overrides per call.
if [[ -z "${SDPM_AGENT_NAME:-}" && -f "$SDPM_HOME/.agent-name" ]]; then
  SDPM_AGENT_NAME=$(cat "$SDPM_HOME/.agent-name" 2>/dev/null || true)
fi
export SDPM_AGENT_NAME="${SDPM_AGENT_NAME:-sdpm}"
REPO_URL="https://github.com/aws-samples/sample-spec-driven-presentation-maker.git"
WEBUI_PORT="${SDPM_WEBUI_PORT:-3000}"

# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

require_checkout() {
  [[ -d "$CHECKOUT/.git" ]] || { echo "SDPM is not installed at $CHECKOUT. Re-run the installer." >&2; exit 1; }
}

profile() {
  if [[ -f "$PROFILE_FILE" ]]; then cat "$PROFILE_FILE"; else echo full; fi
}

webui_installed() { [[ "$(profile)" == "full" && -d "$CHECKOUT/web-ui/build" ]]; }

# Absolute path of uv, recorded by the installer; re-resolved and re-recorded if stale.
resolve_uv() {
  local recorded=""
  [[ -f "$UV_PATH_FILE" ]] && recorded=$(cat "$UV_PATH_FILE" 2>/dev/null || true)
  if [[ -n "$recorded" && -x "$recorded" ]]; then echo "$recorded"; return 0; fi
  local found
  found=$(command -v uv 2>/dev/null || true)
  [[ -z "$found" && -x "$HOME/.local/bin/uv" ]] && found="$HOME/.local/bin/uv"
  [[ -n "$found" ]] || { echo "uv not found. Re-run the installer (it installs uv)." >&2; exit 1; }
  case "$found" in /*) ;; *) found="$(cd "$(dirname "$found")" && pwd)/$(basename "$found")" ;; esac
  mkdir -p "$SDPM_HOME" && echo "$found" > "$UV_PATH_FILE"
  echo "$found"
}

# Run a Python entry point inside the local server's environment (no stdout of our own).
py() {
  local uv; uv=$(resolve_uv) || exit 1
  exec "$uv" run --directory "$CHECKOUT/servers/local" python "$@"
}

# client_config.py, told exactly which uv and checkout the clients must point at.
cfg() {
  local uv; uv=$(resolve_uv) || exit 1
  exec "$uv" run --directory "$CHECKOUT/servers/local" python client_config.py --uv "$uv" --checkout "$CHECKOUT" "$@"
}

cfg_call() {
  local uv; uv=$(resolve_uv) || return 1
  "$uv" run --directory "$CHECKOUT/servers/local" python client_config.py --uv "$uv" --checkout "$CHECKOUT" "$@"
}

# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------

open_url() {
  if command -v open >/dev/null 2>&1; then open "$1" >/dev/null 2>&1
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1
  else printf 'Open %s in your browser.\n' "$1"
  fi
}

port_is_open() {
  (exec 3<>"/dev/tcp/127.0.0.1/$WEBUI_PORT") >/dev/null 2>&1
}

wait_and_open_browser() {
  (
    local i
    for ((i=0; i<240; i++)); do
      if port_is_open; then open_url "http://localhost:$WEBUI_PORT"; exit 0; fi
      sleep 0.5
    done
    echo "SDPM did not become ready on port $WEBUI_PORT within 120 seconds." >&2
  ) &
}

webui() {
  require_checkout
  if ! webui_installed; then
    echo "The browser Web UI is not installed in this profile ($(profile))." >&2
    echo "Add it with:  sdpm update --with-webui   (needs Node.js 20+)" >&2
    exit 1
  fi
  if port_is_open; then
    echo "Port $WEBUI_PORT is already in use; opening the existing service."
    open_url "http://localhost:$WEBUI_PORT"
    return 0
  fi
  wait_and_open_browser
  cd "$CHECKOUT/web-ui" || exit 1
  NEXT_PUBLIC_MODE=local npm run start -- --hostname 127.0.0.1 --port "$WEBUI_PORT"
}

mcp() {
  require_checkout
  # Foreground stdio server for a terminal check. Nothing else may touch stdout here.
  py server.py
}

# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

report_failure() {
  echo "SDPM $1 failed while $2 (exit $3)." >&2
  echo "Review the output above and repair the checkout at $CHECKOUT, then rerun 'sdpm $1'." >&2
}

step() {
  local what="$1" op="$2" status; shift 2
  echo "> $what..."
  "$@"; status=$?
  [[ "$status" -eq 0 ]] || { report_failure "$op" "$what" "$status"; return "$status"; }
}

build_mcp() {
  local uv; uv=$(resolve_uv) || return 1
  step "Syncing the MCP server environment" update "$uv" sync --directory "$CHECKOUT/servers/local" || return $?
  step "Installing icon catalogs" update "$uv" run --directory "$CHECKOUT/servers/local" \
    python -m sdpm.knowledge.assets.download --sources aws,material || return $?
}

build_webui() {
  step "Installing Web UI dependencies" update bash -c "cd '$CHECKOUT/web-ui' && npm ci" || return $?
  step "Building the Web UI (Local mode)" update bash -c "cd '$CHECKOUT/web-ui' && NEXT_PUBLIC_MODE=local npm run build" || return $?
}

update() {
  require_checkout
  local with_webui=0
  for arg in "$@"; do [[ "$arg" == "--with-webui" ]] && with_webui=1; done
  echo "> Fetching main from $REPO_URL"
  step "Fetching main" update git -C "$CHECKOUT" fetch --tags --prune origin main || return $?
  step "Checking out main" update git -C "$CHECKOUT" checkout -q main || return $?
  step "Fast-forwarding main" update git -C "$CHECKOUT" pull -q --ff-only origin main || return $?
  build_mcp || return $?
  if [[ "$with_webui" -eq 1 ]]; then
    command -v npm >/dev/null 2>&1 || { echo "Node.js 20+ is required for the Web UI: https://nodejs.org/" >&2; return 1; }
    echo full > "$PROFILE_FILE"
  fi
  if [[ "$(profile)" == "full" ]]; then build_webui || return $?; fi
  echo "Update complete."
  echo "  sdpm webui     open the browser Web UI" ; [[ "$(profile)" == "full" ]] || echo "  (not installed — sdpm update --with-webui)"
  echo "  sdpm register  connect your MCP clients"
}

uninstall() {
  require_checkout
  echo "This removes $SDPM_HOME, the sdpm command and desktop shortcuts."
  read -r -p "Continue? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted."; return 0; }
  cfg_call unregister || true
  local launcher_dir; launcher_dir="${SDPM_LAUNCHER_DIR:-$HOME/.local/bin}"
  rm -f "$launcher_dir/sdpm" "$HOME/Desktop/SDPM.command" "$HOME/.local/share/applications/sdpm.desktop"
  rm -rf "$SDPM_HOME"
  echo "SDPM removed."
}

version() {
  require_checkout
  local ref commit
  ref=$(git -C "$CHECKOUT" describe --tags --always 2>/dev/null || echo main)
  commit=$(git -C "$CHECKOUT" rev-parse --short HEAD)
  echo "$ref ($commit)"
}

status() {
  require_checkout
  echo "SDPM $(version)"
  echo "  checkout   $CHECKOUT"
  echo "  profile    $(profile)"
  if webui_installed; then echo "  webui      installed        → sdpm webui"
  else                     echo "  webui      not installed    → sdpm update --with-webui"; fi
  echo "  mcp        installed        → sdpm register  (connect your MCP clients)"
  echo ""
  cfg_call status 2>/dev/null || true
}

help_text() {
  cat <<'HELP'
Usage: sdpm [COMMAND]

Surfaces
  webui                 Start the browser Web UI and open it
  mcp                   Run the MCP server on stdio (terminal check)

MCP clients
  register [CLIENT..]   Register the server with detected (or named) clients
  unregister [CLIENT..] Remove it again
  mcp-config [CLIENT..] Print the configuration with this machine's paths (--json, --all)

Maintenance
  update [--with-webui] Pull main, sync dependencies, rebuild what is installed
  doctor                Check the local environment
  uninstall             Remove SDPM from this machine
  version | path | help

No command: show status.
HELP
}

case "${1:-}" in
  "") status ;;
  webui|launch) webui ;;
  mcp) mcp ;;
  register) shift; require_checkout; cfg register "$@" ;;
  unregister) shift; require_checkout; cfg unregister "$@" ;;
  mcp-config) shift; require_checkout; cfg print "$@" ;;
  update) shift; update "$@" ;;
  doctor) require_checkout; (cd "$CHECKOUT" && make doctor) ;;
  uninstall) uninstall ;;
  version|--version|-v) version ;;
  path) echo "$CHECKOUT" ;;
  help|--help|-h) help_text ;;
  *) echo "Unknown command: $1" >&2; help_text >&2; exit 2 ;;
esac
