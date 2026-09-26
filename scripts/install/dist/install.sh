#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2016,SC2059
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# shellcheck disable=SC2059
# Shared installer TUI helpers. Compatible with the macOS bash 3.2 default.

if [[ -t 1 ]]; then
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'
  C_YELLOW=$'\033[33m'; C_DIM=$'\033[2m'; C_RESET=$'\033[0m'
else
  C_CYAN=''; C_GREEN=''; C_RED=''; C_YELLOW=''; C_DIM=''; C_RESET=''
fi

TOTAL_STEPS=${TOTAL_STEPS:-0}
CURRENT_STEP=${CURRENT_STEP:-0}
LAST_LOG=${LAST_LOG:-}
LAST_ELAPSED=${LAST_ELAPSED:-}

show_header() {
  local title="$1" version="${2:-}"
  if [[ -t 1 ]]; then clear 2>/dev/null || true; fi
  echo ""
  printf "  ${C_CYAN}╭───────────────────────────────────────────╮${C_RESET}\n"
  printf "  ${C_CYAN}│  %-28s v%-8s │${C_RESET}\n" "$title" "$version"
  printf "  ${C_CYAN}╰───────────────────────────────────────────╯${C_RESET}\n\n"
}

show_check() {
  local name="$1" version="$2" found="$3"
  if [[ "$found" == "1" ]]; then
    printf "    ${C_GREEN}✓${C_RESET} %s ${C_DIM}%s${C_RESET}\n" "$name" "$version"
  else
    printf "    ${C_RED}✗${C_RESET} %s ${C_DIM}not installed${C_RESET}\n" "$name"
  fi
}

show_progress() {
  local filled=0 i bar=""
  if [[ "$TOTAL_STEPS" -gt 0 ]]; then
    filled=$((CURRENT_STEP * 36 / TOTAL_STEPS))
  fi
  for ((i=0; i<filled; i++)); do bar="${bar}━"; done
  for ((i=filled; i<36; i++)); do bar="${bar}─"; done
  printf "  ${C_DIM}%s${C_RESET} %d/%d\n" "$bar" "$CURRENT_STEP" "$TOTAL_STEPS"
}

start_step() {
  local message="$1" detail="${2:-}"
  CURRENT_STEP=$((CURRENT_STEP + 1))
  echo ""
  show_progress
  printf "    ${C_CYAN}●${C_RESET} %s ${C_DIM}[%d/%d]${C_RESET}\n" "$message" "$CURRENT_STEP" "$TOTAL_STEPS"
  [[ -n "$detail" ]] && printf "      ${C_DIM}%s${C_RESET}\n" "$detail"
}

complete_step() { printf "    ${C_GREEN}✓${C_RESET} %s\n" "$1"; }

fail_step() {
  local message="$1" log="${2:-}" help_url="${3:-}"
  printf "    ${C_RED}✗${C_RESET} %s\n" "$message"
  if [[ -n "$log" ]]; then
    printf "    ${C_DIM}┌ Last log lines ───────────────────────────${C_RESET}\n"
    echo "$log" | tail -n 10 | while IFS= read -r line; do
      printf "    ${C_DIM}│ %s${C_RESET}\n" "$line"
    done
    printf "    ${C_DIM}└───────────────────────────────────────────${C_RESET}\n"
  fi
  if [[ -n "$help_url" ]]; then
    printf "    ${C_YELLOW}Recovery: %s${C_RESET}\n" "$help_url"
  fi
}

show_confirm() {
  local prompt="$1" reply
  if [[ "${NON_INTERACTIVE:-0}" == "1" ]]; then return 0; fi
  # Under `curl … | bash` stdin is the script itself; prompts must come from the terminal.
  if [[ ! -r /dev/tty ]]; then
    echo "" >&2
    echo "No terminal available for prompts. Re-run with --non-interactive (add --mcp-only/--full" >&2
    echo "and --register/--no-register to choose instead of accepting the defaults)." >&2
    exit 2
  fi
  printf "\n  %s " "$prompt"
  read -r reply </dev/tty
  case "${reply:-y}" in [Yy]*|"") return 0 ;; *) return 1 ;; esac
}

