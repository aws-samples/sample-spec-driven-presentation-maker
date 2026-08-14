[EN](../en/getting-started.md) | [JA](../ja/getting-started.md)

# Getting Started

Step-by-step instructions for setting up spec-driven-presentation-maker, from local usage to AWS deployment.

> **🤖 You don't need to read this page manually.** This repo ships with [`AGENTS.md`](../../AGENTS.md). Just tell your coding agent (Claude Code, Codex CLI, Cursor, Kiro, GitHub Copilot in VS Code, etc.) what you want — for example, "Set up this repo," "Deploy it to AWS," or "Wire it up so I can use it from Claude Desktop as Layer 2." The agent will read AGENTS.md, pick the right layer, and run the right commands for you.

> **🚀 Deploying to AWS only?** Use the [One-Click Deploy](deploy-cloudshell.md#one-click-deploy-recommended) — just sign in to the AWS Console, click the Launch Stack button, and fill in the parameters. For advanced customization (external IdP, WAF, config.yaml), you can also use [CloudShell deploy](deploy-cloudshell.md#deploy-using-cloudshell). This page covers Layer 1–2 local usage and direct-CDK workflows for development and debugging.

## Which Layer Do I Need?

- **Layer 1** — Use from a SKILL.md-compatible coding agent (Claude Code, Codex CLI, Cursor, Kiro, GitHub Copilot in VS Code, etc.). Python only, no MCP or AWS.
- **Layer 2** — Use from a local MCP client (Claude Desktop, Claude Cowork, etc.). Local stdio MCP, no AWS.
- **Layer 3** — Use from a remote-only MCP client (Claude.ai web, etc. — clients that cannot spawn local processes). AWS deployment required.
- **Layer 4** — Use the included browser Web UI. AWS full-stack deployment.

## Prerequisites

Common to all layers:

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager

Additional requirements for **deploying Layer 3–4 with local CDK directly** (not needed when using the CloudShell deploy path):

- AWS Account ([CDK bootstrapped](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html): `cdk bootstrap aws://ACCOUNT_ID/REGION`)
- Node.js 18+
- Docker or [Finch](https://github.com/runfinch/finch) (for container builds)
- AWS CLI with appropriate credentials configured

---

## Layer 1: Agent Skill (no MCP)

The simplest way to use spec-driven-presentation-maker: copy or symlink the `sdpm/`
directory into your agent's skills directory. The agent calls the engine through
`scripts/pptx_builder.py` — no MCP server involved.

> **Kiro CLI users:** you probably want [Layer 2](#layer-2-local-mcp-server) instead —
> `make install-kiro` sets up the local MCP server (mode behavior included) and a
> dedicated composer agent for reliable parallel slide generation.

```bash
# Install dependencies
cd sdpm
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

### Kiro CLI — one make target (recommended)

Kiro CLI users get everything from a single target — the MCP server carries the mode
behavior, and a dedicated `sdpm-composer` agent handles parallel slide generation:

```bash
git clone https://github.com/aws-samples/sample-spec-driven-presentation-maker.git
cd sample-spec-driven-presentation-maker
make install-kiro
kiro-cli chat   # then just ask: "make slides about ..."
```

This registers the `sdpm` local MCP server in `<KIRO_HOME>/settings/mcp.json` (default
`~/.kiro`), symlinks the mode entry points into `<KIRO_HOME>/skills/` (so you can also
run `/sdpm-vibe`, `/sdpm-spec`, `/sdpm-style` or `/sdpm-translate` to pick a mode
explicitly), and generates
a composer agent at `<KIRO_HOME>/agents/sdpm-composer.json` — a thin pointer that gives
compose workers the sdpm server only, instead of cold-starting every MCP server in your
profile per worker. The behavior itself is still served by the MCP server via
`start_presentation(mode=...)`; the entry points and the composer agent only name it.
Prerequisites: [`uv`](https://docs.astral.sh/uv/) on your
`PATH`, plus **LibreOffice** and **poppler** for slide previews.

Keep the checkout where it is — the MCP server runs from it. `git pull` is enough to
update. Re-run `make install-kiro` only if you move the checkout.

Useful flags — call the script directly, since `make` does not forward arguments:

```bash
uv run python3 clients/kiro/install.py --agent NAME       # register into one agent config
uv run python3 clients/kiro/install.py --mode legacy      # skip Power auto-detection
KIRO_HOME=~/.kiro-sdpm-dev make install-kiro              # install into a separate profile
```

If another checkout already owns the `sdpm` MCP registration or the skill symlinks, the
installer stops and lists what it found instead of repointing a working setup. Either
install into a separate `KIRO_HOME`, remove the other checkout's wiring yourself, or pass
`--replace-existing` to take it over deliberately.

### Kiro IDE — install as a Power

The repository root is an [Agent Plugins](https://agent-plugins.org) package
(`plugin.json` + `mcp.json` + `skills/`), which is the format Kiro Powers use. Install the
checkout as a Power from the Kiro IDE; Powers are global-scope and Kiro manages the
bundled MCP server itself, so nothing needs to be written into
`~/.kiro/settings/mcp.json`.

Powers and the Kiro CLI wiring above are two paths to the same package and should not both
be active. Because Powers have no project scope, keep them apart with separate profiles:
run the CLI installer under a different `KIRO_HOME` than the one your Power is installed
into. Running `make install-kiro` in a profile where the Power is already present makes
the installer remove its own legacy wiring instead of adding to it.

### Codex — install as a plugin

The checkout ships a Codex manifest (`.codex-plugin/plugin.json`), a bundled MCP server
definition (`.mcp.json`) and a repo marketplace (`.agents/plugins/marketplace.json`), so
it can be installed without hand-editing `config.toml`:

```bash
codex plugin marketplace add ./     # from inside the checkout
```

Then install `spec-driven-presentation-maker` from that marketplace in the ChatGPT desktop
app and start a new conversation. Codex copies the plugin into
`~/.codex/plugins/cache/…`, so the MCP server's Python environment is created under the
plugin's writable data directory rather than inside the checkout.

### Other MCP clients — manual setup

#### Start the Server

```bash
cd servers/local
uv sync
uv run python server.py
```

#### Configure Your MCP Client

Add to your client's MCP configuration file (`claude_desktop_config.json`, `.vscode/mcp.json`, etc.):

```json
{
  "mcpServers": {
    "spec-driven-presentation-maker": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/servers/local", "python", "server.py"]
    }
  }
}
```

#### Verify

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

> **💡 The [Recommended Deploy Guide](deploy-cloudshell.md) is the recommended path for AWS deployments.**
> `scripts/deploy.sh` runs from CloudShell and from any local Linux/macOS environment, and builds via CodeBuild — so you don't need CDK or Docker installed locally. The instructions below cover the direct local CDK workflow, mainly used for development and debugging.

### Configuration

```bash
cd infra
npm ci
cp config.example.yaml config.yaml
```

Edit `config.yaml` to select which stacks to deploy.

#### Layer 3 — MCP Server Only (Minimum)

```yaml
stacks:
  data: true           # Required — DynamoDB + S3
  runtime: true        # Required — AgentCore Runtime MCP Server
  agent: false
  webUi: false

features:
  enableInvocationLogging: false  # Bedrock Model Invocation Logging (optional)
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

> **💡 Recommended path:** Deploy Layer 4 via the [Recommended Deploy Guide](deploy-cloudshell.md) (works from CloudShell and any local Linux/macOS). Just run `./scripts/deploy.sh --region us-east-1` — no local CDK/Docker needed.

Enable `agent` and `webUi` in `config.yaml` to add:

- Strands Agent on Amazon Bedrock AgentCore Runtime
- React Web UI (chat interface + deck preview)
- JWT Bearer authentication (Amazon Cognito default, any OIDC IdP supported)

### Configuration

```yaml
stacks:
  data: true
  runtime: true
  agent: true          # Strands Agent on AgentCore Runtime
  webUi: true          # React Web UI (S3 + CloudFront)

features:
  enableInvocationLogging: false
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

### Checking Endpoints After Deployment

If the deploy script's log monitoring was interrupted, or you need to check the endpoints later, run:

```bash
bash scripts/show_endpoints.sh
```

This displays the CloudFront URL and Cognito sign-up URL from the deployed CloudFormation stacks.

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

### WAF IP Address Restriction

Set `waf.allowedIpV4AddressRanges` and/or `waf.allowedIpV6AddressRanges` in `config.yaml` to restrict access to CloudFront and API Gateway by IP address.

```yaml
waf:
  allowedIpV4AddressRanges:
    - "10.0.0.0/8"
    - "192.168.0.0/16"
  allowedIpV6AddressRanges:
    - "2001:db8::/32"
```

When configured, CDK creates:
- **SdpmCloudFrontWaf** stack in `us-east-1` (WAFv2 CLOUDFRONT scope requirement) — attached to CloudFront
- **Regional WAF** in the deploy region — attached to API Gateway

Default action is **Block** — only the listed IP ranges are allowed. When the `waf` section is omitted, no WAF resources are created.

> **⚠️ IPv6 Note:** If you specify only `allowedIpV4AddressRanges` without `allowedIpV6AddressRanges`, all IPv6 access is blocked. Modern browsers often prefer IPv6 when available, which can cause the Web UI to hang on "Loading authentication configuration..." even if your IPv4 address is allowed. Always specify both IPv4 and IPv6 ranges if your network uses dual-stack.

### Semantic Slide Search

Cross-deck semantic search is provided out of the box, backed by Amazon Bedrock Knowledge Bases and Amazon S3 Vectors. No extra configuration is needed.

### Custom Templates and Assets

For adding custom .pptx templates and icons, see [Custom Templates and Assets](custom-template.md).

---

## Important Notes

### Cost

See [Cost Estimates](cost.md) for details. Delete resources with `npx cdk destroy --all` when done with development/testing.

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
- [Connecting Agents](add-to-gateway.md) — MCP client connection guide
