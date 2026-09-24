#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
set -uo pipefail

SDPM_HOME="${SDPM_HOME:-$HOME/.sdpm}"
CHECKOUT="$SDPM_HOME/checkout"
MARKER_FILE="$SDPM_HOME/.update-available"
LAST_CHECK_FILE="$SDPM_HOME/.last-update-check"
CHECK_INTERVAL_SECONDS=$((24 * 60 * 60))
REPO_URL="https://github.com/aws-samples/sample-spec-driven-presentation-maker.git"

open_url() {
  if command -v open >/dev/null 2>&1; then open "$1" >/dev/null 2>&1
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1
  else printf 'Open %s in your browser.\n' "$1"
  fi
}

port_is_open() {
  (exec 3<>/dev/tcp/127.0.0.1/3000) >/dev/null 2>&1
}

wait_and_open_browser() {
  (
    local i
    for ((i=0; i<240; i++)); do
      if port_is_open; then open_url "http://localhost:3000"; exit 0; fi
      sleep 0.5
    done
    echo "SDPM did not become ready on port 3000 within 120 seconds." >&2
  ) &
}

current_revision() { git -C "$CHECKOUT" rev-parse HEAD 2>/dev/null || true; }
remote_revision() { git -C "$CHECKOUT" ls-remote origin refs/heads/main 2>/dev/null | awk 'NR==1 {print $1}'; }

check_update_async() {
  [[ -d "$CHECKOUT/.git" ]] || return 0
  local now last=0
  now=$(date +%s)
  [[ -f "$LAST_CHECK_FILE" ]] && last=$(cat "$LAST_CHECK_FILE" 2>/dev/null || echo 0)
  [[ $((now - last)) -lt "$CHECK_INTERVAL_SECONDS" ]] && return 0
  (
    local latest current
    latest=$(remote_revision); current=$(current_revision)
    date +%s > "$LAST_CHECK_FILE" 2>/dev/null || true
    if [[ -n "$latest" && "$latest" != "$current" ]]; then
      echo "$latest" > "$MARKER_FILE"
    else
      rm -f "$MARKER_FILE"
    fi
  ) >/dev/null 2>&1 &
}

show_update_banner() {
  [[ -f "$MARKER_FILE" ]] || return 0
  echo ""
  echo "---------------------------------------------------"
  echo "  A newer SDPM checkout is available."
  echo "  Run 'sdpm update' to install it."
  echo "---------------------------------------------------"
  echo ""
}

report_update_failure() {
  local step="$1"
  local status="$2"
  echo "SDPM update failed while $step (exit $status)." >&2
  echo "Review the command output above and repair the checkout at $CHECKOUT, then rerun 'sdpm update'." >&2
}

run_update_step() {
  local step="$1"
  local status
  shift
  "$@"
  status=$?
  if [[ "$status" -ne 0 ]]; then
    report_update_failure "$step" "$status"
    return "$status"
  fi
  return 0
}

build_checkout() {
  local status
  echo "> Syncing local MCP dependencies..."
  run_update_step "syncing local MCP dependencies" uv sync --directory "$CHECKOUT/servers/local" || return $?
  echo "> Installing Web UI dependencies..."
  (cd "$CHECKOUT/web-ui" && npm ci)
  status=$?
  if [[ "$status" -ne 0 ]]; then
    report_update_failure "installing Web UI dependencies" "$status"
    return "$status"
  fi
  echo "> Building Web UI in Local mode..."
  (cd "$CHECKOUT/web-ui" && NEXT_PUBLIC_MODE=local npm run build)
  status=$?
  if [[ "$status" -ne 0 ]]; then
    report_update_failure "building the Local Web UI" "$status"
    return "$status"
  fi
  return 0
}

launch() {
  [[ -d "$CHECKOUT/.git" ]] || { echo "SDPM is not installed at $CHECKOUT. Re-run the installer." >&2; exit 1; }
  show_update_banner
  if port_is_open; then
    echo "Port 3000 is already in use; opening the existing service."
    open_url "http://localhost:3000"
    return 0
  fi
  [[ -d "$CHECKOUT/web-ui/build" ]] || { echo "Web UI build missing. Run 'sdpm update'." >&2; exit 1; }
  check_update_async
  wait_and_open_browser
  cd "$CHECKOUT/web-ui" || exit 1
  NEXT_PUBLIC_MODE=local npm run start -- --hostname 127.0.0.1 --port 3000
}

update() {
  [[ -d "$CHECKOUT/.git" ]] || { echo "Not a git checkout: $CHECKOUT" >&2; exit 1; }
  echo "> Fetching main from $REPO_URL"
  run_update_step "fetching main" git -C "$CHECKOUT" fetch --tags --prune origin main || return $?
  run_update_step "checking out main" git -C "$CHECKOUT" checkout main || return $?
  run_update_step "fast-forwarding main" git -C "$CHECKOUT" pull --ff-only origin main || return $?
  build_checkout || return $?
  rm -f "$MARKER_FILE"
  echo "Update complete. Run 'sdpm launch'."
}

check_update() {
  [[ -d "$CHECKOUT/.git" ]] || { echo "Not a git checkout: $CHECKOUT" >&2; exit 1; }
  local latest current
  latest=$(remote_revision); current=$(current_revision)
  date +%s > "$LAST_CHECK_FILE"
  [[ -n "$latest" ]] || { echo "Could not query $REPO_URL" >&2; exit 1; }
  if [[ "$latest" == "$current" ]]; then
    echo "SDPM is up to date."; rm -f "$MARKER_FILE"
  else
    echo "A newer SDPM checkout is available. Run 'sdpm update'."
    echo "$latest" > "$MARKER_FILE"
  fi
}

version() {
  [[ -d "$CHECKOUT/.git" ]] || { echo "Not a git checkout: $CHECKOUT" >&2; exit 1; }
  local ref commit
  ref=$(git -C "$CHECKOUT" describe --tags --always 2>/dev/null || echo main)
  commit=$(git -C "$CHECKOUT" rev-parse --short HEAD)
  echo "SDPM version: $ref ($commit)"
}

help_text() {
  cat <<'HELP'
Usage: sdpm [COMMAND]

Commands:
  launch        Start the built Local Web UI (default) and open a browser
  update        Pull main, sync dependencies, and rebuild the Local Web UI
  check-update  Check whether the installed checkout is behind main
  doctor        Run the repository environment doctor
  version       Show the installed revision
  path          Print the checkout path
  help          Show this help
HELP
}

case "${1:-launch}" in
  launch|"") launch ;;
  update) update ;;
  check-update) check_update ;;
  doctor) (cd "$CHECKOUT" && make doctor) ;;
  version|--version|-v) version ;;
  path) echo "$CHECKOUT" ;;
  help|--help|-h) help_text ;;
  *) echo "Unknown command: $1" >&2; help_text >&2; exit 2 ;;
esac
