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

# The TTY rule: stdout is a terminal and /dev/tty opens. Without it the answer is the default
# (yes), unasked, exactly as with --non-interactive; nothing waits for input.
tty_prompt_allowed() { [[ "${NON_INTERACTIVE:-0}" != "1" && -t 1 ]] && { : </dev/tty; } 2>/dev/null; }

show_confirm() {
  local prompt="$1" reply
  # Under `curl … | bash` stdin is the script itself; prompts must come from the terminal.
  tty_prompt_allowed || return 0
  printf "\n  %s " "$prompt"
  read -r reply </dev/tty
  case "${reply:-y}" in [Yy]*|"") return 0 ;; *) return 1 ;; esac
}

# Two-row checklist matching the client picker in servers/local/client_config.py: the MCP
# server row is always on; the Web UI row toggles. Sets SURFACE_WEBUI=1|0; without a
# terminal (the TTY rule) it keeps the default, both.
show_surface_picker() {
  SURFACE_WEBUI=1
  tty_prompt_allowed || return 0
  _render_surfaces() {
    printf "  What to install   ${C_DIM}space toggle · enter confirm${C_RESET}\n\n"
    printf "        ${C_DIM}[x] MCP server        for your AI agent — always installed${C_RESET}\n"
    if [[ "$SURFACE_WEBUI" == "1" ]]; then
      printf "  ${C_CYAN}❯${C_RESET} ${C_GREEN}[x]${C_RESET} Browser Web UI    ${C_DIM}needs Node.js 20+; a few minutes of build${C_RESET}\n"
    else
      printf "  ${C_CYAN}❯${C_RESET} [ ] Browser Web UI    ${C_DIM}needs Node.js 20+; a few minutes of build${C_RESET}\n"
    fi
  }
  local key
  printf '\033[?25l'
  _render_surfaces
  while :; do
    IFS= read -rsn1 key </dev/tty || break
    case "$key" in
      " ") SURFACE_WEBUI=$((1 - SURFACE_WEBUI)) ;;
      "") break ;;
      $'\033') IFS= read -rsn2 -t 1 key </dev/tty || true ;;   # arrows: nothing to move to
      q) SURFACE_WEBUI=1; break ;;
    esac
    printf '\033[4A\033[J'
    _render_surfaces
  done
  printf '\033[4A\033[J\033[?25h'
  if [[ "$SURFACE_WEBUI" == "1" ]]; then echo "  What to install: MCP server, Browser Web UI"
  else echo "  What to install: MCP server"; fi
  echo ""
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
REGISTER="${SDPM_REGISTER:-default}" # default | yes | no
AGENT_NAME="${SDPM_AGENT_NAME:-}"    # the Kiro CLI agent; passed on only when given
CHANNEL="${SDPM_CHANNEL:-}"          # release | main; passed on only when given
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
  --channel CHANNEL    release (default: the latest release) or main (every merged change)
                       Over an existing install, its profile, agent name and channel are kept
  --no-register        Skip client registration (print the configuration instead)
  --deps-only          Install git, uv, LibreOffice, and poppler only
  --non-interactive    Accept dependency installation prompts; default profile: full
                       (also the behaviour without a terminal: nothing waits for input)
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
  SDPM_CHANNEL=release|main Same as --channel
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
    --agent-name) shift; AGENT_NAME="${1:?--agent-name needs a value}" ;;
    --channel) shift; CHANNEL="${1:?--channel needs release or main}" ;;
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

case "$CHANNEL" in ""|release|main) ;; *) echo "--channel must be release or main, not '$CHANNEL'." >&2; exit 2 ;; esac
case "$PROFILE" in ""|full|mcp) ;; *) echo "SDPM_PROFILE must be full or mcp, not '$PROFILE'." >&2; exit 2 ;; esac
case "$REGISTER" in default|ask) REGISTER=default ;; yes|no) ;;
  *) echo "SDPM_REGISTER must be yes or no, not '$REGISTER'." >&2; exit 2 ;; esac

# The one rule for asking anything: stdout is a terminal and /dev/tty opens. Under
# `curl | bash` stdin is the script, so it says nothing; an agent captures stdout. Without
# a terminal the installer runs exactly as with --non-interactive and never waits.
prompt_allowed() { [[ "$NON_INTERACTIVE" != "1" && -t 1 ]] && { : </dev/tty; } 2>/dev/null; }
prompt_allowed || NON_INTERACTIVE=1

