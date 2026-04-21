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
(cd "$WEBUI_DIR" && rm -rf build && npm run build)

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
