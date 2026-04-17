[EN](../en/deploy-cloudshell.md) | [JA](../ja/deploy-cloudshell.md)

# spec-driven-presentation-maker CloudShell Deploy Guide

## About spec-driven-presentation-maker

spec-driven-presentation-maker is an open-source toolkit that adds presentation generation capabilities to AI agents. Simply connect it as an MCP (Model Context Protocol) tool to your existing AI system, and you can generate slides through conversation. Choose the layer that fits your needs — from a local CLI to a full-stack web app.

Deploy spec-driven-presentation-maker to AWS from CloudShell.
No local CDK or Docker required. CodeBuild handles all building and deployment.

## Prerequisites

- Signed in to the AWS Management Console
- **AdministratorAccess** or equivalent permissions in the target account (for first deployment)
- CloudShell open in the target deployment region

## Steps

### 1. Clone the Repository in CloudShell

Open CloudShell in the AWS Console and clone the repository.

```bash
cd ~
git clone https://github.com/aws-samples/sample-spec-driven-presentation-maker.git
cd sample-spec-driven-presentation-maker
```

> **💡 Tip:** CloudShell's home directory (1 GB) persists across sessions. For subsequent deployments, run `cd ~/sample-spec-driven-presentation-maker && git pull` to update.

### 2. Run deploy.sh

```bash
chmod +x scripts/deploy.sh
```

Choose options based on your use case.

**Layer 4 (Full Stack: Agent + Web UI) — Default:**

