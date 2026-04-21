#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# =============================================================================
# deploy.sh — Deploy spec-driven-presentation-maker via CodeBuild (no local CDK/Docker required)
#
# Usage:
#   ./scripts/deploy.sh                    # Layer 4 full stack (default)
#   ./scripts/deploy.sh --layer3           # Layer 3 only (MCP Server)
#   ./scripts/deploy.sh --layer4           # Layer 4 explicit
#   ./scripts/deploy.sh --destroy          # Tear down all stacks
#
# Prerequisites:
#   - AWS CLI configured (CloudShell has this by default)
#   - Sufficient IAM permissions (AdministratorAccess recommended for first deploy)
# =============================================================================

set -euo pipefail

# Ensure we run from the repository root regardless of where the script is invoked
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}/.."

# ---- Defaults ----
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
PROFILE=""
LAYER="4"
SEARCH_SLIDES="false"
OBSERVABILITY="false"
OIDC_URL=""
ALLOWED_CLIENTS=""
WAF_IPV4=""
WAF_IPV6=""
CDK_COMMAND="deploy"
PROJECT_NAME="sdpm-deploy"
STACK=""

# ---- Load defaults from infra/config.yaml if present ----
# CLI arguments below will override these values.
CONFIG_FILE="infra/config.yaml"
if [ -f "${CONFIG_FILE}" ]; then
  _agent=$(grep -E "^\s*agent:" "${CONFIG_FILE}" | head -1 | awk '{print $2}' | tr -d '"' || true)
  _webui=$(grep -E "^\s*webUi:" "${CONFIG_FILE}" | head -1 | awk '{print $2}' | tr -d '"' || true)
  if [ "${_agent}" = "false" ] && [ "${_webui}" = "false" ]; then
    LAYER="3"
  fi
  _search=$(grep -E "^\s*searchSlides:" "${CONFIG_FILE}" | head -1 | awk '{print $2}' | tr -d '"' || true)
  [ -n "${_search}" ] && SEARCH_SLIDES="${_search}"
  _obs=$(grep -E "^\s*observability:" "${CONFIG_FILE}" | head -1 | awk '{print $2}' | tr -d '"' || true)
  [ -n "${_obs}" ] && OBSERVABILITY="${_obs}"
  # WAF IPv4/IPv6: collect list items under each key
  WAF_IPV4=$(awk '/allowedIpV4AddressRanges:/{f=1;next} f && /^[[:space:]]*-/{gsub(/["]/,"",$2); printf "%s,", $2; next} f && !/^[[:space:]]*-/{f=0}' "${CONFIG_FILE}" | sed 's/,$//')
  WAF_IPV6=$(awk '/allowedIpV6AddressRanges:/{f=1;next} f && /^[[:space:]]*-/{gsub(/["]/,"",$2); printf "%s,", $2; next} f && !/^[[:space:]]*-/{f=0}' "${CONFIG_FILE}" | sed 's/,$//')
  _oidc=$(grep -E "^\s*oidcDiscoveryUrl:" "${CONFIG_FILE}" | head -1 | sed -E 's/^[^:]+:\s*"?([^"]*)"?\s*$/\1/' || true)
  [ -n "${_oidc}" ] && OIDC_URL="${_oidc}"
fi

# ---- Parse arguments ----
usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Deploy spec-driven-presentation-maker to AWS via CodeBuild. No local CDK or Docker required.

Options:
  --region REGION          Deploy region (default: \$AWS_DEFAULT_REGION or us-east-1)
  --profile PROFILE        AWS CLI profile

  --layer3                 Layer 3 only — MCP Server (no Agent, no Web UI)
  --layer4                 Layer 4 full stack — Agent + Web UI (default)
  --search                 Enable semantic slide search (Bedrock KB)
  --observability          Enable Bedrock Model Invocation Logging

  --oidc-url URL           External IdP OIDC Discovery URL
  --allowed-clients IDS    Comma-separated JWT allowed client IDs

  --waf-ipv4 CIDRS         Comma-separated IPv4 CIDR ranges for WAF (e.g. "1.2.3.4/32,10.0.0.0/8")
  --waf-ipv6 CIDRS         Comma-separated IPv6 CIDR ranges for WAF

  --destroy                Destroy all stacks
  --stack ARGS             CDK stack selector/flags (e.g. "SdpmRuntime --exclusively")
                           Default: --all

  -h, --help               Show this help
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)         REGION="$2"; shift 2 ;;
    --profile)        PROFILE="$2"; shift 2 ;;
    --layer3)         LAYER="3"; shift ;;
    --layer4)         LAYER="4"; shift ;;
    --search)         SEARCH_SLIDES="true"; shift ;;
    --observability)  OBSERVABILITY="true"; shift ;;
    --oidc-url)       OIDC_URL="$2"; shift 2 ;;
    --allowed-clients) ALLOWED_CLIENTS="$2"; shift 2 ;;
    --waf-ipv4)       WAF_IPV4="$2"; shift 2 ;;
    --waf-ipv6)       WAF_IPV6="$2"; shift 2 ;;
    --destroy)        CDK_COMMAND="destroy"; shift ;;
    --stack)          STACK="$2"; shift 2 ;;
    -h|--help)        usage ;;
    *)                echo "Unknown option: $1"; usage ;;
  esac
