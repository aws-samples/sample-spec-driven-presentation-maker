#!/bin/bash
# pptx-maker配布用zipを作成してDesktopに配置する
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
OUT=~/Desktop/pptx-maker.zip

cd "$SRC"
rm -f "$OUT"

zip -r "$OUT" . \
  -x '.venv/*' \
  -x '.git/*' \
  -x '.kiro/*' \
  -x '.DS_Store' \
  -x 'icons/*' \
  -x '*__pycache__/*' \
  -x '~$*' \
  -x './*.json' \
  -x './*.pptx' \
  -x 'uv.lock' \
  -x '.pytest_cache/*' \
  -x 'dist/*' \
  -x '*.egg-info/*' \
  -x 'Makefile' \
  -x 'tests/*'

# テンプレートだけ追加
zip "$OUT" templates/aws-brand-dark.pptx templates/aws-brand-light.pptx

echo ""
echo "Created: $OUT"
ls -lh "$OUT"
