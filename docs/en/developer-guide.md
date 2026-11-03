# Developer Guide

This guide is for two readers: contributors who change the code, and operators who deploy
SDPM to AWS from a checkout with the CDK. To use SDPM, see [Getting Started](getting-started.md).
To deploy on AWS without installing the CDK or Docker, use the
[Deploy guide](deploy-cloudshell.md) (One-Click Deploy or AWS CloudShell).

## Work from a checkout

Set up your own clone (not `~/.sdpm/checkout`):

```bash
curl -fsSL https://raw.githubusercontent.com/aws-samples/sample-spec-driven-presentation-maker/main/scripts/install/dist/install.sh | bash -s -- --deps-only
git clone https://github.com/aws-samples/sample-spec-driven-presentation-maker.git
cd sample-spec-driven-presentation-maker
uv sync
uv run python3 sdpm/scripts/download_aws_icons.py
uv run python3 sdpm/scripts/download_material_icons.py
make smoke        # tools/list + start_presentation against the local server
```

You can keep the installed release and your clone side by side. The installed `~/.sdpm` is
what users run; your clone is what you change. Point clients at the clone **next to** the
installed one:

```bash
make register-dev              # Kiro CLI: agent `sdpm-dev` → this checkout; others: asks per client
make register-dev AGENT=sdpm-x CLIENTS=kiro-cli   # one agent per worktree, one client
make mcp-config-dev            # just print the configuration for this checkout
```

`kiro-cli chat --agent sdpm-dev` then runs your working tree, and `--agent sdpm` runs the
installed release. The Web UI needs no registration. It finds `servers/local` relative to
its own `web-ui/` directory, so `cd web-ui && npm run dev:local` runs your clone's server
and ACP agents with hot reload. Use `PORT=3001` if `sdpm webui` is already on port 3000, or
move the installed one with `SDPM_WEBUI_PORT`.

| | Installed (what users run) | Your clone |
|---|---|---|
| MCP (Kiro CLI) | `kiro-cli chat --agent sdpm` | `make register-dev` → `--agent sdpm-dev` |
| Web UI | `sdpm webui` | `cd web-ui && npm run dev:local` |
| Update | `sdpm update` | `git pull`; edits apply on the next session |

For Claude Code, `--scope user` registration allows one server name per scope. For the
clone, use a project-scoped entry or an ad-hoc config such as
`claude --mcp-config <(make -s mcp-config-dev …)` instead of replacing the user-scope `sdpm`.

### Agent skill without MCP

`sdpm/SKILL.md` drives the CLI (`sdpm/scripts/pptx_builder.py`) directly, for agents that
have no MCP support. Copy or symlink `sdpm/` into the agent's skills directory. The engine,
references and templates are all inside it. This path exists for completeness; MCP is the
recommended way.

### Checks before a pull request

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full process. In short:

```bash
make lint                                  # ruff
make test                                  # pytest
ash scan --mode local --fail-on-findings   # security scan (ASH)
bash scripts/install/build.sh              # only when you changed scripts/install/ (CI rejects drift)
```

## Remote MCP server (AWS)

This section deploys SDPM as a remote MCP server on Amazon Bedrock AgentCore Runtime with
the CDK on your machine. It is mainly for development and debugging.

> **Recommended for most deployments:** the [Deploy guide](deploy-cloudshell.md).
> `scripts/deploy.sh` runs from CloudShell or any local Linux or macOS machine and builds
> through CodeBuild, so you need neither the CDK nor Docker locally.

### Configuration

```bash
cd infra
npm ci
cp config.example.yaml config.yaml
```

Edit `config.yaml` to select which stacks to deploy. For the MCP server only (the minimum):

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

Deployment takes about 15 to 30 minutes.

### Deployed stacks

| Stack | Resources |
|-------|-----------|
| SdpmData | Amazon DynamoDB table, S3 buckets (pptx + resources), reference files deployed to S3 |
| SdpmRuntime | Amazon Bedrock AgentCore Runtime endpoint, ECR repository + Docker image, Amazon Cognito M2M auth |

### Templates

