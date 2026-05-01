#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
# Deploy web-ui to S3 + CloudFront.
# IMPORTANT: Excludes aws-exports.json (managed by CDK WriteAwsExports custom resource).

set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-1}"
STACK="SdpmWebUi"
WEBUI_DIR="$(dirname "$0")/../web-ui"
BUILD_DIR="$WEBUI_DIR/build"

# Always rebuild to avoid shipping a stale build/ (missing chunks cause
# CloudFront to SPA-fallback HTML to .js requests -> "Unexpected token '<'").
echo "Building web-ui..."
# Resolve model config (NEXT_PUBLIC_ALLOWED_MODELS, NEXT_PUBLIC_DEFAULT_CHAT_MODEL_ID,
# NEXT_PUBLIC_DEFAULT_CREATE_MODEL_ID) from infra/config.yaml + infra/lib/model-metadata.ts.
# Without this, the Settings Sheet "Models" section is hidden (allowed.length === 0).
MODEL_ENV=$(cd "$(dirname "$0")/../infra" && node lib/resolve-model-env.js)
(cd "$WEBUI_DIR" && rm -rf build && eval "$MODEL_ENV" && npm run build:cloud)

if [ ! -d "$BUILD_DIR" ]; then
  echo "Error: $BUILD_DIR not found after build."
  exit 1
fi

SITE_BUCKET=$(aws cloudformation list-stack-resources \
  --stack-name "$STACK" \
  --query 'StackResourceSummaries[?starts_with(LogicalResourceId,`SiteBucket`) && ResourceType==`AWS::S3::Bucket`].PhysicalResourceId' \
  --output text --region "$REGION")

CF_DIST=$(aws cloudformation list-stack-resources \
  --stack-name "$STACK" \
  --query 'StackResourceSummaries[?ResourceType==`AWS::CloudFront::Distribution`].PhysicalResourceId' \
  --output text --region "$REGION")

echo "Bucket: $SITE_BUCKET"
echo "Distribution: $CF_DIST"

aws s3 sync "$BUILD_DIR" "s3://$SITE_BUCKET/" \
  --delete \
  --exclude "aws-exports.json" \
  --region "$REGION"

aws cloudfront create-invalidation \
  --distribution-id "$CF_DIST" \
  --paths "/*" \
  --query 'Invalidation.Id' \
  --output text \
  --region "$REGION"

echo "Done."
