[EN](../en/uninstall.md) | [JA](../ja/uninstall.md)

# Uninstall Guide

How to remove SDPM resources from your AWS account.

## Overview

SDPM deploys multiple CloudFormation stacks. Because of their dependencies, manual deletion through the CloudFormation console is tedious. We recommend using [go-to-k/delstack](https://github.com/go-to-k/delstack) for a one-shot, dependency-aware deletion.

Stack list (deleted in reverse dependency order):

- `SdpmWebUi` (Layer 4)
- `SdpmAgent` (Layer 4)
- `SdpmRuntime`
- `SdpmData`
- `SdpmAuth` (if using the default Cognito setup)
- `SdpmCloudFrontWaf` (only when WAF is enabled, us-east-1 only)

## Recommended: Use delstack

[go-to-k/delstack](https://github.com/go-to-k/delstack) deletes CloudFormation stacks in the correct dependency order while force-cleaning up stubborn resources (versioned S3 buckets, ECR repositories, etc.).

### Install

macOS / Linux:

```bash
brew install go-to-k/tap/delstack
```

With Go:

```bash
go install github.com/go-to-k/delstack@latest
```

Other installation methods are documented in [delstack's README](https://github.com/go-to-k/delstack#install).

### Delete command

Run the following in your deployment region (e.g. `us-east-1`).

```bash
# Delete Layer 4 full stack
delstack --region us-east-1 \
  -s SdpmWebUi \
  -s SdpmAgent \
  -s SdpmRuntime \
  -s SdpmData \
  -s SdpmAuth

# Add this if WAF was enabled (always us-east-1)
delstack --region us-east-1 -s SdpmCloudFrontWaf
```

For a Layer 3 deployment, omit `SdpmWebUi` and `SdpmAgent`.

### Why delstack

- **Automatic dependency resolution**: deletes stacks in the correct order.
- **Force-delete S3 buckets**: empties versioned buckets before deletion.
- **Force-delete ECR repositories**: handles repos that would otherwise fail with `DELETE_FAILED`.
- **Interactive confirmation**: shows the list of resources and asks for `yes` before deleting.

## From AWS CloudShell

AWS CloudShell ships with Go pre-installed, so you can install and run delstack there:

```bash
# Install in CloudShell
go install github.com/go-to-k/delstack@latest

# Put it on PATH
export PATH=$PATH:$(go env GOPATH)/bin

# Delete
delstack --region us-east-1 -s SdpmWebUi -s SdpmAgent -s SdpmRuntime -s SdpmData -s SdpmAuth
```

## Using CDK (local environments only)

If you have a local CDK environment, you can also use:

```bash
cd infra
npx cdk destroy --all
```

This often fails when S3 buckets or ECR repositories contain leftover resources, so delstack is still recommended.

## Manual deletion via CloudFormation console

If you prefer the GUI, delete the stacks in **reverse** order:

1. `SdpmWebUi`
2. `SdpmAgent`
3. `SdpmRuntime`
4. `SdpmData`
5. `SdpmAuth`
6. `SdpmCloudFrontWaf` (check the us-east-1 region)

If a stack fails with `DELETE_FAILED` because of leftover S3 buckets or ECR repositories, empty those resources manually and retry.

## Post-deletion verification

Confirm the following resources are gone:

- CloudFormation: the stacks listed above
- S3: buckets with `sdpm-*` or `cdk-*` prefix
- DynamoDB: `sdpm-*` tables
- ECR: `sdpm-*` repositories
- SSM Parameter Store: `/sdpm/*`
- CloudWatch Logs: `/aws/lambda/sdpm-*`, `/aws/bedrock/*`

## Notes

- **Data is not recoverable**. Export your decks and slides from S3 first if you want to keep them.
- **The CDK bootstrap stack (`CDKToolkit`)** is intentionally excluded because it may be shared with other CDK projects. Delete it manually only if you want a full cleanup.
- **Bedrock Model Invocation Logging** (enabled via `--enable-invocation-logging`) is an account/region-level setting and is cleaned up when `SdpmData` is deleted.