The bundled templates are deployed to the resource bucket under `templates/` and are listed
by `list_templates` with no further step. To add a template for everyone in your deployment,
use `scripts/upload_template.py`; see
[Custom Templates — Layer 3](custom-template.md#layer-3-remote-mcp).

### Verify the deployment

Get an OAuth token:

```bash
TOKEN=$(curl -s -X POST \
  "https://<CognitoDomain>.auth.<region>.amazoncognito.com/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "<M2MClientId>:<M2MClientSecret>" \
  -d "grant_type=client_credentials&scope=sdpm/invoke" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Find `CognitoDomain`, `M2MClientId` and `M2MClientSecret` in the CDK outputs. Then call
`tools/list`:

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

## Full stack (AWS)

> **Recommended:** deploy the full stack with the [Deploy guide](deploy-cloudshell.md)
> (CloudShell or any local Linux or macOS machine): `./scripts/deploy.sh --region us-east-1`.
> No local CDK or Docker is needed.

Enable `agent` and `webUi` in `config.yaml` to add:

- the Strands Agent on Amazon Bedrock AgentCore Runtime
- the React Web UI (chat and deck preview)
- JWT Bearer authentication (Amazon Cognito by default; any OIDC IdP works)

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

| Stack | Resources |
|-------|-----------|
| SdpmAuth | Amazon Cognito User Pool, hosted UI |
| SdpmAgent | Strands Agent on Amazon Bedrock AgentCore Runtime, ECR image |
| SdpmWebUi | S3 bucket, Amazon CloudFront distribution, Amazon API Gateway, Lambda |

### Choosing the models

The agent's models are set under `model` in `infra/config.yaml`:

```yaml
model:
  defaults:
    chat: "global.anthropic.claude-sonnet-4-6"
    create: "global.anthropic.claude-sonnet-4-6"   # omit to use the chat model
  allowedModelIds:          # the models users can pick in the Web UI
    - "global.anthropic.claude-sonnet-4-6"
    - "global.anthropic.claude-opus-4-6-v1"
  recommendedModelIds:      # optional: listed under "Recommended" in the picker
    - "global.anthropic.claude-sonnet-4-6"
```

The default for both is `global.anthropic.claude-sonnet-4-6`. Both defaults must be in
`allowedModelIds` (and in `recommendedModelIds` when that list is present). Every model in
`allowedModelIds` must have an entry in `infra/lib/model-metadata.ts`, or the synth fails.
`infra/config.example.yaml` lists the models that are registered today.

### Authentication options

#### Default: Amazon Cognito User Pool

When `agent` or `webUi` is enabled, the CDK creates an Amazon Cognito User Pool with a
hosted UI. Users sign in through the Web UI, and the JWT is passed through the stack. For
the authentication and authorization model, see
[Architecture — Authentication and Authorization Model](architecture.md#authentication-and-authorization-model).

Self sign-up is off by default: an administrator creates each user, in the Cognito console
or with `aws cognito-idp admin-create-user`
([Deploy guide — Creating a Cognito user](deploy-cloudshell.md#creating-a-cognito-user-layer-4)).
To let people create their own account from the sign-in page, turn it on in `config.yaml`,
optionally limited to some email domains:

```yaml
auth:
  selfSignUp: true            # default: false
  allowedEmailDomains:        # optional; omit for any domain
    - example.com
```

A Cognito Pre sign-up Lambda trigger checks the domain of every sign-up request. The match
is exact and ignores case: `example.com` does not admit `team.example.com`, so list each
subdomain you want. Users created by an administrator are not checked.
`allowedEmailDomains` without `selfSignUp: true` fails the synth. Switching either setting
updates the user pool in place; existing users keep their accounts.

#### External OIDC IdP

To use your own IdP (Entra ID, Auth0, Okta and others):

1. Skip the AuthStack, or configure your IdP as an Amazon Cognito federation source.
2. Set `oidcDiscoveryUrl` and `allowedClients` in `config.yaml`.
3. The runtime's `customJwtAuthorizer` validates JWTs from any OIDC-compliant issuer.

### Checking endpoints after deployment

If the deploy script's log monitoring was interrupted, or you need the endpoints later, run:

```bash
bash scripts/show_endpoints.sh
```

It prints the CloudFront URL and the Cognito user pool console URL from the deployed CloudFormation stacks.

### Updating the Web UI

To update the Web UI without a full CDK deployment:

```bash
cd web-ui && npm run build && cd ..
bash scripts/deploy_webui.sh
```

`aws-exports.json` (auth settings, API endpoints) is managed by a CDK custom resource. If you
change the stack configuration, run `npx cdk deploy SdpmWebUi`.

## Optional features

### WAF IP address restriction

Set `waf.allowedIpV4AddressRanges` and/or `waf.allowedIpV6AddressRanges` in `config.yaml` to
restrict access to CloudFront and API Gateway by IP address.

```yaml
waf:
  allowedIpV4AddressRanges:
    - "10.0.0.0/8"
    - "192.168.0.0/16"
  allowedIpV6AddressRanges:
    - "2001:db8::/32"
```

When configured, the CDK creates:

- the **SdpmCloudFrontWaf** stack in `us-east-1` (WAFv2 requires the CLOUDFRONT scope there), attached to CloudFront
- a **regional WAF** in the deploy region, attached to API Gateway

The default action is **Block**: only the listed IP ranges are allowed. Without the `waf`
section, no WAF resources are created.

> **⚠️ IPv6:** if you set only `allowedIpV4AddressRanges`, all IPv6 access is blocked.
> Browsers often prefer IPv6 when it is available, so the Web UI can hang on "Loading
> authentication configuration..." even though your IPv4 address is allowed. On a
> dual-stack network, set both IPv4 and IPv6 ranges.

### Semantic slide search

Search across decks is included, backed by Amazon Bedrock Knowledge Bases and Amazon S3
Vectors. It needs no extra configuration.

### Custom templates and assets

To add `.pptx` templates and icons, see [Custom Templates and Assets](custom-template.md).

## Notes

### Cost

See [Cost Estimates](cost.md). When you are done with development or testing, delete the
resources with `npx cdk destroy --all`.

### Data retention

The SdpmData stack deletes its data with it. The DynamoDB table and both S3 buckets use
`RemovalPolicy.DESTROY`, and the buckets empty themselves on deletion
(`autoDeleteObjects`). `cdk destroy` or deleting SdpmData removes every deck. Export what
you want to keep first. See also [Uninstall](uninstall.md).

## Troubleshooting

### Docker build fails with Finch

```bash
export CDK_DOCKER=finch
```

### ECR permission error during deploy

Amazon Bedrock AgentCore Runtime can hit permission errors when pulling ECR images. This
usually resolves on a second deploy:

```bash
npx cdk deploy --all
```

### Missing .dockerignore

If Docker builds are very slow or fail with disk space errors, make sure `.dockerignore`
exists at the repository root.

### White screen at the Amazon CloudFront URL

The deployment may have run without `web-ui/build` present:

```bash
cd web-ui && npm run build && cd ..
bash scripts/deploy_webui.sh
```

## Related documents

- [Architecture](architecture.md): layers, data flow, auth model, MCP tool reference
- [Security](security.md): what the AWS stack sets up and what to review before production
- [Custom Templates](custom-template.md): templates, styles and assets
- [Connecting Agents](add-to-gateway.md): MCP clients and gateways
