#!/usr/bin/env bash
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
