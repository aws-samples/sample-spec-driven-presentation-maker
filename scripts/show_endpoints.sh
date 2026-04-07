#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# show_endpoints.sh — Display CloudFront URL and Cognito User Pool console URL
#                     from deployed CloudFormation stacks.
#
# Usage:
#   ./scripts/show_endpoints.sh
#   ./scripts/show_endpoints.sh --region us-west-2
#   ./scripts/show_endpoints.sh --profile my-profile

set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-1}"
PROFILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)  REGION="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    *)         echo "Unknown option: $1"; exit 1 ;;
  esac
done

AWS_OPTS="--region ${REGION}"
if [ -n "$PROFILE" ]; then
  AWS_OPTS="${AWS_OPTS} --profile ${PROFILE}"
fi

# --- Fetch CloudFormation outputs ---
SITE_URL=$(aws cloudformation describe-stacks \
  --stack-name SdpmWebUi ${AWS_OPTS} \
  --query 'Stacks[0].Outputs[?OutputKey==`SiteUrl`].OutputValue' \
  --output text 2>/dev/null || echo "")

USER_POOL_ID=$(aws cloudformation describe-stacks \
  --stack-name SdpmAuth ${AWS_OPTS} \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text 2>/dev/null || echo "")

if [ -z "${SITE_URL}" ]; then
  echo "Error: SdpmWebUi stack not found or has no SiteUrl output."
  echo "Make sure Layer 4 (--layer4) has been deployed in region ${REGION}."
  exit 1
fi

COGNITO_CONSOLE_URL="https://${REGION}.console.aws.amazon.com/cognito/v2/idp/user-pools/${USER_POOL_ID}/users?region=${REGION}"

echo ""
echo "========================================="
echo "  CloudFront URL      : ${SITE_URL}"
echo "  Cognito User Pool   : ${COGNITO_CONSOLE_URL}"
echo "========================================="
echo ""
echo "1. Open the Cognito User Pool console to create a user"
echo "2. Open the CloudFront URL to access the Web UI"
