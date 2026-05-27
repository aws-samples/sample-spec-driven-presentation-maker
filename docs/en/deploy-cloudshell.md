[EN](../en/deploy-cloudshell.md) | [JA](../ja/deploy-cloudshell.md)

# spec-driven-presentation-maker Deploy Guide

## About spec-driven-presentation-maker

spec-driven-presentation-maker is an open-source toolkit that adds presentation generation capabilities to AI agents. Simply connect it as an MCP (Model Context Protocol) tool to your existing AI system, and you can generate slides through conversation. Choose the layer that fits your needs — from a local CLI to a full-stack web app.

---

## One-Click Deploy (Recommended)

Deploy SDPM to your AWS account with a single click. No local tools or CLI setup required — just sign in to the AWS Console, click the button, fill in the parameters, and wait for completion.

### Prerequisites

- Signed in to the [AWS Management Console](https://console.aws.amazon.com/)
- **AdministratorAccess** or equivalent permissions in the target account

### Step 1: Click the Launch Stack button

Choose the region closest to you:

| Region | Launch |
|--------|--------|
| Tokyo (ap-northeast-1) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://ap-northeast-1.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |
| N. Virginia (us-east-1) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://us-east-1.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |
| Oregon (us-west-2) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://us-west-2.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |

### Step 2: Fill in parameters

The CloudFormation console will display a parameter form. Fill in the following:

| Parameter | Description | Default |
|-----------|-------------|---------|
| **NotificationEmailAddress** | Email address to receive deployment start/completion notifications | *(required)* |
| **DeploymentLayer** | `layer3` = MCP Server only, `layer4` = Full stack (Agent + Web UI) | `layer4` |
| **ModelId** | Bedrock model ID for the Agent (e.g. `global.anthropic.claude-sonnet-4-6`) | `global.anthropic.claude-sonnet-4-6` |
| **EnableInvocationLogging** | Enable Bedrock Model Invocation Logging (`true` / `false`) | `false` |
| **AllowedIpV4AddressRanges** | Comma-separated IPv4 CIDR ranges for WAF IP restriction (leave empty for no restriction) | *(empty)* |
| **AllowedIpV6AddressRanges** | Comma-separated IPv6 CIDR ranges for WAF IP restriction (leave empty for no restriction) | *(empty)* |

> **💡 Tip:** We recommend specifying `AllowedIpV4AddressRanges` to restrict access. You can check your current public IP at [https://checkip.amazonaws.com/](https://checkip.amazonaws.com/). If you don't restrict IPs, the app is publicly accessible but login (Cognito) is still required.

### Step 3: Deploy

1. Check **"I acknowledge that AWS CloudFormation might create IAM resources with custom names."**
2. Click **Create stack**
3. Wait for the stack to complete (approximately 30–40 minutes). You'll receive an email notification when done.

### Step 4: Sign in

When deployment completes, a temporary password is sent to the **NotificationEmailAddress** you specified. Open the Web UI URL (included in the notification email or found in CloudFormation Outputs `SdpmWebUi` → `SiteUrl`), sign in with that email and temporary password, and set a new password on first login. That's it — you can start generating slides immediately.

---

## Deploy using CloudShell

Use this method if you need to **customize deployment options** beyond the one-click parameters (e.g., external IdP, config.yaml overrides, or specific deploy.sh flags).

Because CodeBuild runs the build and deployment, you don't need a local CDK or Docker install, and the same steps work in either of these environments:

- **AWS CloudShell** (fully browser-based)
- Local **Linux / macOS / WSL** (requires `bash` and the `aws` CLI)

> Windows has no native Bash, so use **CloudShell** or **WSL**.

> **📌 Note:** Deployment settings can be persisted in `infra/config.yaml`, making re-deploys more consistent. Direct local CDK deployment (`npx cdk deploy`) is reserved for development and debugging workflows.

### Prerequisites

- Signed in to the AWS Management Console
- **AdministratorAccess** or equivalent permissions in the target account (for first deployment)
- One of the following working environments
    - AWS CloudShell (opened in the target deployment region)
    - Local Linux / macOS / WSL with `bash`, `git`, the `aws` CLI, and valid AWS credentials

### Quick Start

In CloudShell, open CloudShell from the AWS Console. Locally, use any shell. Copy-paste the block below to deploy **Layer 4 (Agent + Web UI, default)** to `us-east-1`.

```bash
cd ~
git clone https://github.com/aws-samples/sample-spec-driven-presentation-maker.git
cd sample-spec-driven-presentation-maker
chmod +x scripts/deploy.sh
./scripts/deploy.sh --region us-east-1
```

> **💡 Tip:** CloudShell's home directory (1 GB) persists across sessions. For subsequent deployments, run `cd ~/sample-spec-driven-presentation-maker && git pull && ./scripts/deploy.sh --region us-east-1` to update and redeploy.

> **📝 Note:** Unlike One-Click Deploy, this method does not automatically create a Cognito user. After deployment, [create a Cognito user manually](#creating-a-cognito-user-layer-4) to sign in to the Web UI.

### Alternative Configurations

For anything other than the default (Layer 4, `us-east-1`), swap the `./scripts/deploy.sh ...` line in the Quick Start with one of the following.

**Layer 3 (MCP Server only):**

```bash
./scripts/deploy.sh --region us-east-1 --layer3
```

**Enable Bedrock Model Invocation Logging:**

```bash
./scripts/deploy.sh --region us-east-1 --enable-invocation-logging
```

> **Note:** `--enable-invocation-logging` configures Bedrock Model Invocation Logging (MIL) at the account/region level. If MIL is already configured, the script will display a warning and automatically skip the MIL setup to preserve the existing configuration.

**With an external IdP:**

```bash
./scripts/deploy.sh --region us-east-1 \
  --oidc-url "https://your-idp.example.com/.well-known/openid-configuration" \
  --allowed-clients "client-id-1,client-id-2"
```

**With WAF IP address restriction:**

```bash
# IPv4 only (⚠️ this blocks all IPv6 access — see note below)
./scripts/deploy.sh --region us-east-1 --waf-ipv4 "203.0.113.0/24,198.51.100.0/24"

# IPv4 + IPv6 (recommended for dual-stack networks)
./scripts/deploy.sh --region us-east-1 \
  --waf-ipv4 "203.0.113.0/24" \
  --waf-ipv6 "2001:db8::/32"
```

> **⚠️ IPv6 Note:** If you specify only `--waf-ipv4` without `--waf-ipv6`, all IPv6 access is blocked. Modern browsers often prefer IPv6, which can cause the Web UI to appear stuck. Always specify both if your network uses dual-stack.

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

## Monitor Deployment Progress

The script streams CodeBuild logs in real time.
Even if your CloudShell session times out, the CodeBuild build continues on the AWS side.

If your session disconnects, check the results here:

- **CodeBuild Console**: Build history for project `sdpm-deploy`
- **CloudFormation Console**: Stack status and Outputs

## Post-Deployment Verification

When the build shows `SUCCEEDED`, CloudFormation Outputs appear at the end of the CodeBuild logs.
If you missed them, check the CloudFormation console.

### Finding Endpoint URLs

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

### Creating a Cognito User (Layer 4)

The default Cognito User Pool has no users, so you need to create one manually.

1. Open the [Cognito Console](https://console.aws.amazon.com/cognito/)
2. Select **sdpm-users** from the User Pool list
3. Go to the **Users** tab → Click **Create user**
4. Enter the following:
   - **Email address**: Email for login
   - **Temporary password**: Initial password (8+ characters, including uppercase and numbers)
   - Check **Mark email address as verified**
5. Click **Create user**

### Signing in to the Web UI

1. Open the `SiteUrl` from the `SdpmWebUi` stack Outputs in your browser
2. Sign in with the email and temporary password you created
3. You'll be prompted to change your password on first login
4. After signing in, the chat interface appears

### Creating a User via CLI

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
| `--enable-invocation-logging` | Enable Bedrock Model Invocation Logging | Disabled |
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

**--enable-invocation-logging warns "already configured"**

Bedrock Model Invocation Logging allows only one configuration per account/region. If an existing configuration is found, `deploy.sh` will display a warning with the existing log group name and automatically skip the MIL setup. The deployment continues with Invocation Logging disabled to preserve the existing configuration. To use SDPM's Invocation Logging, first remove the existing MIL configuration manually, then re-run with `--enable-invocation-logging`.

## Estimated Monthly Cost

See [Cost Estimates](cost.md) for a full breakdown and optimization tips.

## Related Documents

- [Getting Started](getting-started.md) — Setup instructions for Layer 1–4 (including local CDK deployment)
- [Architecture](architecture.md) — 4-layer design, data flow, auth model, MCP tool reference
- [Custom Templates](custom-template.md) — Adding templates and assets
- [Connecting Agents](add-to-gateway.md) — MCP client connection guide
- [Teams & Slack Integration](teams-slack-integration.md) — Chat platform integration