has_command() { command -v "$1" >/dev/null 2>&1; }

run_with_spinner() {
  local command="$1" workdir="${2:-}" log_file start pid rc elapsed
  log_file="$(mktemp)"
  start=$(date +%s)
  if [[ -n "$workdir" ]]; then
    (cd "$workdir" && eval "$command") >"$log_file" 2>&1 &
  else
    eval "$command" >"$log_file" 2>&1 &
  fi
  pid=$!
  if [[ -t 1 ]]; then
    local frames=('|' '/' '-' '+') i=0
    while kill -0 "$pid" 2>/dev/null; do
      elapsed=$(( $(date +%s) - start ))
      printf "\r      ${C_DIM}%s %02d:%02d${C_RESET}" "${frames[$((i % 4))]}" $((elapsed / 60)) $((elapsed % 60))
      i=$((i + 1)); sleep 0.1
    done
    printf "\r                          \r"
  fi
  wait "$pid"; rc=$?
  elapsed=$(( $(date +%s) - start ))
  LAST_ELAPSED=$(printf "%02d:%02d" $((elapsed / 60)) $((elapsed % 60)))
  LAST_LOG="$(cat "$log_file")"
  rm -f "$log_file"
  return "$rc"
}

SDPM_LAUNCHER_CONTENT=''
IFS= read -r -d '' SDPM_LAUNCHER_CONTENT <<'__SDPM_LAUNCHER__' || true
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
__SDPM_LAUNCHER__
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# shellcheck disable=SC1091,SC2016,SC2059
# SDPM installer for macOS and Linux. The generated dist/install.sh is the
# standalone curl | bash entry point.
set -uo pipefail

INSTALLER_VERSION="0.1.0"
REPO_URL="${SDPM_REPO_URL:-https://github.com/aws-samples/sample-spec-driven-presentation-maker.git}"
REPO_HELP="https://github.com/aws-samples/sample-spec-driven-presentation-maker"
SDPM_HOME="${SDPM_HOME:-$HOME/.sdpm}"
CHECKOUT="$SDPM_HOME/checkout"
LAUNCHER_DIR="${SDPM_LAUNCHER_DIR:-$HOME/.local/bin}"
DEPS_ONLY=0
PROFILE="${SDPM_PROFILE:-}"          # full | mcp ; asked interactively when empty
REGISTER="${SDPM_REGISTER:-ask}"     # ask | yes | no
export SDPM_AGENT_NAME="${SDPM_AGENT_NAME:-sdpm}"   # name of the Kiro CLI agent
NON_INTERACTIVE="${SDPM_NON_INTERACTIVE:-0}"
SKIP_LIBREOFFICE="${SDPM_SKIP_LIBREOFFICE:-0}"
SKIP_SHORTCUT="${SDPM_SKIP_SHORTCUT:-0}"
export NON_INTERACTIVE

usage() {
  cat <<'HELP'
Usage: install.sh [OPTIONS]

Options:
  --full               Install the MCP server and the browser Web UI (needs Node.js)
  --mcp-only           Install the MCP server only (no Node.js, no Web UI)
  --register           Register the MCP server with every detected client without asking
  --agent-name NAME    Name of the Kiro CLI agent (default: sdpm)
  --no-register        Skip client registration (print the configuration instead)
  --deps-only          Install git, uv, LibreOffice, and poppler only
  --non-interactive    Accept dependency installation prompts; default profile: full
  --skip-libreoffice   Do not check or install LibreOffice
  --skip-shortcut      Do not create a desktop shortcut
  -h, --help           Show this help

Environment:
  SDPM_HOME                 Installation root (default: ~/.sdpm)
  SDPM_LAUNCHER_DIR         Launcher directory (default: ~/.local/bin)
  SDPM_PROFILE=full|mcp     Same as --full / --mcp-only
  SDPM_REPO_URL             Clone source (default: the GitHub repository; CI/testing)
  SDPM_REGISTER=yes|no      Same as --register / --no-register
  SDPM_AGENT_NAME           Same as --agent-name
  SDPM_NON_INTERACTIVE=1    Same as --non-interactive
  SDPM_SKIP_LIBREOFFICE=1   Same as --skip-libreoffice
  SDPM_SKIP_SHORTCUT=1      Same as --skip-shortcut
HELP
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full) PROFILE=full ;;
    --mcp-only) PROFILE=mcp ;;
    --register) REGISTER=yes ;;
    --agent-name) shift; SDPM_AGENT_NAME="${1:?--agent-name needs a value}" ;;
    --no-register) REGISTER=no ;;
    --deps-only) DEPS_ONLY=1 ;;
    --non-interactive) NON_INTERACTIVE=1 ;;
    --skip-libreoffice) SKIP_LIBREOFFICE=1 ;;
    --skip-shortcut) SKIP_SHORTCUT=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]:-$0}")"