> **🌐 Want to try it in your browser right away?** Layer 4 deploys a chat-based Web UI. After deployment, [create a Cognito user](#creating-a-cognito-user-layer-4) and you can start generating slides from your browser immediately.

```bash
./scripts/deploy.sh --region us-east-1
```

**Layer 3 (MCP Server only):**

```bash
./scripts/deploy.sh --region us-east-1 --layer3
```

**Enable Bedrock Model Invocation Logging:**

```bash
./scripts/deploy.sh --region us-east-1 --observability
```

> **Note:** `--observability` configures Bedrock Model Invocation Logging (MIL) at the account/region level. If MIL is already configured, the script will display a warning and automatically skip the MIL setup to preserve the existing configuration.

**With an external IdP:**

```bash
./scripts/deploy.sh --region us-east-1 \
  --oidc-url "https://your-idp.example.com/.well-known/openid-configuration" \
  --allowed-clients "client-id-1,client-id-2"
```

**With WAF IP address restriction:**

```bash
./scripts/deploy.sh --region us-east-1 --waf-ipv4 "203.0.113.0/24,198.51.100.0/24"
```

**Using `infra/config.yaml`:**

If `infra/config.yaml` exists, `deploy.sh` loads it as defaults. CLI arguments override config file values. This is useful for persisting settings across deployments without repeating CLI flags.

```bash
cp infra/config.example.yaml infra/config.yaml
# Edit config.yaml to set stacks, features, WAF, etc.
./scripts/deploy.sh --region us-east-1
```

**Destroy all stacks:**

```bash
./scripts/deploy.sh --region us-east-1 --destroy
```

### 3. Monitor Deployment Progress

The script streams CodeBuild logs in real time.
Even if your CloudShell session times out, the CodeBuild build continues on the AWS side.

If your session disconnects, check the results here:

- **CodeBuild Console**: Build history for project `sdpm-deploy`
- **CloudFormation Console**: Stack status and Outputs

### 4. Post-Deployment Verification

When the build shows `SUCCEEDED`, CloudFormation Outputs appear at the end of the CodeBuild logs.
If you missed them, check the CloudFormation console.

#### Finding Endpoint URLs

1. Open the [CloudFormation Console](https://console.aws.amazon.com/cloudformation/)
2. Select the deployment region

**Layer 3 (MCP Server only):**

| Stack | Output Key | Description |
|---|---|---|
| `SdpmRuntime` | `RuntimeArn` | MCP Server Runtime ARN |
| `SdpmRuntime` | `EndpointId` | Runtime Endpoint ID |

**Layer 4 (Full Stack):**

| Stack | Output Key | Description |
|---|---|---|
| `SdpmAuth` | `UserPoolId` | Cognito User Pool ID |
| `SdpmAuth` | `UserPoolClientId` | Cognito App Client ID |
| `SdpmRuntime` | `RuntimeArn` | MCP Server Runtime ARN |
| `SdpmAgent` | `AgentRuntimeArn` | Agent Runtime ARN |
| `SdpmWebUi` | `SiteUrl` | Web UI CloudFront URL |
| `SdpmWebUi` | `ApiUrl` | REST API URL |

#### Creating a Cognito User (Layer 4)

The default Cognito User Pool has no users, so you need to create one manually.

1. Open the [Cognito Console](https://console.aws.amazon.com/cognito/)
2. Select **sdpm-users** from the User Pool list
3. Go to the **Users** tab → Click **Create user**
4. Enter the following:
   - **Email address**: Email for login
   - **Temporary password**: Initial password (8+ characters, including uppercase and numbers)
   - Check **Mark email address as verified**
5. Click **Create user**

#### Signing in to the Web UI

1. Open the `SiteUrl` from the `SdpmWebUi` stack Outputs in your browser
2. Sign in with the email and temporary password you created
3. You'll be prompted to change your password on first login
4. After signing in, the chat interface appears

#### Creating a User via CLI

You can also create a user directly from CloudShell.

```bash
REGION="us-east-1"
EMAIL="user@example.com"
TEMP_PASSWORD="<YOUR_TEMPORARY_PASSWORD>"  # 8+ chars, uppercase + number required

USER_POOL_ID=$(aws cloudformation describe-stacks \
  --stack-name SdpmAuth \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text --region "$REGION")

aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "$EMAIL" \
  --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true \
  --temporary-password "$TEMP_PASSWORD" \
  --region "$REGION"

SITE_URL=$(aws cloudformation describe-stacks \
  --stack-name SdpmWebUi \
  --query 'Stacks[0].Outputs[?OutputKey==`SiteUrl`].OutputValue' \
  --output text --region "$REGION")

echo ""
echo "========================================="
echo "  User created"
echo "========================================="
echo "  URL:      $SITE_URL"
echo "  Email:    $EMAIL"
echo "  Password: $TEMP_PASSWORD (change on first login)"
echo "========================================="
echo ""
echo "Open the URL above to sign in."
```

## Options Reference

| Option | Description | Default |
|---|---|---|
| `--region REGION` | Deployment region | `us-east-1` |
| `--profile PROFILE` | AWS CLI profile | — |
| `--layer3` | Layer 3 only (MCP Server) | — |
| `--layer4` | Layer 4 full stack | Default |
| `--search` | Enable semantic slide search | Disabled |
| `--observability` | Enable Bedrock Model Invocation Logging | Disabled |
| `--oidc-url URL` | External IdP OIDC Discovery URL | — |
| `--allowed-clients IDS` | Comma-separated JWT allowed client IDs | — |
| `--waf-ipv4 CIDRS` | Comma-separated IPv4 CIDR ranges for WAF | — |
| `--waf-ipv6 CIDRS` | Comma-separated IPv6 CIDR ranges for WAF | — |
| `--destroy` | Destroy all stacks | — |

## Troubleshooting

**CodeBuild times out**

The default timeout is 60 minutes. Initial deployments may take longer due to ECR image builds. Re-running will be faster thanks to Docker layer caching.

**Permission errors**

`deploy.sh` attaches `AdministratorAccess` to the CodeBuild service role. If you lack permissions to create IAM roles, ask an administrator to pre-create the role `sdpm-deploy-role`.

**CloudShell storage is full**

CloudShell's home directory is 1 GB. Delete unnecessary files.

```bash
# To re-clone from scratch
rm -rf ~/sample-spec-driven-presentation-maker
```

**--observability warns "already configured"**

Bedrock Model Invocation Logging allows only one configuration per account/region. If an existing configuration is found, `deploy.sh` will display a warning with the existing log group name and automatically skip the MIL setup. The deployment continues with observability disabled to preserve the existing configuration. To use SDPM's observability, first remove the existing MIL configuration manually, then re-run with `--observability`.

## Estimated Monthly Cost

> **Estimated as of April 2026.** AWS service pricing is subject to change. Always refer to the official pricing pages for the latest rates: [Amazon Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/), [AgentCore Pricing](https://aws.amazon.com/bedrock/agentcore/pricing/), [S3](https://aws.amazon.com/s3/pricing/), [DynamoDB](https://aws.amazon.com/dynamodb/pricing/).

Estimates for Layer 4 full stack (us-east-1). Assumes a team of ~10 users generating ~20 decks per month.

### Fixed Costs (Always Running)

| Resource | Est. Monthly |
|---|---|
| CloudFront | ~$1 |
| Cognito User Pool | $0 |
| API Gateway REST + Lambda (API) | ~$1 |
| S3 (3 buckets) | ~$1 |
| DynamoDB On-Demand | ~$1 |
| ECR (2 images) | ~$1 |
| CloudWatch Logs | ~$1 |

### Variable Costs (Usage-Dependent)

| Resource | Est. for 20 Decks/Month |
|---|---|
| AgentCore Runtime (MCP Server + Agent) | ~$5-10 |
| Bedrock Claude Sonnet 4.6 (Agent LLM) | ~$80-130 |
| AgentCore Code Interpreter | ~$1-3 |
| AgentCore Memory | ~$1 |

### Total

**~$95–145/month** (varies with usage)

### Cost Reduction Tips

| Method | Savings | Notes |
|---|---|---|
| Prompt caching | LLM cost up to 80% reduction | Enabled by default for supported models |
| Don't use `--search` (default) | No KB + S3 Vectors cost | Skip if semantic search isn't needed |
| Don't use `--observability` (default) | No CloudWatch Logs cost | Skip if MIL logging isn't needed |

## Related Documents

- [Getting Started](getting-started.md) — Setup instructions for Layer 1–4 (including local CDK deployment)
- [Architecture](architecture.md) — 4-layer design, data flow, auth model, MCP tool reference
- [Custom Templates](custom-template.md) — Adding templates and assets
- [Connecting Agents](add-to-gateway.md) — AgentCore Gateway connection
- [Teams & Slack Integration](teams-slack-integration.md) — Chat platform integration