# Over an existing install, keep its profile unless told otherwise. An old sdpm command can
# write .profile=full after state.json said mcp (`sdpm update --with-webui`); full wins.
recorded_profile() {
  local legacy="" recorded=""
  [[ -f "$SDPM_HOME/.profile" ]] && legacy="$(cat "$SDPM_HOME/.profile" 2>/dev/null || true)"
  [[ "$legacy" == "full" ]] && { echo full; return; }
  [[ -f "$SDPM_HOME/state.json" ]] &&
    recorded="$(sed -nE 's/^[[:space:]]*"profile":[[:space:]]*"(full|mcp)".*/\1/p' "$SDPM_HOME/state.json" | head -1)"
  [[ -n "$recorded" ]] && { echo "$recorded"; return; }
  case "$legacy" in full|mcp) echo "$legacy" ;; esac
}
[[ -n "$PROFILE" ]] || PROFILE="$(recorded_profile)"

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

# PATH as the user's shell has it, before this run adds to it: the completion screen says
# whether the launcher directory still needs adding.
ORIG_PATH="$PATH"
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

# Before the first step that needs sudo (apt on Linux, the Homebrew install on macOS): with
# a terminal, ask for the password once, outside the spinner; without one, never wait on
# it: print what a person has to run and stop. Root needs no sudo.
SUDO_READY=0
ensure_sudo() {
  local commands="$1"
  [[ "$SUDO_READY" == "1" || $(id -u) -eq 0 ]] && return 0
  # shellcheck disable=SC2024 # sudo -v reads the password from the terminal, as intended
  if has_command sudo; then
    if ! prompt_allowed; then
      if sudo -n true 2>/dev/null; then SUDO_READY=1; return 0; fi
    elif sudo -v </dev/tty; then SUDO_READY=1; return 0
    fi
  fi
  echo "" >&2
  if has_command sudo; then echo "sudo needs a password, and nobody can type it here. Run this, then the installer again:" >&2
  else echo "sudo is required to install these packages. Run this as root, then the installer again:" >&2; fi
  printf '%s\n' "$commands" | sed 's/^/  /' >&2
  exit 1
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
  local apt_packages="" node_line="" name
  for i in "${indexes[@]}"; do
    name="${DEP_NAMES[i]}"
    case "$name" in
      Homebrew) ensure_sudo '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' ;;
      git) apt_packages+=" git" ;;
      poppler) apt_packages+=" poppler-utils" ;;
      LibreOffice) apt_packages+=" libreoffice" ;;
      Node.js) apt_packages+=" nodejs"; node_line="curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -" ;;
    esac
  done
  if [[ "$OS_TYPE" == "linux" && -n "$apt_packages" ]]; then
    ensure_sudo "${node_line:+$node_line
}sudo apt-get update && sudo apt-get install -y${apt_packages}"
  fi
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

EXISTING=0   # 1: this run is over an install that exists (its manifest counts as an update)

setup_checkout() {
  start_step "Downloading SDPM" "$CHECKOUT"
  mkdir -p "$SDPM_HOME"
  if [[ -d "$CHECKOUT/.git" ]]; then
    EXISTING=1
    # The sdpm command's fetch: origin's main and tags, local tags mirroring origin's.
    if run_with_spinner "git -C '$CHECKOUT' fetch --quiet --prune origin '+refs/heads/main:refs/remotes/origin/main' '+refs/tags/*:refs/tags/*'"; then
      complete_step "SDPM fetched ($LAST_ELAPSED)"
    else fail_step "SDPM fetch failed" "$LAST_LOG" "$REPO_HELP"; exit 1; fi
  elif [[ -e "$CHECKOUT" ]]; then
    fail_step "$CHECKOUT exists but is not a git checkout" "Move it aside and retry." "$REPO_HELP"; exit 1
  elif run_with_spinner "git clone --branch main --single-branch '$REPO_URL' '$CHECKOUT'"; then
    complete_step "SDPM checkout created ($LAST_ELAPSED)"
  else fail_step "SDPM clone failed" "$LAST_LOG" "$REPO_HELP"; exit 1; fi
}

