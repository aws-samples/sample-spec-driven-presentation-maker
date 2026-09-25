[EN](../en/getting-started.md) | [JA](../ja/getting-started.md)

# Getting Started

Use SDPM in a browser or connect it to the AI agent you already use. Both paths run
locally without an AWS account. For the internal four-layer design, see
[Architecture](architecture.md#4-layer-architecture).

## Choose how you want to use SDPM

### Use it in your browser (full experience)

The local Web UI provides chat, deck management, editable previews, and PowerPoint export.
Install it on macOS or Linux with one command:

```bash
curl -fsSL https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.sh | bash
```

The installer installs git, uv, LibreOffice, poppler, Node.js, and Kiro CLI; clones SDPM to
`${SDPM_HOME:-~/.sdpm}/checkout`; builds the local Web UI; and creates an `sdpm` launcher
and desktop shortcut. Run `sdpm` or `sdpm launch` to open
[http://localhost:3000](http://localhost:3000).

On Windows:

```powershell
irm https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.ps1 | iex
```

Windows support is verified in CI only and has not received manual Windows QA.

#### Launcher commands

| Command | Action |
|---|---|
| `sdpm` / `sdpm launch` | Start the local Web UI and open it in your browser |
| `sdpm update` | Pull `main`, update dependencies, and rebuild the Web UI |
| `sdpm check-update` | Check whether a newer revision is available |
| `sdpm doctor` | Run the repository environment checks |
| `sdpm version` | Show the installed revision |
| `sdpm path` | Print the checkout path |
| `sdpm help` | Show command help |

#### Installer options

| macOS / Linux | Windows | Effect |
|---|---|---|
| `--deps-only` | `-DepsOnly` | Install only git, uv, LibreOffice, and poppler |
| `--non-interactive` | `-NonInteractive` | Accept dependency installation prompts |
| `--skip-libreoffice` | `-SkipLibreOffice` | Skip LibreOffice checks and installation |
| `--skip-shortcut` | `-SkipShortcut` | Do not create a desktop shortcut |

Set `SDPM_HOME` to change the install root. The default is `~/.sdpm` on Unix and
`%USERPROFILE%\.sdpm` on Windows.

### Use it from the AI agent you already have

Choose your client and complete the action shown. The `uvx` options do not require a
checkout. Expect the first launch to take tens of seconds while uv builds and caches the package.

| Client | Setup |
|---|---|
| Claude Desktop | [Download `sdpm.mcpb`](https://github.com/aws-samples/sample-spec-driven-presentation-maker/releases/latest/download/sdpm.mcpb), then double-click it |
| Cursor | [![Add to Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](cursor://anysphere.cursor-deeplink/mcp/install?name=sdpm&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJnaXQraHR0cHM6Ly9naXRodWIuY29tL2F3cy1zYW1wbGVzL3NhbXBsZS1zcGVjLWRyaXZlbi1wcmVzZW50YXRpb24tbWFrZXIjc3ViZGlyZWN0b3J5PXNlcnZlcnMvbG9jYWwiLCJzZHBtLW1jcCJdfQ==) |
| Visual Studio Code | `code --add-mcp '{"name":"sdpm","command":"uvx","args":["--from","git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=servers/local","sdpm-mcp"]}'` |
| Kiro CLI | `kiro-cli mcp add --name sdpm --command uvx --args '["--from","git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=servers/local","sdpm-mcp"]' --scope global` |
| Claude Code | `/plugin marketplace add aws-samples/sample-spec-driven-presentation-maker` then `/plugin install sdpm@sdpm` |
| Codex | Run `codex plugin marketplace add ./` in the checkout, then install from the ChatGPT desktop app |

For `uvx` clients, install the system dependencies with:

```bash
curl -fsSL https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.sh | bash -s -- --deps-only
```

LibreOffice and poppler render PNG previews. PPTX generation works without them. Claude
Desktop manages its own Python runtime, and its `.mcpb` includes the official icon catalogs.

Install the AWS and Material icon catalogs for a clone-free `uvx` setup:

```bash
uvx --from "git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=servers/local" sdpm-install-assets
```

The default `uvx` command follows `main`. To force uv to refresh its cached checkout and
packages, run:

```bash
uvx --refresh --from "git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=servers/local" sdpm-install-assets --help
```

After setup, ask your agent to “make slides about …”. The agent's first call,
`start_presentation`, returns the orchestrator role document plus the styles and templates
on offer; a deck-writing sub-agent starts with `start_composing`, a style request with
`start_style`, a translation with `start_translation`. The MCP server alone is the complete
setup — skills and agent definitions are optional extras. To pick a mode explicitly, use
the server's prompts where your client shows them: `sdpm-vibe` (build from material, no
questions), `sdpm-spec` (shape the deck in dialogue first), `sdpm-style`, `sdpm-translate`
(Claude Code `/mcp__sdpm__sdpm-vibe`, VS Code `/mcp.sdpm.sdpm-vibe`, Kiro CLI `/sdpm-vibe`).

## AWS deployment

For a shared remote MCP server or hosted Web UI, use the
[One-Click Deploy](deploy-cloudshell.md#one-click-deploy-recommended). The recommended path
runs from AWS CloudShell and does not require local CDK or Docker. Direct CDK instructions
for development and debugging are under [Manual setup](#manual-setup).

## Manual setup

These paths are for contributors, advanced client configuration, or direct AWS development.
They expose implementation details that the two quick-start paths do not require.

### Agent skill without MCP

Use the engine directly from a SKILL.md-compatible agent by copying or symlinking `sdpm/`
into the agent's skills directory. The agent calls `scripts/pptx_builder.py`; no MCP server
or AWS account is involved.

```bash
cd sdpm
uv sync

# Download icons (optional, recommended)
uv run python3 scripts/download_aws_icons.py
uv run python3 scripts/download_material_icons.py

# Verify
uv run python3 scripts/pptx_builder.py list_templates
```

The engine, references (workflows, guides, bundled styles), sample templates (dark/light), and SKILL.md are all included.

### Local MCP server

Connect SDPM to an MCP-compatible client without AWS.

#### Kiro CLI from a checkout

The `kiro-cli mcp add … uvx …` one-liner in the quick start is the complete setup: the
orchestrator spawns composers as ordinary sub-agents, which start with `start_composing`.
`make install-kiro` is the checkout-based alternative; it additionally links the `sdpm-*`
skills (slash-command entry points) and generates a `sdpm-composer` agent whose only MCP
server is SDPM — an optimisation for profiles with many MCP servers, not a requirement.

```bash
git clone https://github.com/aws-samples/sample-spec-driven-presentation-maker.git
cd sample-spec-driven-presentation-maker
make install-kiro
kiro-cli chat   # then ask: "make slides about ..."
```

This registers `sdpm` in `<KIRO_HOME>/settings/mcp.json` (default `~/.kiro`), links the
entry points into `<KIRO_HOME>/skills/`, and generates
`<KIRO_HOME>/agents/sdpm-composer.json`. The composer profile starts only the SDPM MCP
server instead of every server in your profile. Keep the checkout in place. Update it with
`git pull`; rerun `make install-kiro` only after moving the checkout.

Useful options:

```bash
uv run python3 clients/kiro/install.py --agent NAME       # one agent config
uv run python3 clients/kiro/install.py --mode legacy      # skip Power detection
KIRO_HOME=~/.kiro-sdpm-dev make install-kiro              # separate profile
```

The installer stops rather than overwrite wiring owned by another checkout. Use a separate
`KIRO_HOME`, remove the other wiring yourself, or pass `--replace-existing` deliberately.

#### Kiro IDE Power

The repository root is an [Agent Plugins](https://agent-plugins.org) package
(`plugin.json`, `mcp.json`, and `skills/`). Install the checkout as a Power from Kiro IDE.
Kiro manages the bundled MCP server at global scope. The GitHub import URL still requires
separate device verification, so this guide does not claim a one-click URL yet.

Do not activate the Power and checkout-based Kiro CLI wiring in the same profile. Use a
separate `KIRO_HOME`; `make install-kiro` removes its own legacy wiring when it detects the
Power in that profile.

#### Codex plugin from a checkout

```bash
codex plugin marketplace add ./
```

Run the command inside the checkout, install `spec-driven-presentation-maker` from that
marketplace in the ChatGPT desktop app, and start a new conversation. Codex copies the
plugin into `~/.codex/plugins/cache/…` and creates its Python environment in writable plugin
data.

#### Manual MCP configuration

For a clone-free client configuration, add the canonical stdio server definition:

```json
{
  "mcpServers": {
    "sdpm": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/aws-samples/sample-spec-driven-presentation-maker#subdirectory=servers/local",
        "sdpm-mcp"
      ]
    }
  }
}
```

To run from a source checkout instead, prepare and test the server:

```bash
cd servers/local
uv sync
uv run python server.py
```

Then point your client's MCP configuration at the absolute checkout path:

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

Ask the connected agent to create a presentation. It reads the workflow, gathers the topic,
audience, and purpose, writes the brief, art direction, and outline, builds the slides, then
generates the PPTX and previews. See the
[Architecture MCP tool reference](architecture.md#mcp-tool-reference) for the tool list.

### Remote MCP server (AWS)

Deploy spec-driven-presentation-maker as a remote MCP server on Amazon Bedrock AgentCore Runtime.

> **💡 The [Recommended Deploy Guide](deploy-cloudshell.md) is the recommended path for AWS deployments.**
> `scripts/deploy.sh` runs from CloudShell and from any local Linux/macOS environment, and builds via CodeBuild — so you don't need CDK or Docker installed locally. The instructions below cover the direct local CDK workflow, mainly used for development and debugging.

#### Configuration

```bash
cd infra
npm ci
cp config.example.yaml config.yaml
```

Edit `config.yaml` to select which stacks to deploy.

##### MCP server only (minimum)

```yaml
stacks:
  data: true           # Required — DynamoDB + S3
  runtime: true        # Required — AgentCore Runtime MCP Server
  agent: false
  webUi: false

features:
  enableInvocationLogging: false  # Bedrock Model Invocation Logging (optional)
```

#### Deploy

```bash
# With Docker Desktop
npx cdk deploy --all

# With Finch (no Docker Desktop)
CDK_DOCKER=finch npx cdk deploy --all

# Non-interactive (CI/CD)
CDK_DOCKER=finch npx cdk deploy --all --require-approval never
```

Deployment takes approximately 15–30 minutes.

##### Changing the Model ID

The default model is `global.anthropic.claude-sonnet-4-6`. To use a different model, edit `infra/config.yaml`:

```yaml
model:
  modelId: "global.anthropic.claude-opus-4-6-v1"
```

Or override at deploy time:

```bash
npx cdk deploy --all --context modelId=global.anthropic.claude-opus-4-6-v1
```

#### Deployed stacks

| Stack | Resources |
|-------|-----------|
| SdpmData | Amazon DynamoDB table, S3 buckets (pptx + resources), reference files deployed to S3 |
| SdpmRuntime | Amazon Bedrock AgentCore Runtime endpoint, ECR repository + Docker image, Amazon Cognito M2M auth |

#### Template Registration

CDK deploys template files to S3, but Amazon DynamoDB registration is required for `list_templates` to work.
See [Custom Templates — Registering Templates](custom-template.md#layer-3-remote-mcp) for details.

#### Verify Deployment

##### Get an OAuth Token

```bash
TOKEN=$(curl -s -X POST \
  "https://<CognitoDomain>.auth.<region>.amazoncognito.com/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "<M2MClientId>:<M2MClientSecret>" \
  -d "grant_type=client_credentials&scope=sdpm/invoke" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Find `CognitoDomain`, `M2MClientId`, and `M2MClientSecret` in the CDK outputs.

##### Call tools/list

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

### Full stack (AWS)

> **💡 Recommended path:** Deploy the full stack via the [Recommended Deploy Guide](deploy-cloudshell.md) (works from CloudShell and any local Linux/macOS). Just run `./scripts/deploy.sh --region us-east-1` — no local CDK/Docker needed.

Enable `agent` and `webUi` in `config.yaml` to add:

- Strands Agent on Amazon Bedrock AgentCore Runtime
- React Web UI (chat interface + deck preview)
- JWT Bearer authentication (Amazon Cognito default, any OIDC IdP supported)

#### Configuration

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

#### Full-stack additions

| Stack | Resources |
|-------|-----------|
| SdpmAuth | Amazon Cognito User Pool, hosted UI |
| SdpmAgent | Strands Agent on Amazon Bedrock AgentCore Runtime, ECR image |
| SdpmWebUi | S3 bucket, Amazon CloudFront distribution, Amazon API Gateway, Lambda |

#### Authentication Options

##### Default: Amazon Cognito User Pool

When `agent` or `webUi` is enabled, CDK automatically creates a Amazon Cognito User Pool with hosted UI. Users sign in via the web UI, and the JWT is propagated through the stack.

For authentication and authorization model details, see [Architecture — Authentication and Authorization Model](architecture.md#authentication-and-authorization-model).

##### External OIDC IdP

To use your own IdP (Entra ID, Auth0, Okta, etc.):

1. Skip the AuthStack or configure your IdP as a Amazon Cognito federation source
2. Set `oidcDiscoveryUrl` and `allowedClients` in `config.yaml`
3. The Runtime's `customJwtAuthorizer` validates JWTs from any OIDC-compliant issuer

#### Checking Endpoints After Deployment

If the deploy script's log monitoring was interrupted, or you need to check the endpoints later, run:

```bash
bash scripts/show_endpoints.sh
```

This displays the CloudFront URL and Cognito sign-up URL from the deployed CloudFormation stacks.

#### Updating the Web UI

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