done

# Derive stack flags from layer selection
if [ "$LAYER" = "3" ]; then
  STACK_AGENT="false"
  STACK_WEB_UI="false"
else
  STACK_AGENT="true"
  STACK_WEB_UI="true"
fi

# Build AWS CLI options
AWS_OPTS="--region ${REGION}"
if [ -n "$PROFILE" ]; then
  AWS_OPTS="${AWS_OPTS} --profile ${PROFILE}"
fi

# ---- Resolve account ID ----
ACCOUNT_ID=$(aws sts get-caller-identity ${AWS_OPTS} --query Account --output text)
echo "Account: ${ACCOUNT_ID}"
echo "Region:  ${REGION}"
echo "Layer:   ${LAYER}"
echo "Search:  ${SEARCH_SLIDES}"
echo "Observ:  ${OBSERVABILITY}"
echo "WAF v4:  ${WAF_IPV4:-(none)}"
echo "WAF v6:  ${WAF_IPV6:-(none)}"
echo "Command: ${CDK_COMMAND}"
echo ""

# ---- Check existing MIL configuration ----
if [ "${OBSERVABILITY}" = "true" ] && [ "${CDK_COMMAND}" = "deploy" ]; then
  EXISTING_MIL=$(aws bedrock get-model-invocation-logging-configuration ${AWS_OPTS} \
    --query 'loggingConfig.cloudWatchConfig.logGroupName' --output text 2>/dev/null || echo "None")
  if [ "${EXISTING_MIL}" != "None" ] && [ -n "${EXISTING_MIL}" ]; then
    echo "⚠️  WARNING: Bedrock Model Invocation Logging is already configured in this account/region."
    echo "   Existing log group: ${EXISTING_MIL}"
    echo "   Skipping --observability to preserve the existing configuration."
    echo ""
    OBSERVABILITY="false"
  fi
fi

# ---- S3 bucket for source upload ----
SOURCE_BUCKET="${PROJECT_NAME}-${ACCOUNT_ID}-${REGION}"

# Create bucket if it doesn't exist
if ! aws s3api head-bucket --bucket "${SOURCE_BUCKET}" ${AWS_OPTS} 2>/dev/null; then
  echo "Creating source bucket: ${SOURCE_BUCKET}"
  if [ "${REGION}" = "us-east-1" ]; then
    aws s3api create-bucket \
      --bucket "${SOURCE_BUCKET}" \
      ${AWS_OPTS}
  else
    aws s3api create-bucket \
      --bucket "${SOURCE_BUCKET}" \
      --create-bucket-configuration LocationConstraint="${REGION}" \
      ${AWS_OPTS}
  fi
fi

# ---- Zip and upload source ----
echo "Packaging source..."
TMPDIR=$(mktemp -d)
SOURCE_ZIP="${TMPDIR}/source.zip"

# Zip the repo, excluding unnecessary files to keep the archive small
zip -r "${SOURCE_ZIP}" . \
  -x ".git/*" \
  -x ".kiro/*" \
  -x ".venv/*" \
  -x "venv/*" \
  -x "*/.venv/*" \
  -x "__pycache__/*" \
  -x "*.pyc" \
  -x "infra/cdk.out/*" \
  -x "infra/node_modules/*" \
  -x "web-ui/node_modules/*" \
  -x "web-ui/.next/*" \
  -x "web-ui/build/*" \
  -x "skill/assets/aws/*" \
  -x "skill/assets/material/*" \
  -x ".ruff_cache/*" \
  -x ".pytest_cache/*" \
  -x ".DS_Store" \
  -x "_plan_*" \
  -x "tmp/*" \
  -x ".ash/*" \
  > /dev/null

SOURCE_KEY="source/$(date +%Y%m%d-%H%M%S).zip"
echo "Uploading to s3://${SOURCE_BUCKET}/${SOURCE_KEY} ..."
aws s3 cp "${SOURCE_ZIP}" "s3://${SOURCE_BUCKET}/${SOURCE_KEY}" ${AWS_OPTS} --quiet
rm -rf "${TMPDIR}"

