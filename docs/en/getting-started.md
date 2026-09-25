[EN](../en/getting-started.md) | [JA](../ja/getting-started.md)

# Getting Started

Use SDPM in a browser or connect it to the AI agent you already use. Both paths run
locally without an AWS account. For the internal four-layer design, see
[Architecture](architecture.md#4-layer-architecture).

## Install

One command installs SDPM into `~/.sdpm`: a git checkout, the MCP server environment, the
icon catalogs, and the `sdpm` launcher. The same checkout serves every surface — your AI
agent through MCP and, optionally, a browser Web UI — so there is one thing to update and
one thing to remove.

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.sh | bash
```

```powershell
# Windows (PowerShell 5.1 or 7; verified in CI only)
irm https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.ps1 | iex
```

What happens:

1. Dependencies are checked and offered for installation: `git`, `uv`, and — for slide
   previews — LibreOffice and poppler. Previews are optional; a deck builds without them.
2. **"Also install the browser Web UI?"** — yes installs Node.js 20+ and Kiro CLI (the Web
   UI's agent backend) and builds the UI; no gives you an MCP-only install with no Node.js.
3. The checkout is cloned to `~/.sdpm/checkout`, the server environment is synced, and the
   AWS / Material icon catalogs are downloaded.
4. **"Register SDPM with <client>?"** — asked once per MCP client found on the machine.
   Nothing is written without your yes. The final screen tells you what to do next.

Re-running the installer repairs an existing installation; it never creates a second one.

### Installer options

| Option | Effect |
|---|---|
| `--full` / `--mcp-only` | Skip the profile question |
| `--register` / `--no-register` | Register with every detected client / only print the configuration |
| `--non-interactive` | Accept all prompts (profile defaults to full) |
| `--skip-libreoffice`, `--skip-shortcut` | Leave those out |
| `--deps-only` | Install `git`, `uv`, LibreOffice and poppler only (for a developer checkout) |

Environment equivalents: `SDPM_PROFILE=full|mcp`, `SDPM_REGISTER=yes|no`,
`SDPM_NON_INTERACTIVE=1`, `SDPM_HOME` (install root, default `~/.sdpm`),
`SDPM_LAUNCHER_DIR` (default `~/.local/bin`; `%USERPROFILE%\bin` on Windows).
`bash -s -- --mcp-only` passes options through `curl … | bash`.

## The `sdpm` launcher

```
sdpm                    status: version, profile, surfaces, which clients are connected
sdpm webui              start the browser Web UI and open it
sdpm mcp                run the MCP server on stdio (to check it from a terminal)
sdpm register [CLIENT]  connect MCP clients (asks per client; --yes, --dry-run)
sdpm unregister         disconnect them again
sdpm mcp-config [CLIENT]  print the client configuration with this machine's paths (--json, --all)
sdpm update [--with-webui]  pull main, sync, rebuild what is installed (or add the Web UI)
sdpm doctor             environment checks
sdpm uninstall          remove ~/.sdpm, the launcher, shortcuts; offers to unregister
```

The launcher is the same on every OS. `sdpm mcp` exists for humans; the configuration the
clients receive points at `uv` and the checkout directly (next section).

## Your AI agent (MCP)

`sdpm register` connects the server through each client's own CLI, so no configuration file
is edited by hand:

| Client | What `sdpm register` does |
|---|---|
| Kiro CLI (and Kiro IDE — shared `~/.kiro/settings/mcp.json`) | `kiro-cli mcp add --scope global …` |
| Claude Code | `claude mcp add --scope user sdpm -- …` |
| Visual Studio Code | `code --add-mcp …` |
| Codex (CLI, IDE extension, ChatGPT desktop app) | `codex mcp add sdpm -- …` |
| Cursor | opens the `cursor://…/mcp/install` deep link built with your real paths — one click |
| Kiro IDE without Kiro CLI, other clients | prints the JSON and the file it belongs in |
| Claude Desktop | use the [`sdpm.mcpb`](https://github.com/aws-samples/sample-spec-driven-presentation-maker/releases/latest/download/sdpm.mcpb) release instead (double-click) |

Every configuration is the same one line, with absolute paths:

```json
{
  "mcpServers": {
    "sdpm": {
      "command": "/Users/you/.local/bin/uv",
      "args": ["run", "--directory", "/Users/you/.sdpm/checkout/servers/local", "python", "server.py"]
    }
  }
}
```

Absolute paths matter: GUI clients started from the Dock or Start Menu do not inherit your
shell `PATH`. `sdpm mcp-config` prints this block with your paths filled in for any client,
so a client that is not listed above takes it verbatim.

Then ask your agent for slides. The first tool it reaches for, `start_presentation`, returns
the role document that drives the work plus the styles and templates on offer — the MCP
server alone is the complete setup. To pick a mode explicitly, use the server's prompts
where your client shows them: `sdpm-vibe` (build from material, no questions), `sdpm-spec`
(shape the deck in dialogue first), `sdpm-style`, `sdpm-translate` (Claude Code
`/mcp__sdpm__sdpm-vibe`, VS Code `/mcp.sdpm.sdpm-vibe`, Kiro CLI `/sdpm-vibe`).

Slide previews need LibreOffice and poppler. Without them the deck still builds; the build
result carries `preview: {"status": "unavailable", "install": "…"}` with the one command
for your OS, and the agent relays it. Icon catalogs missing for any reason are fetched in
the background on the server's first start.

## Your browser (Web UI)

`sdpm webui` starts the Web UI in Local mode — Next.js on `http://localhost:3000` talking to
Kiro CLI over ACP — and opens it. Run `kiro-cli login` once before the first use. The
installer also creates a desktop shortcut. An MCP-only install adds the Web UI later with
`sdpm update --with-webui`. Details: [Web UI Local mode](../../web-ui/README.md#local-mode).

## AWS deployment

For a shared remote MCP server or hosted Web UI, use the
[One-Click Deploy](deploy-cloudshell.md#one-click-deploy-recommended). The recommended path
runs from AWS CloudShell and does not require local CDK or Docker. Direct CDK instructions
for development and debugging are under [Developer setup](#developer-setup).

## Developer setup

For contributors working from their own clone (not `~/.sdpm/checkout`).

### Local MCP server from a checkout

```bash
curl -fsSL https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.sh | bash -s -- --deps-only
git clone https://github.com/aws-samples/sample-spec-driven-presentation-maker.git
cd sample-spec-driven-presentation-maker
uv sync
(cd servers/local && uv sync)
uv run python3 sdpm/scripts/download_aws_icons.py
uv run python3 sdpm/scripts/download_material_icons.py
make smoke        # tools/list + start_presentation against the local server
```

Point a client at the clone with the same one-line configuration, using the clone's
`servers/local` path — or let the checkout do it:

```bash
uv run --directory servers/local python client_config.py --checkout "$PWD" print --all
```

### Agent skill without MCP

`sdpm/SKILL.md` drives the CLI (`sdpm/scripts/pptx_builder.py`) directly for agents that
have no MCP support. Copy or symlink `sdpm/` into the agent's skills directory; the engine,
references and templates are all inside it. This is an architecture artefact, not a
recommended path.

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