if ! SCRIPT_DIR="$(cd "$SCRIPT_DIR" 2>/dev/null && pwd)"; then
  SCRIPT_DIR="$(pwd)"
fi
if ! declare -F show_header >/dev/null 2>&1; then
  if [[ -f "$SCRIPT_DIR/lib/tui.sh" ]]; then
    # shellcheck source=lib/tui.sh
    source "$SCRIPT_DIR/lib/tui.sh"
  else
    echo "Installer TUI library is missing. Run scripts/install/build.sh and use dist/install.sh." >&2
    exit 1
  fi
fi

OS_NAME="$(uname -s)"
ARCH="$(uname -m)"
case "$OS_NAME" in
  Darwin) OS_TYPE="macos" ;;
  Linux) OS_TYPE="linux" ;;
  *) echo "Unsupported operating system: $OS_NAME" >&2; exit 1 ;;
esac

if [[ "$OS_TYPE" == "linux" ]] && ! has_command apt-get; then
  echo "This installer currently supports apt-based Linux distributions only." >&2
  exit 1
fi

refresh_path() {
  export PATH="$HOME/.local/bin:$LAUNCHER_DIR:$PATH"
  if [[ "$OS_TYPE" == "macos" ]] && has_command brew; then
    eval "$(brew shellenv)"
  fi
}
refresh_path

apt_command() {
  if [[ $(id -u) -eq 0 ]]; then printf 'env DEBIAN_FRONTEND=noninteractive apt-get';
  elif has_command sudo; then printf 'sudo env DEBIAN_FRONTEND=noninteractive apt-get';
  else echo "sudo is required to install apt packages." >&2; return 1
  fi
}

DEP_NAMES=(); DEP_VERSIONS=(); DEP_FOUND=(); DEP_REASONS=(); DEP_HELP=()
add_dep() {
  DEP_NAMES+=("$1"); DEP_VERSIONS+=("$2"); DEP_FOUND+=("$3")
  DEP_REASONS+=("$4"); DEP_HELP+=("$5")
}

