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

> **Note:** `--observability` configures Bedrock Model Invocation Logging (MIL) at the account/region level. If MIL is already configured, the script will warn about overwriting the existing configuration and ask for confirmation.

**With an external IdP:**

```bash
./scripts/deploy.sh --region us-east-1 \
  --oidc-url "https://your-idp.example.com/.well-known/openid-configuration" \
  --allowed-clients "client-id-1,client-id-2"
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

Bedrock Model Invocation Logging allows only one configuration per account/region. If an existing configuration is found, `deploy.sh` will prompt for confirmation before overwriting. The existing log destination (CloudWatch Logs group name) is displayed — verify it's safe to overwrite before entering `y`. Once overwritten, the previous MIL configuration cannot be restored.

## Estimated Monthly Cost

Estimates for Layer 4 full stack (us-east-1). Assumes a team of ~10 users generating ~100 decks per month.

### Fixed Costs (Always Running)

| Resource | Configuration | Est. Monthly |
|---|---|---|
| CloudFront | ~10GB transfer/month | ~$1 |
| Cognito User Pool | Free up to 50,000 MAU | $0 |
| API Gateway REST | A few thousand requests/month | ~$0.5 |
| Lambda (API) | A few thousand requests/month | ~$0.5 |
| S3 (3 buckets) | A few GB storage + requests | ~$1 |
| DynamoDB On-Demand | Low read/write volume | ~$1 |
| ECR (2 images) | A few GB storage | ~$1 |
| CloudWatch Logs | Log storage | ~$1 |

### Variable Costs (Usage-Dependent)

| Resource | Unit Price | Est. for 100 Decks/Month |
|---|---|---|
| AgentCore Runtime (MCP Server) | Container runtime charges | ~$10-20 |
| AgentCore Runtime (Agent) | Container runtime charges | ~$10-20 |
| Bedrock Claude Opus 4.6 (Agent LLM) | Input $15 / Output $75 per 1M tokens | ~$30-80 |
| AgentCore Code Interpreter | Session charges | ~$5-10 |
| AgentCore Memory | Event storage | ~$1 |

### Total

**~$60–140/month** (varies with usage)

### Cost Reduction Tips

| Method | Savings | Notes |
|---|---|---|
| Switch LLM to Sonnet 4.6 | LLM cost 1/5–1/10 | Default since v1.0. Use `config.yaml` to switch models |
| Don't use `--search` (default) | No KB + S3 Vectors cost | Skip if semantic search isn't needed |
| Don't use `--observability` (default) | No CloudWatch Logs cost | Skip if MIL logging isn't needed |

> Estimates based on published pricing as of March 2026. See [AWS Pricing](https://aws.amazon.com/pricing/) for current rates.

## Related Documents

- [Getting Started](getting-started.md) — Setup instructions for Layer 1–4 (including local CDK deployment)
- [Architecture](architecture.md) — 4-layer design, data flow, auth model, MCP tool reference
- [Custom Templates](custom-template.md) — Adding templates and assets
- [Connecting Agents](add-to-gateway.md) — AgentCore Gateway connection
- [Teams & Slack Integration](teams-slack-integration.md) — Chat platform integration
