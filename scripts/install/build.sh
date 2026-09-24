#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# shellcheck disable=SC2129
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$ROOT/dist"
CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1
[[ $# -le 1 ]] || { echo "Usage: build.sh [--check]" >&2; exit 2; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

{
  echo '#!/usr/bin/env bash'
  echo '# shellcheck disable=SC1091,SC2016,SC2059'
  tail -n +2 "$ROOT/lib/tui.sh"
  cat <<'EMBED_START'

SDPM_LAUNCHER_CONTENT=''
IFS= read -r -d '' SDPM_LAUNCHER_CONTENT <<'__SDPM_LAUNCHER__' || true
EMBED_START
  cat "$ROOT/launcher.sh"
  cat <<'EMBED_END'
__SDPM_LAUNCHER__
EMBED_END
  tail -n +2 "$ROOT/install.sh"
} > "$tmp/install.sh"
chmod +x "$tmp/install.sh"

awk '{ print; if ($0 == "# __INSTALL_BODY_BELOW__") exit }' "$ROOT/install.ps1" > "$tmp/install.ps1"
cat "$ROOT/lib/tui.ps1" >> "$tmp/install.ps1"
cat >> "$tmp/install.ps1" <<'PS_EMBED_START'

$script:EmbeddedLauncher = @'
PS_EMBED_START
cat "$ROOT/launcher.ps1" >> "$tmp/install.ps1"
cat >> "$tmp/install.ps1" <<'PS_EMBED_END'
'@
PS_EMBED_END
awk 'found { print } $0 == "# __INSTALL_BODY_BELOW__" { found=1 }' "$ROOT/install.ps1" >> "$tmp/install.ps1"

if [[ "$CHECK" == "1" ]]; then
  status=0
  for file in install.sh install.ps1; do
    if [[ ! -f "$DIST/$file" ]] || ! cmp -s "$tmp/$file" "$DIST/$file"; then
      echo "Generated installer is stale: scripts/install/dist/$file" >&2
      status=1
    fi
  done
  exit "$status"
fi

mkdir -p "$DIST"
cp "$tmp/install.sh" "$DIST/install.sh"
cp "$tmp/install.ps1" "$DIST/install.ps1"
chmod +x "$DIST/install.sh"
echo "Generated scripts/install/dist/install.sh and install.ps1"