scan_dependencies() {
  DEP_NAMES=(); DEP_VERSIONS=(); DEP_FOUND=(); DEP_REASONS=(); DEP_HELP=()
  if [[ "$OS_TYPE" == "macos" ]]; then
    if has_command brew; then add_dep "Homebrew" "$(brew --version | head -1)" 1 "package manager" "https://brew.sh/"
    else add_dep "Homebrew" "" 0 "package manager" "https://brew.sh/"; fi
  fi
  if has_command git; then add_dep "git" "$(git --version | awk '{print $3}')" 1 "source checkout" "https://git-scm.com/"
  else add_dep "git" "" 0 "source checkout" "https://git-scm.com/"; fi
  if has_command uv; then add_dep "uv" "$(uv --version | awk '{print $2}')" 1 "Python environment" "https://docs.astral.sh/uv/"
  else add_dep "uv" "" 0 "Python environment" "https://docs.astral.sh/uv/"; fi
  if [[ "$SKIP_LIBREOFFICE" != "1" ]]; then
    if has_command soffice || has_command libreoffice || [[ -d /Applications/LibreOffice.app ]]; then
      add_dep "LibreOffice" "installed" 1 "slide previews" "https://www.libreoffice.org/download/"
    else add_dep "LibreOffice" "" 0 "slide previews" "https://www.libreoffice.org/download/"; fi
  fi
  if has_command pdftoppm; then add_dep "poppler" "$(pdftoppm -v 2>&1 | head -1)" 1 "PDF previews" "https://poppler.freedesktop.org/"
  else add_dep "poppler" "" 0 "PDF previews" "https://poppler.freedesktop.org/"; fi
  if [[ "$DEPS_ONLY" != "1" && "$PROFILE" == "full" ]]; then
    if has_command node; then
      local node_version node_major
      node_version="$(node --version)"; node_major="${node_version#v}"; node_major="${node_major%%.*}"
      if [[ "$node_major" =~ ^[0-9]+$ ]] && [[ "$node_major" -ge 20 ]]; then add_dep "Node.js" "$node_version" 1 "Web UI" "https://nodejs.org/"
      else add_dep "Node.js" "$node_version (20+ required)" 0 "Web UI" "https://nodejs.org/"; fi
    else add_dep "Node.js" "" 0 "Web UI" "https://nodejs.org/"; fi
    if [[ "${SDPM_SKIP_KIRO_CLI:-0}" != "1" ]]; then
      if has_command kiro-cli; then add_dep "kiro-cli" "installed" 1 "Web UI agent backend" "https://kiro.dev/docs/cli/setup/"
      else add_dep "kiro-cli" "" 0 "Web UI agent backend" "https://kiro.dev/docs/cli/setup/"; fi
    fi
  fi
}

install_homebrew() {
  start_step "Installing Homebrew" "macOS package manager"
  local command='/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  [[ "$NON_INTERACTIVE" == "1" ]] && command="NONINTERACTIVE=1 $command"
  if run_with_spinner "$command"; then
    if [[ -x /opt/homebrew/bin/brew ]]; then eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then eval "$(/usr/local/bin/brew shellenv)"; fi
    complete_step "Homebrew installed ($LAST_ELAPSED)"
  else fail_step "Homebrew installation failed" "$LAST_LOG" "https://brew.sh/"; exit 1; fi
}

install_brew_or_apt() {
  local name="$1" brew_package="$2" apt_package="$3" help_url="$4" command
  start_step "Installing $name" "$name is required by SDPM"
  if [[ "$OS_TYPE" == "macos" ]]; then command="brew install $brew_package"
  else command="$(apt_command) update && $(apt_command) install -y $apt_package"; fi
  if run_with_spinner "$command"; then refresh_path; complete_step "$name installed ($LAST_ELAPSED)"
  else fail_step "$name installation failed" "$LAST_LOG" "$help_url"; exit 1; fi
}

install_libreoffice() {
  start_step "Installing LibreOffice" "Required for PPTX preview rendering"
  local command
  if [[ "$OS_TYPE" == "macos" ]]; then command="brew install --cask libreoffice"
  else command="$(apt_command) update && $(apt_command) install -y libreoffice"; fi
  if run_with_spinner "$command"; then complete_step "LibreOffice installed ($LAST_ELAPSED)"
  else fail_step "LibreOffice installation failed" "$LAST_LOG" "https://www.libreoffice.org/download/"; exit 1; fi
}

install_node() {
  start_step "Installing Node.js" "Node.js 20 LTS or newer is required by the Web UI"
  local command
  if [[ "$OS_TYPE" == "macos" ]]; then
    command="brew install node"
  else
    command="curl -fsSL https://deb.nodesource.com/setup_20.x | $(apt_command | sed 's/ apt-get$//') bash - && $(apt_command) install -y nodejs"
  fi
  if run_with_spinner "$command"; then refresh_path; complete_step "Node.js installed ($LAST_ELAPSED)"
  else fail_step "Node.js installation failed" "$LAST_LOG" "https://nodejs.org/"; exit 1; fi
}

