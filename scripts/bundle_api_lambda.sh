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
# Wheels only, for the Lambda platform (python3.13 = Amazon Linux 2023, glibc 2.34),
# whatever the host is (an arm64 CodeBuild or a Mac builds the same bundle). Uses uv
# from PATH, or installs the pinned version into a temporary directory when there is
# none (CodeBuild, the bundling image).
set -euo pipefail

UV_VERSION="0.13.6"

OUT="${1:?usage: bundle_api_lambda.sh OUTDIR}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$OUT"

UV="$(command -v uv || true)"
UV_DIR=""
if [ -z "$UV" ]; then
  UV_DIR="$(mktemp -d)"
  python3 -m pip install --quiet --disable-pip-version-check --no-cache-dir --target "$UV_DIR" "uv==$UV_VERSION"
  UV="$UV_DIR/bin/uv"
fi

REQS="$(mktemp)"
trap 'rm -rf "$REQS" ${UV_DIR:+"$UV_DIR"}' EXIT
# Exactly the locked versions (uv.lock at the repo root), hash-checked; nothing resolves here.
"$UV" export --frozen --directory "$ROOT" --package sdpm-api --no-dev --no-emit-workspace \
  --quiet -o "$REQS"
"$UV" pip install \
  --target "$OUT" \
  --python-platform x86_64-manylinux_2_34 \
  --python-version 3.13 \
  --only-binary :all: \
  --require-hashes \
  --no-deps \
  --no-cache \
  -r "$REQS"

cp -r "$ROOT"/api/*.py "$OUT"/
cp -r "$ROOT/shared" "$OUT/shared"
# sdpm Engine — required by sdpm.engine.analyzer for template analysis
# (GET /templates, POST /templates/user); its dependencies come from sdpm-skill.
cp -r "$ROOT/sdpm/sdpm" "$OUT/sdpm"
