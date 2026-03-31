[EN](../en/getting-started.md) | [JA](../ja/getting-started.md)

# Getting Started

Step-by-step instructions for setting up spec-driven-presentation-maker, from local usage to AWS deployment.

## Prerequisites

Common to all layers:

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager

Additional requirements for Layer 3–4 (AWS deployment):

- AWS Account ([CDK bootstrapped](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html): `cdk bootstrap aws://ACCOUNT_ID/REGION`)
- Node.js 18+
- Docker or [Finch](https://github.com/runfinch/finch) (for container builds)
- AWS CLI with appropriate credentials configured

---

## Layer 1: Kiro CLI Skill

The simplest way to use spec-driven-presentation-maker. Copy the `skill/` directory to your Kiro CLI skills directory.

```bash
# Install dependencies
cd skill
uv sync

# Download icons (optional, recommended)
uv run python3 scripts/download_aws_icons.py
uv run python3 scripts/download_material_icons.py

# Verify
uv run python3 scripts/pptx_builder.py examples
```

The engine, references (design patterns, workflows, guides), sample templates (dark/light), and SKILL.md are all included.

---

## Layer 2: Local MCP Server

Connect spec-driven-presentation-maker to any MCP-compatible client. No AWS account required.

### Start the Server

```bash
cd mcp-local
uv sync
uv run python server.py
```

### Configure Your MCP Client

Add to your client's MCP configuration file (`claude_desktop_config.json`, `.vscode/mcp.json`, etc.):

```json
{
  "mcpServers": {
    "spec-driven-presentation-maker": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/mcp-local", "python", "server.py"]
    }
  }
}
```

### Verify

Ask your agent to "create a presentation." The following workflow runs automatically:

1. Reads workflow files via MCP Server Instructions
2. Interviews you about topic, audience, and purpose
3. Designs briefing → outline → art direction, persisted to `specs/`
4. Builds slides one by one
5. Generates PPTX and shows a preview

For the full tool list, see [Architecture — MCP Tool Reference](architecture.md#mcp-tool-reference).

---

## Layer 3: Remote MCP Server (AWS)

Deploy spec-driven-presentation-maker as a remote MCP server on Amazon Bedrock AgentCore Runtime.

> **💡 Easy Deploy:** You can also deploy from CloudShell with a single command — no local CDK or Docker required.
> See [CloudShell Deploy Guide](deploy-cloudshell.md).

### Configuration

```bash
cd infra
npm install
cp config.example.yaml config.yaml
```

Edit `config.yaml` to select which stacks to deploy.

#### Layer 3 — MCP Server Only (Minimum)

```yaml
stacks:
  data: true           # Required — DynamoDB + S3
  runtime: true        # Required — AgentCore Runtime MCP Server
  pngWorker: true      # Optional — PPTX→PNG conversion (Fargate + SQS)
  agent: false
  webUi: false

features:
  searchSlides: false   # Semantic slide search (requires Bedrock Knowledge Base)
```

### Deploy

```bash
# With Docker Desktop
npx cdk deploy --all

# With Finch (no Docker Desktop)
CDK_DOCKER=finch npx cdk deploy --all

# Non-interactive (CI/CD)
CDK_DOCKER=finch npx cdk deploy --all --require-approval never
```

Deployment takes approximately 15–30 minutes.

#### Changing the Model ID

The default model is `global.anthropic.claude-sonnet-4-6`. To use a different model, edit `infra/config.yaml`:

```yaml
model:
  modelId: "global.anthropic.claude-opus-4-6-v1"
```

Or override at deploy time:

```bash
npx cdk deploy --all --context modelId=global.anthropic.claude-opus-4-6-v1
```

### Deployed Stacks (Layer 3)

| Stack | Resources |
|-------|-----------|
| SdpmData | Amazon DynamoDB table, S3 buckets (pptx + resources), reference files deployed to S3 |
| SdpmRuntime | Amazon Bedrock AgentCore Runtime endpoint, ECR repository + Docker image, Amazon Cognito M2M auth |
| SdpmPngWorker | AWS Fargate task definition, SQS queue, ECS cluster |

### Template Registration

CDK deploys template files to S3, but Amazon DynamoDB registration is required for `list_templates` to work.
See [Custom Templates — Registering Templates (Layer 3)](custom-template.md#layer-3-remote-mcp) for details.

### Verify Deployment

#### Get an OAuth Token

```bash
TOKEN=$(curl -s -X POST \
  "https://<CognitoDomain>.auth.<region>.amazoncognito.com/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "<M2MClientId>:<M2MClientSecret>" \
  -d "grant_type=client_credentials&scope=sdpm/invoke" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Find `CognitoDomain`, `M2MClientId`, and `M2MClientSecret` in the CDK outputs.

#### Call tools/list

```bash
ENCODED_ARN=$(python3 -c "import urllib.parse; print(urllib.parse.quote('<RuntimeArn>', safe=''))")

curl -X POST \
  "https://bedrock-agentcore.<region>.amazonaws.com/runtimes/${ENCODED_ARN}/invocations?qualifier=DEFAULT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":1}'
```

A tool list in the response confirms success.

---

## Layer 4: Full Stack (AWS)

> **💡 Easy Deploy:** Layer 4 can also be deployed from CloudShell with a single command. Just run `./scripts/deploy.sh --region us-east-1`.
> See [CloudShell Deploy Guide](deploy-cloudshell.md).

Enable `agent` and `webUi` in `config.yaml` to add:

- Strands Agent on Amazon Bedrock AgentCore Runtime
- React Web UI (chat interface + deck preview)
- JWT Bearer authentication (Amazon Cognito default, any OIDC IdP supported)

### Configuration

```yaml
stacks:
  data: true
  runtime: true
  pngWorker: true
  agent: true          # Strands Agent on AgentCore Runtime
  webUi: true          # React Web UI (S3 + CloudFront)

features:
  searchSlides: false
```

```bash
npx cdk deploy --all
```

### Deployed Stacks (Layer 4 additions)

| Stack | Resources |
|-------|-----------|
| SdpmAuth | Amazon Cognito User Pool, hosted UI |
| SdpmAgent | Strands Agent on Amazon Bedrock AgentCore Runtime, ECR image |
| SdpmWebUi | S3 bucket, Amazon CloudFront distribution, Amazon API Gateway, Lambda |

### Authentication Options

#### Default: Amazon Cognito User Pool

When `agent` or `webUi` is enabled, CDK automatically creates a Amazon Cognito User Pool with hosted UI. Users sign in via the web UI, and the JWT is propagated through the stack.

For authentication and authorization model details, see [Architecture — Authentication and Authorization Model](architecture.md#authentication-and-authorization-model).

#### External OIDC IdP

To use your own IdP (Entra ID, Auth0, Okta, etc.):

1. Skip the AuthStack or configure your IdP as a Amazon Cognito federation source
2. Set `oidcDiscoveryUrl` and `allowedClients` in `config.yaml`
3. The Runtime's `customJwtAuthorizer` validates JWTs from any OIDC-compliant issuer

### Updating the Web UI

To update the Web UI without a full CDK deployment:

```bash
cd web-ui && npm run build && cd ..
bash scripts/deploy_webui.sh
```

`aws-exports.json` (auth info, API endpoints, etc.) is managed by a CDK Custom Resource.
If you change the stack configuration, run `npx cdk deploy SdpmWebUi`.

---

## Optional Features

### Semantic Slide Search

Set `features.searchSlides: true` to create a Amazon Bedrock Knowledge Base for cross-deck semantic search.

As a prerequisite, enable access to the Amazon Titan Text Embeddings V2 model in your deployment region (Amazon Bedrock console → Model access).

### Custom Templates and Assets

For adding custom .pptx templates and icons, see [Custom Templates and Assets](custom-template.md).

---

## Important Notes

### Cost

- PngWorkerStack creates a VPC with NAT Gateway (hourly charges apply)
- Amazon Bedrock AgentCore Runtime runs 2 containers (Agent + MCP Server)
- Enabling `features.searchSlides` creates an additional Amazon Bedrock Knowledge Base
- Delete resources with `npx cdk destroy --all` when done with development/testing

### Data Retention

DataStack's Amazon DynamoDB table and S3 buckets have `RemovalPolicy.RETAIN`. Data is not deleted by `cdk destroy` — manual deletion is required.

---

## Troubleshooting

### Docker build fails with Finch

```bash
export CDK_DOCKER=finch
```

### ECR permission error during deploy

Amazon Bedrock AgentCore Runtime may encounter permission errors when pulling ECR images. This typically resolves on re-deploy:

```bash
npx cdk deploy --all
```

### Templates not showing in list_templates

Run `upload_template.py` after CDK deployment. CDK deploys .pptx files to S3 but does not create Amazon DynamoDB records.

### .dockerignore missing

If Docker builds are extremely slow or fail with disk space errors, ensure `.dockerignore` exists at the repository root and includes `infra/cdk.out/`.

### Agent not following the workflow

`server_instructions` auto-injection requires Strands SDK v1.30.0+. Verify that `strands-agents>=1.30.0` is installed.

### White screen at Amazon CloudFront URL

The deployment may have run without `web-ui/build` present:

```bash
cd web-ui && npm run build && cd ..
bash scripts/deploy_webui.sh
```

---

## Related Documents

- [Architecture](architecture.md) — 4-layer design, data flow, auth model
- [Custom Templates](custom-template.md) — Adding templates and assets
- [Connecting Agents](add-to-gateway.md) — Amazon Bedrock AgentCore Gateway connection