install_uv() {
  start_step "Installing uv" "Python package and runtime manager"
  if run_with_spinner 'curl -LsSf https://astral.sh/uv/install.sh | sh'; then
    refresh_path; complete_step "uv installed ($LAST_ELAPSED)"
  else fail_step "uv installation failed" "$LAST_LOG" "https://docs.astral.sh/uv/"; exit 1; fi
}

install_kiro_cli() {
  start_step "Installing Kiro CLI" "Local Web UI ACP backend"
  local command='curl -fsSL https://cli.kiro.dev/install | bash'
  if [[ "$OS_TYPE" == "linux" ]]; then
    case "$ARCH" in x86_64|amd64|aarch64|arm64) ;;
      *) fail_step "Unsupported Linux architecture: $ARCH" "" "https://kiro.dev/docs/cli/setup/"; exit 1 ;; esac
    command="mkdir -p '$HOME/.local/bin' && curl -fsSL https://desktop-release.q.us-east-1.amazonaws.com/latest/kiro-cli.appimage -o '$HOME/.local/bin/kiro-cli' && chmod +x '$HOME/.local/bin/kiro-cli'"
  fi
  if run_with_spinner "$command"; then refresh_path; complete_step "Kiro CLI installed ($LAST_ELAPSED)"
  else fail_step "Kiro CLI installation failed" "$LAST_LOG" "https://kiro.dev/docs/cli/setup/"; exit 1; fi
}

install_missing_dependencies() {
  local indexes=() i count=${#DEP_NAMES[@]}
  for ((i=0; i<count; i++)); do
    show_check "${DEP_NAMES[i]}" "${DEP_VERSIONS[i]}" "${DEP_FOUND[i]}"
    [[ "${DEP_FOUND[i]}" == "1" ]] || indexes+=("$i")
  done
  if [[ ${#indexes[@]} -eq 0 ]]; then echo ""; printf "    ${C_GREEN}All required dependencies are available.${C_RESET}\n"; return; fi
  echo ""; echo "    Missing dependencies:"
  for i in "${indexes[@]}"; do printf "      - %s (%s)\n" "${DEP_NAMES[i]}" "${DEP_REASONS[i]}"; done
  if ! show_confirm "Install missing dependencies?"; then
    echo "Installation cancelled. Manual installation links:"
    for i in "${indexes[@]}"; do printf "  %s: %s\n" "${DEP_NAMES[i]}" "${DEP_HELP[i]}"; done
    exit 0
  fi
  TOTAL_STEPS=$((TOTAL_STEPS + ${#indexes[@]}))
  for i in "${indexes[@]}"; do
    case "${DEP_NAMES[i]}" in
      Homebrew) install_homebrew ;;
      git) install_brew_or_apt "git" "git" "git" "https://git-scm.com/" ;;
      uv) install_uv ;;
      LibreOffice) install_libreoffice ;;
      poppler) install_brew_or_apt "poppler" "poppler" "poppler-utils" "https://poppler.freedesktop.org/" ;;
      Node.js) install_node ;;
      kiro-cli) install_kiro_cli ;;
    esac
  done
}

setup_checkout() {
  start_step "Downloading SDPM" "$CHECKOUT"
  mkdir -p "$SDPM_HOME"
  if [[ -d "$CHECKOUT/.git" ]]; then
    if run_with_spinner "git -C '$CHECKOUT' fetch --tags --prune origin main && git -C '$CHECKOUT' checkout main && git -C '$CHECKOUT' pull --ff-only origin main"; then
      complete_step "SDPM checkout updated ($LAST_ELAPSED)"
    else fail_step "SDPM update failed" "$LAST_LOG" "$REPO_HELP"; exit 1; fi
  elif [[ -e "$CHECKOUT" ]]; then
    fail_step "$CHECKOUT exists but is not a git checkout" "Move it aside and retry." "$REPO_HELP"; exit 1
  elif run_with_spinner "git clone --branch main --single-branch '$REPO_URL' '$CHECKOUT'"; then
    complete_step "SDPM checkout created ($LAST_ELAPSED)"
  else fail_step "SDPM clone failed" "$LAST_LOG" "$REPO_HELP"; exit 1; fi
}