# Verify upload
if ! aws s3api head-object --bucket "${SOURCE_BUCKET}" --key "${SOURCE_KEY}" ${AWS_OPTS} > /dev/null 2>&1; then
  echo "ERROR: Upload verification failed — ${SOURCE_KEY} not found in S3."
  echo "The zip may be too large for the available disk space (CloudShell has 1GB limit)."
  exit 1
fi

# ---- CodeBuild service role ----
ROLE_NAME="${PROJECT_NAME}-role"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# Create role if it doesn't exist
# Note: get-role outputs to stdout even on success, so redirect both streams
if ! aws iam get-role --role-name "${ROLE_NAME}" ${AWS_OPTS} > /dev/null 2>&1; then
  echo "Creating CodeBuild service role: ${ROLE_NAME}"

  # Trust policy for CodeBuild
  TRUST_POLICY='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"codebuild.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

  aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_POLICY}" \
    ${AWS_OPTS} > /dev/null

  # CDK deploy needs broad permissions — AdministratorAccess for simplicity.
  # In production, scope this down to the specific services used.
  aws iam attach-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-arn "arn:aws:iam::aws:policy/AdministratorAccess" \
    ${AWS_OPTS}

  echo "Waiting for role propagation..."
  sleep 10
else
  echo "CodeBuild service role already exists: ${ROLE_NAME}"
fi

# ---- Create or update CodeBuild project ----
# AWS CLI shorthand syntax cannot embed JSON arrays in --environment,
# so we write the full JSON to a temp file and use --cli-input-json.
ENV_VARS_JSON=$(cat <<EOF
[
  {"name":"STACK_AGENT",           "value":"${STACK_AGENT}",       "type":"PLAINTEXT"},
  {"name":"STACK_WEB_UI",          "value":"${STACK_WEB_UI}",      "type":"PLAINTEXT"},
  {"name":"FEATURE_SEARCH_SLIDES", "value":"${SEARCH_SLIDES}",     "type":"PLAINTEXT"},
  {"name":"FEATURE_OBSERVABILITY", "value":"${OBSERVABILITY}",     "type":"PLAINTEXT"},
  {"name":"AUTH_OIDC_URL",         "value":"${OIDC_URL}",          "type":"PLAINTEXT"},
  {"name":"AUTH_ALLOWED_CLIENTS",  "value":"${ALLOWED_CLIENTS}",   "type":"PLAINTEXT"},
  {"name":"WAF_IPV4",              "value":"${WAF_IPV4}",          "type":"PLAINTEXT"},
  {"name":"WAF_IPV6",              "value":"${WAF_IPV6}",          "type":"PLAINTEXT"},
  {"name":"CDK_COMMAND",           "value":"${CDK_COMMAND}",       "type":"PLAINTEXT"},
  {"name":"STACK",                 "value":"${STACK}",             "type":"PLAINTEXT"}
]
EOF
)

ENVIRONMENT_JSON=$(cat <<EOF
{
  "type": "ARM_CONTAINER",
  "image": "aws/codebuild/amazonlinux-aarch64-standard:3.0",
  "computeType": "BUILD_GENERAL1_LARGE",
  "privilegedMode": true,
  "environmentVariables": ${ENV_VARS_JSON}
}
EOF
)

SOURCE_JSON="{\"type\":\"S3\",\"location\":\"${SOURCE_BUCKET}/${SOURCE_KEY}\"}"

# Check if project exists
if aws codebuild batch-get-projects --names "${PROJECT_NAME}" ${AWS_OPTS} \
    --query 'projects[0].name' --output text 2>/dev/null | grep -q "${PROJECT_NAME}"; then

  echo "Updating CodeBuild project: ${PROJECT_NAME}"
  aws codebuild update-project \
    --name "${PROJECT_NAME}" \
    --source "${SOURCE_JSON}" \
    --environment "${ENVIRONMENT_JSON}" \
    --service-role "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}" \
    ${AWS_OPTS} > /dev/null
else
  echo "Creating CodeBuild project: ${PROJECT_NAME}"
  aws codebuild create-project \
    --name "${PROJECT_NAME}" \
    --source "${SOURCE_JSON}" \
    --artifacts '{"type":"NO_ARTIFACTS"}' \
    --environment "${ENVIRONMENT_JSON}" \
    --service-role "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}" \
    --timeout-in-minutes 60 \
    ${AWS_OPTS} > /dev/null
fi

