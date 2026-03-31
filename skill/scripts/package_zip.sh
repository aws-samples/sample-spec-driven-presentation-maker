#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# spec-driven-presentation-maker配布用zipを作成してDesktopに配置する
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
OUT=~/Desktop/spec-driven-presentation-maker.zip

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
zip "$OUT" templates/default-dark.pptx templates/default-light.pptx

echo ""
echo "Created: $OUT"
ls -lh "$OUT"