setup_packages() {
  start_step "Syncing the MCP server environment" "servers/local"
  if run_with_spinner "uv sync --directory '$CHECKOUT/servers/local'"; then complete_step "MCP server ready ($LAST_ELAPSED)"
  else fail_step "uv sync failed" "$LAST_LOG" "$REPO_HELP/blob/main/docs/en/getting-started.md"; exit 1; fi
  echo "$PROFILE" > "$SDPM_HOME/.profile"
  echo "$SDPM_AGENT_NAME" > "$SDPM_HOME/.agent-name"
  local uv_path; uv_path="$(command -v uv)"   # absolute; symlinks kept (brew's bin/uv is the stable path)
  echo "$uv_path" > "$SDPM_HOME/.uv-path"
  [[ "$PROFILE" == "full" ]] || return 0

  start_step "Installing Web UI dependencies" "npm ci"
  if run_with_spinner "npm ci" "$CHECKOUT/web-ui"; then complete_step "Web UI dependencies installed ($LAST_ELAPSED)"
  else fail_step "npm ci failed" "$LAST_LOG" "$REPO_HELP/tree/main/web-ui"; exit 1; fi

  start_step "Building Web UI" "NEXT_PUBLIC_MODE=local npm run build"
  if run_with_spinner "NEXT_PUBLIC_MODE=local npm run build" "$CHECKOUT/web-ui"; then complete_step "Local Web UI built ($LAST_ELAPSED)"
  else fail_step "Local Web UI build failed" "$LAST_LOG" "$REPO_HELP/tree/main/web-ui"; exit 1; fi
}

setup_icon_set() {
  local name="$1" manifest="$2" script="$3"
  if [[ -f "$manifest" ]]; then
    start_step "$name icons" "already available"; complete_step "$name icons skipped"; return
  fi
  start_step "Downloading $name icons" "official icon source"
  if run_with_spinner "uv run --directory '$CHECKOUT/sdpm' python '$script'"; then complete_step "$name icons downloaded ($LAST_ELAPSED)"
  else fail_step "$name icon download failed; retry after installation" "$LAST_LOG" "$REPO_HELP"; fi
}

setup_launcher() {
  start_step "Installing sdpm command" "$LAUNCHER_DIR/sdpm"
  mkdir -p "$LAUNCHER_DIR"
  if [[ -n "${SDPM_LAUNCHER_CONTENT:-}" ]]; then printf '%s\n' "$SDPM_LAUNCHER_CONTENT" > "$LAUNCHER_DIR/sdpm"
  elif [[ -f "$SCRIPT_DIR/launcher.sh" ]]; then cp "$SCRIPT_DIR/launcher.sh" "$LAUNCHER_DIR/sdpm"
  else fail_step "Launcher source is missing" "" "$REPO_HELP"; exit 1; fi
  chmod +x "$LAUNCHER_DIR/sdpm"
  complete_step "sdpm command installed"
}

setup_shortcut() {
  [[ "$SKIP_SHORTCUT" == "1" ]] && return 0
  start_step "Creating desktop shortcut" "SDPM Web UI"
  if [[ "$OS_TYPE" == "macos" ]]; then
    local desktop="$HOME/Desktop"
    if [[ ! -d "$desktop" ]]; then complete_step "Desktop folder not found; shortcut skipped"; return; fi
    printf '#!/bin/bash\nexec "%s/sdpm" webui\n' "$LAUNCHER_DIR" > "$desktop/SDPM.command"
    chmod +x "$desktop/SDPM.command"
  else
    local apps="$HOME/.local/share/applications"
    mkdir -p "$apps"
    cat > "$apps/sdpm.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=SDPM
Comment=Spec-Driven Presentation Maker
Exec=$LAUNCHER_DIR/sdpm webui
Terminal=true
Categories=Office;Presentation;
EOF
    chmod +x "$apps/sdpm.desktop"
  fi
  complete_step "Desktop shortcut created"
}

