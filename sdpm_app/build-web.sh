#!/usr/bin/env bash
# Build web-ui static export and bundle into sdpm_app/web/
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT/web-ui"
npm install --silent
npx next build

OUT="$ROOT/sdpm_app/web"
rm -rf "$OUT"
cp -R "$ROOT/web-ui/build" "$OUT"
echo "[sdpm] Bundled web UI → $OUT"