# main's checkout_update.py (this installer is main's code too), run before anything is
# checked out: it picks the latest release (or main), moves the checkout there, then hands
# over to that version's own setup: Python environment, Web UI, icons, the sdpm command,
# clients, state.json. Its output is not wrapped, so uv, npm and the client picker show as
# they are.
SETUP_STATUS=0
hand_off() {
  local tmp uv_path args
  uv_path="$(command -v uv)"   # absolute; symlinks kept (brew's bin/uv is the stable path)
  tmp=$(mktemp -d) || { SETUP_STATUS=1; return; }
  args=(--checkout "$CHECKOUT" --uv "$uv_path" install --launcher "$LAUNCHER_DIR/sdpm"
        --register "$REGISTER" --profile "$PROFILE")
  [[ "$EXISTING" == "1" ]] || args+=(--new-checkout)
  [[ -n "$AGENT_NAME" ]] && args+=(--agent-name "$AGENT_NAME")
  [[ -n "$CHANNEL" ]] && args+=(--channel "$CHANNEL")
  [[ "$NON_INTERACTIVE" == "1" ]] && args+=(--non-interactive)
  echo ""
  if git -C "$CHECKOUT" --work-tree="$tmp" restore --source=refs/remotes/origin/main --worktree -- servers/local/checkout_update.py; then
    "$uv_path" run --no-project --isolated --python ">=3.11" python "$tmp/servers/local/checkout_update.py" "${args[@]}"
    SETUP_STATUS=$?
  else
    SETUP_STATUS=1
  fi
  rm -rf "$tmp"
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
  show_surface_picker
  if [[ "$SURFACE_WEBUI" == "1" ]]; then PROFILE=full; else PROFILE=mcp; fi
}

# The client table above (✓ registered / – skipped / ✗ failed) is the part that matters;
# nothing here repeats it.
show_completion() {
  local profile
  profile="$(recorded_profile)"; profile="${profile:-$PROFILE}"
  echo ""
  printf "  ${C_GREEN}SDPM is installed${C_RESET} in $CHECKOUT\n\n"
  if [[ "$profile" == "full" ]]; then
    echo "    Browser:   sdpm webui"
    kiro-cli whoami >/dev/null 2>&1 || echo "               (the Web UI uses Kiro CLI — run 'kiro-cli login' once first)"
  else
    echo "    Browser:   not installed — sdpm update --with-webui"
  fi
  echo "    Agents:    ask for slides in a registered client (table above)"
  echo "    Later:     sdpm  ·  sdpm register  ·  sdpm update  ·  sdpm uninstall"
  if [[ ":$ORIG_PATH:" != *":$LAUNCHER_DIR:"* ]]; then
    printf "    ${C_YELLOW}Add %s to PATH to run 'sdpm' directly.${C_RESET}\n" "$LAUNCHER_DIR"
  fi
  if [[ "$SETUP_STATUS" == "4" ]]; then
    printf "    ${C_YELLOW}Some steps did not finish (see above). Fix client registrations with 'sdpm register <client>'.${C_RESET}\n"
    exit 1
  fi
}

main() {
  show_header "SDPM Setup" "$INSTALLER_VERSION"
  [[ "$DEPS_ONLY" == "1" ]] || choose_profile
  scan_dependencies
  TOTAL_STEPS=0
  if [[ "$DEPS_ONLY" != "1" ]]; then
    TOTAL_STEPS=1
    [[ "$PROFILE" == "full" && "$SKIP_SHORTCUT" != "1" ]] && TOTAL_STEPS=2
  fi
  install_missing_dependencies
  if [[ "$DEPS_ONLY" == "1" ]]; then
    echo ""; printf "  ${C_GREEN}Dependency setup complete.${C_RESET}\n"; uv --version; return
  fi
  setup_checkout
  hand_off
  if [[ "$SETUP_STATUS" != "0" && "$SETUP_STATUS" != "4" ]]; then
    echo ""
    fail_step "SDPM setup failed (see above)" "" "$REPO_HELP/blob/main/docs/en/getting-started.md#sdpm-update-stops"
    exit "$SETUP_STATUS"
  fi
  [[ "$PROFILE" == "full" ]] && setup_shortcut
  show_completion
}

main