# ---- Start build ----
echo ""
echo "Starting CodeBuild..."
BUILD_ID=$(aws codebuild start-build \
  --project-name "${PROJECT_NAME}" \
  --source-type-override S3 \
  --source-location-override "${SOURCE_BUCKET}/${SOURCE_KEY}" \
  --environment-variables-override "${ENV_VARS_JSON}" \
  ${AWS_OPTS} \
  --query 'build.id' --output text)

echo "Build ID: ${BUILD_ID}"
echo ""

# ---- Tail build logs ----
# CodeBuild streams logs to CloudWatch Logs at /aws/codebuild/<project>
LOG_GROUP="/aws/codebuild/${PROJECT_NAME}"

echo "Waiting for build to start..."
sleep 5

# Poll build status and stream logs
LAST_TOKEN=""
while true; do
  # Get build status
  BUILD_STATUS=$(aws codebuild batch-get-builds \
    --ids "${BUILD_ID}" \
    ${AWS_OPTS} \
    --query 'builds[0].buildStatus' --output text)

  BUILD_PHASE=$(aws codebuild batch-get-builds \
    --ids "${BUILD_ID}" \
    ${AWS_OPTS} \
    --query 'builds[0].currentPhase' --output text)

  # Try to get log stream name
  LOG_STREAM=$(aws codebuild batch-get-builds \
    --ids "${BUILD_ID}" \
    ${AWS_OPTS} \
    --query 'builds[0].logs.streamName' --output text 2>/dev/null || echo "None")

  if [ "${LOG_STREAM}" != "None" ] && [ -n "${LOG_STREAM}" ]; then
    # Fetch new log events
    if [ -z "${LAST_TOKEN}" ]; then
      LOG_OUTPUT=$(aws logs get-log-events \
        --log-group-name "${LOG_GROUP}" \
        --log-stream-name "${LOG_STREAM}" \
        --start-from-head \
        ${AWS_OPTS} 2>/dev/null || echo '{"events":[],"nextForwardToken":""}')
    else
      LOG_OUTPUT=$(aws logs get-log-events \
        --log-group-name "${LOG_GROUP}" \
        --log-stream-name "${LOG_STREAM}" \
        --next-token "${LAST_TOKEN}" \
        ${AWS_OPTS} 2>/dev/null || echo '{"events":[],"nextForwardToken":""}')
    fi

    # Print new log messages
    echo "${LOG_OUTPUT}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for event in data.get('events', []):
    print(event.get('message', ''), end='')
" 2>/dev/null || true

    # Update token for next iteration
    NEW_TOKEN=$(echo "${LOG_OUTPUT}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('nextForwardToken', ''))
" 2>/dev/null || echo "")
    if [ -n "${NEW_TOKEN}" ]; then
      LAST_TOKEN="${NEW_TOKEN}"
    fi
  fi

  # Check if build is complete
  if [ "${BUILD_STATUS}" != "IN_PROGRESS" ]; then
    echo ""
    echo "========================================="
    echo "  Build ${BUILD_STATUS}"
    echo "  Phase: ${BUILD_PHASE}"
    echo "========================================="

    if [ "${BUILD_STATUS}" = "SUCCEEDED" ]; then
      echo ""
      echo "Deployment complete!"
      echo ""

      # Fetch and display key endpoints from CloudFormation outputs
      SITE_URL=$(aws cloudformation describe-stacks \
        --stack-name SdpmWebUi ${AWS_OPTS} \
        --query 'Stacks[0].Outputs[?OutputKey==`SiteUrl`].OutputValue' \
        --output text 2>/dev/null || echo "")

      USER_POOL_ID=$(aws cloudformation describe-stacks \
        --stack-name SdpmAuth ${AWS_OPTS} \
        --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
        --output text 2>/dev/null || echo "")

      if [ -n "${SITE_URL}" ]; then
        COGNITO_CONSOLE_URL="https://${REGION}.console.aws.amazon.com/cognito/v2/idp/user-pools/${USER_POOL_ID}/users?region=${REGION}"

        echo "========================================="
        echo "  CloudFront URL      : ${SITE_URL}"
        echo "  Cognito User Pool   : ${COGNITO_CONSOLE_URL}"
        echo "========================================="
        echo ""
        echo "1. Open the Cognito User Pool console to create a user"
        echo "2. Open the CloudFront URL to access the Web UI"
      else
        echo "Check CloudFormation outputs for endpoints."
      fi

      exit 0
    else
      echo ""
      echo "Build failed. Check the logs above for details."
      echo "Console: https://${REGION}.console.aws.amazon.com/codesuite/codebuild/projects/${PROJECT_NAME}/build/${BUILD_ID}"
      exit 1
    fi
  fi

  sleep 5
done
