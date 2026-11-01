#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Build the REST API Lambda bundle (x86_64, Python 3.13) into OUTDIR.
#
# The one definition of the bundle: CDK's local bundling, CDK's Docker fallback
# (infra/lib/web-ui-stack.ts) and CI (.github/workflows/ci.yml, api-lambda) all run
# this script, so CI checks exactly what a deploy ships.
#
# Wheels only, for the Lambda platform, whatever the host is (an arm64 CodeBuild or
# a Mac builds the same bundle). Uses uv from PATH, or installs the pinned version
# into a temporary directory when there is none (CodeBuild, the bundling image).
set -euo pipefail

UV_VERSION="0.13.6"

OUT="${1:?usage: bundle_api_lambda.sh OUTDIR}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$OUT"

UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  UV_DIR="$(mktemp -d)"
  trap 'rm -rf "$UV_DIR"' EXIT
  python3 -m pip install --quiet --disable-pip-version-check --no-cache-dir --target "$UV_DIR" "uv==$UV_VERSION"
  UV="$UV_DIR/bin/uv"
fi

"$UV" pip install \
  --target "$OUT" \
  --python-platform x86_64-manylinux2014 \
  --python-version 3.13 \
  --only-binary :all: \
  --no-cache \
  -r "$ROOT/api/requirements.txt"

cp -r "$ROOT"/api/* "$OUT"/
cp -r "$ROOT/shared" "$OUT/shared"
# sdpm Engine — required by shared.ingest._convert_pptx for upload-time
# PPTX → deck conversion (deck.json + slides/*.json + template.pptx).
cp -r "$ROOT/sdpm/sdpm" "$OUT/sdpm"
