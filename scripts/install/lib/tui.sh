#!/usr/bin/env bash
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

# Two-row checklist matching the client picker in servers/local/client_config.py: the MCP
# server row is always on; the Web UI row toggles. Sets SURFACE_WEBUI=1|0. Falls back to
# show_confirm without a terminal.
show_surface_picker() {
  SURFACE_WEBUI=1
  if [[ "${NON_INTERACTIVE:-0}" == "1" ]]; then return 0; fi
  if [[ ! -r /dev/tty || ! -t 1 ]]; then
    if show_confirm "Also install the browser Web UI? [Y/n]"; then SURFACE_WEBUI=1; else SURFACE_WEBUI=0; fi
    return 0
  fi
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
