#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUTPUT="$ROOT/dist/sdpm.mcpb"
MCPB_PACKAGE="${MCPB_PACKAGE:-@anthropic-ai/mcpb@2.1.2}"
SKIP_ASSETS=false

usage() {
  cat <<'EOF'
Usage: scripts/build_mcpb.sh [--skip-assets]

Build dist/sdpm.mcpb. By default, official AWS and Material icon catalogs are
fetched into the bundle. Use --skip-assets for a fast local validation build.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-assets) SKIP_ASSETS=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

STAGE=$(mktemp -d "${TMPDIR:-/tmp}/sdpm-mcpb.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT

# Copy only runtime source. These exclusions are repeated in .mcpbignore so a
# manual pack from the staging tree remains safe as well.
tar -C "$ROOT" \
  --exclude='.venv' \
  --exclude='*/.venv' \
  --exclude='.kiro' \
  --exclude='*/.kiro' \
  --exclude='__pycache__' \
  --exclude='*/__pycache__' \
  --exclude='tests' \
  --exclude='*/tests' \
  --exclude='.DS_Store' \
  --exclude='*/.DS_Store' \
  --exclude='*.pyc' \
  -cf - servers/local sdpm shared | tar -C "$STAGE" -xf -
cp "$ROOT/clients/claude-desktop/manifest.json" "$STAGE/manifest.json"
cp "$ROOT/clients/claude-desktop/.mcpbignore" "$STAGE/.mcpbignore"

# The UV MCPB runtime requires a pyproject.toml at bundle root. Reuse the local
# server's dependency declaration, point its sdpm-skill source into the bundle,
# and avoid packaging the staging root itself (the entry point is explicit).
sed 's#path = "../../sdpm"#path = "sdpm"#' "$ROOT/servers/local/pyproject.toml" |
  awk '/^\[tool\.uv\.sources\]$/ { print "[tool.uv]"; print "package = false"; print "" } { print }' \
  > "$STAGE/pyproject.toml"

if [[ "$SKIP_ASSETS" == false ]]; then
  (
    cd "$STAGE"
    uv run python sdpm/scripts/download_aws_icons.py
    uv run python sdpm/scripts/download_material_icons.py
  )
fi

mkdir -p "$(dirname "$OUTPUT")"
npx -y "$MCPB_PACKAGE" validate "$STAGE/manifest.json"
rm -f "$OUTPUT"
npx -y "$MCPB_PACKAGE" pack "$STAGE" "$OUTPUT"
test -s "$OUTPUT"
echo "Built $OUTPUT"