choose_profile() {
  [[ -n "$PROFILE" ]] && return 0
  if [[ "$NON_INTERACTIVE" == "1" ]]; then PROFILE=full; return 0; fi
  echo ""
  echo "  SDPM has two surfaces on one installation:"
  echo "    - your own AI agent (Kiro CLI, Claude Code, Cursor, ...) through the MCP server"
  echo "    - a browser Web UI (needs Node.js 20+; adds a few minutes of build time)"
  if show_confirm "Also install the browser Web UI? [Y/n]"; then PROFILE=full; else PROFILE=mcp; fi
}

REGISTER_FAILED=0

register_clients() {
  [[ "$REGISTER" == "no" ]] && { "$LAUNCHER_DIR/sdpm" mcp-config || true; return 0; }
  echo ""
  if [[ "$REGISTER" == "yes" ]]; then
    "$LAUNCHER_DIR/sdpm" register --yes || REGISTER_FAILED=1
    return 0
  fi
  if [[ "$NON_INTERACTIVE" == "1" ]]; then "$LAUNCHER_DIR/sdpm" mcp-config || true; return 0; fi
  echo "  Connect your MCP clients now? Each one is asked separately; nothing is written"
  echo "  without your yes, and 'sdpm register' does the same later."
  "$LAUNCHER_DIR/sdpm" register || true
}

show_completion() {
  echo ""; printf "  ${C_GREEN}SDPM is installed.${C_RESET}\n\n"
  echo "    Your agent:   ask it \"Make slides about ...\" — it finds SDPM through MCP."
  echo "                  Kiro CLI: kiro-cli chat --agent $SDPM_AGENT_NAME"
  if [[ "$PROFILE" == "full" ]]; then
    echo "    Browser:      sdpm webui"
    kiro-cli whoami >/dev/null 2>&1 || echo "                  (the Web UI uses Kiro CLI: run 'kiro-cli login' once first)"
  else
    echo "    Browser:      not installed — add it any time with 'sdpm update --with-webui'"
  fi
  echo "    Later:        sdpm            status      sdpm register   connect more clients"
  echo "                  sdpm update     upgrade     sdpm uninstall  remove"
  echo ""; echo "    Checkout: $CHECKOUT"
  if [[ ":$PATH:" != *":$LAUNCHER_DIR:"* ]]; then
    printf "    ${C_YELLOW}Add %s to PATH to run 'sdpm' directly.${C_RESET}\n" "$LAUNCHER_DIR"
  fi
  if [[ "$REGISTER_FAILED" == "1" ]]; then
    printf "    ${C_YELLOW}Some client registrations failed (see above). Fix them with 'sdpm register <client>'.${C_RESET}\n"
    exit 1
  fi
}

main() {
  show_header "SDPM Setup" "$INSTALLER_VERSION"
  [[ "$DEPS_ONLY" == "1" ]] || choose_profile
  scan_dependencies
  TOTAL_STEPS=0
  if [[ "$DEPS_ONLY" != "1" ]]; then
    TOTAL_STEPS=5
    [[ "$PROFILE" == "full" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 2 + (SKIP_SHORTCUT == 1 ? 0 : 1)))
  fi
  install_missing_dependencies
  if [[ "$DEPS_ONLY" == "1" ]]; then
    echo ""; printf "  ${C_GREEN}Dependency setup complete.${C_RESET}\n"; uv --version; return
  fi
  setup_checkout
  setup_packages
  setup_icon_set "AWS Architecture" "$CHECKOUT/sdpm/assets/aws/manifest.json" "$CHECKOUT/sdpm/scripts/download_aws_icons.py"
  setup_icon_set "Material Symbols" "$CHECKOUT/sdpm/assets/material/manifest.json" "$CHECKOUT/sdpm/scripts/download_material_icons.py"
  setup_launcher
  [[ "$PROFILE" == "full" ]] && setup_shortcut
  register_clients
  show_completion
}

main
