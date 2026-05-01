[EN](../en/add-to-gateway.md) | [JA](../ja/add-to-gateway.md)

# Connecting Agents

spec-driven-presentation-maker is an MCP server — it connects to any AI agent that supports the Model Context Protocol. This guide covers the connection options.

## Option 1: Local MCP Server (Layer 2)

No AWS required. The server runs locally via stdio.

See [Getting Started — Layer 2](getting-started.md#layer-2-local-mcp-server) for setup and MCP client configuration.

## Option 2: OAuth 2.1 Discovery Endpoint (Layer 3, recommended)

Requires Layer 3 deployed via CDK (see [Getting Started — Layer 3](getting-started.md#layer-3-remote-mcp-server-aws)).

Register the **MCP Server URL** (API Gateway HTTP API created during CDK deployment) in your MCP client. Authentication is handled automatically via the OAuth 2.1 Discovery protocol.

### Connection Method A: Dynamic Client Registration (DCR) — Default

All major MCP clients (Claude.ai, Claude Desktop, Cursor, VS Code, Kiro) support DCR (RFC 7591). Simply register the MCP Server URL in your client — the client automatically performs OAuth discovery → DCR → authorization code flow.

#### MCP client configuration

```json
{
  "mcpServers": {
    "spec-driven-presentation-maker": {
      "url": "<McpServerUrl>"
    }
  }
}
```

Get `<McpServerUrl>` from the CDK output `SdpmRuntime.McpServerUrl`.

### Connection Method B: Static Client Registration (`auth.mcpCallbackUrls`)

Use a static OAuth client instead of DCR when either of the following applies:

- **The MCP client does not support DCR**
- **You want to restrict access to specific clients only** (enterprise security requirements where open DCR registration is not acceptable)

> **Note**: Disabling DCR will prevent connections from clients that use a different `localhost` callback port on each session.

#### Setup

1. Add the allowed client callback URLs to `config.yaml` and optionally disable DCR:

```yaml
auth:
  enableDCR: false  # Disable DCR (when allowing only specific clients)
  mcpCallbackUrls:
    - https://claude.ai/api/mcp/auth_callback
    - https://claude.com/api/mcp/auth_callback
```

2. Redeploy (`cdk deploy --all`)
3. Configure the MCP client with the `SdpmRuntime.McpOAuthClientId` from CDK outputs

> **Note**: When `enableDCR: false`, the `registration_endpoint` is omitted from `/.well-known/oauth-authorization-server` metadata and `/register` returns 403. Only clients with callback URLs listed in `mcpCallbackUrls` can connect.

#### Deployment patterns

| `mcpCallbackUrls` | `enableDCR` | Behavior |
|---|---|---|
| — | `true` (default) | DCR only. Personal/demo use |
| set | `true` | Static client + DCR. Flexible |
| set | `false` | Static client only. Enterprise lockdown |
| — | `false` | No external MCP access. WebUI only |

---

## Security: protecting the MCP endpoint

The Runtime endpoint is exposed on the **public internet**. Authentication (Cognito JWT or IAM) prevents unauthorized access, but the following additional measures are **strongly recommended**.

### WAF IP restrictions

Set `waf.allowedIpV4AddressRanges` / `allowedIpV6AddressRanges` in `config.yaml` to attach AWS WAF rules to CloudFront and API Gateway. Useful for restricting access to a corporate VPN or specific office networks.

```yaml
waf:
  allowedIpV4AddressRanges:
    - "192.0.2.0/24"      # Corporate IPv4 range
    - "203.0.113.10/32"   # Individual IP
  allowedIpV6AddressRanges:
    - "2001:db8::/32"     # Corporate IPv6 range
```

**Note**: The Runtime endpoint itself (`bedrock-agentcore.*.amazonaws.com`) is managed by AWS and cannot have WAF attached directly. The WAF rules above apply to the Web UI (CloudFront) and API (API Gateway). The primary defence for the Runtime is **JWT / IAM authentication**.

### Other recommendations

- **Pass JWT tokens via environment variables**, not in `mcp.json` as plain text.
- **Keep `allowedClients` as small as possible** when using Cognito.
- **Enable CloudTrail** in production to audit Runtime access.
- **Tighten CORS** to your organisation's domains.

---

## Authentication Configuration

### Default: Amazon Cognito User Pool

CDK creates a Amazon Cognito User Pool with M2M (machine-to-machine) credentials. The M2M client ID and secret are in the CDK outputs.

### External OIDC Identity Provider

spec-driven-presentation-maker supports any OIDC-compliant identity provider:

1. Set `oidcDiscoveryUrl` in `config.yaml` pointing to your IdP's `.well-known/openid-configuration`
2. Set `allowedClients` to the client IDs that should be accepted
3. The Runtime's `customJwtAuthorizer` validates JWTs against the OIDC discovery document

Tested with: Amazon Cognito, Entra ID, Auth0, Okta.

### User Identity

The JWT `sub` claim is used as the user identity throughout the stack:
- Deck ownership and access control
- Per-user deck isolation
- Audit trail

No additional user registration is needed — any valid JWT with a `sub` claim works.

---

## Option 3: Generative AI Use Cases on AWS (GenU) Integration

> **Note:** [Generative AI Use Cases on AWS (GenU)](https://github.com/aws-samples/generative-ai-use-cases-jp) is a separate open-source project under active development. The steps below are based on GenU v5.x as of April 2026 and may change in future releases.

[GenU](https://github.com/aws-samples/generative-ai-use-cases-jp) is an open-source web application that provides various generative AI use cases on AWS. GenU's **AgentBuilder** lets users create custom agents with selected MCP tools and a tailored system prompt. By bundling spec-driven-presentation-maker into the AgentCore Runtime container, users can generate presentations from GenU's web interface.

### Prerequisites

- GenU repository cloned and deployable (see [GenU README](https://github.com/aws-samples/generative-ai-use-cases-jp))
- Docker available on the build machine (required for AgentCore container image build)
- On x86_64 hosts (Intel/AMD), run `docker run --privileged --rm tonistiigi/binfmt --install arm64` before deploying (AgentCore requires ARM64 container images)
- **AgentBuilder enabled** in `packages/cdk/cdk.json` or `parameter.ts`: `agentBuilderEnabled: true`

### Step 1: Copy sdpm files into the GenU AgentCore Runtime directory

```bash
GENU_RUNTIME_DIR=<path-to-genu>/packages/cdk/lambda-python/generic-agent-core-runtime

cp -r <path-to-sdpm>/skill $GENU_RUNTIME_DIR/sdpm-skill
cp -r <path-to-sdpm>/mcp-local $GENU_RUNTIME_DIR/sdpm-mcp-local
```

### Step 2: Patch the Dockerfile

Add the following lines to `$GENU_RUNTIME_DIR/Dockerfile`, **before** the `EXPOSE` line:

```dockerfile
# --- SDPM: spec-driven-presentation-maker ---
COPY sdpm-skill/ ./sdpm-skill/
COPY sdpm-mcp-local/ ./sdpm-mcp-local/
RUN uv pip install --python /tmp/.venv/bin/python ./sdpm-skill
RUN /tmp/.venv/bin/python sdpm-skill/scripts/download_aws_icons.py \
 && /tmp/.venv/bin/python sdpm-skill/scripts/download_material_icons.py
RUN ln -s /var/task/sdpm-skill /var/task/skill
```

### Step 3: Register the MCP server

Add the following entry to `$GENU_RUNTIME_DIR/mcp-configs/agent-builder/mcp.json` under `mcpServers`:

```json
"spec-driven-presentation-maker": {
    "command": "python",
    "args": ["sdpm-mcp-local/server.py"],
    "env": {
        "PYTHONPATH": "/var/task/sdpm-skill",
        "SDPM_OUTPUT_DIR": "/tmp/ws"
    }
}
```

`SDPM_OUTPUT_DIR` tells the skill where to write generated files. GenU requires output files under `/tmp/ws` so that `upload_file_to_s3_and_retrieve_s3_url` can upload them to S3.

### Step 4: Deploy

```bash
cd <path-to-genu>
npx -w packages/cdk cdk deploy --all
```

### Step 5: Create an agent in AgentBuilder

In GenU's AgentBuilder UI:

1. Select `spec-driven-presentation-maker` from the MCP server list
2. Set the following system prompt:

```
You are a presentation design assistant. Use the spec-driven-presentation-maker MCP tools to create PowerPoint slides.

Key rules:
- Always call read_workflows first to load the workflow before making any design decisions.
- When writing the presentation JSON, use the write_file tool to write to /tmp/ws/. Do NOT use Code Interpreter — its sandbox is isolated from MCP tools.
- Large JSON must be split to avoid timeouts. Write each slide as a separate file (e.g. /tmp/ws/part1.json, /tmp/ws/part2.json), then use concat_files to join them into the final /tmp/ws/presentation.json.
- Example split strategy:
  1. write_file("/tmp/ws/header.json", '{"template":"sample_template_dark","slides":[', mode="create")
  2. write_file("/tmp/ws/slide1.json", '{...slide 1 JSON...},', mode="create")
  3. write_file("/tmp/ws/slide2.json", '{...slide 2 JSON...}', mode="create")
  4. write_file("/tmp/ws/footer.json", ']}', mode="create")
  5. concat_files(source_paths=["/tmp/ws/header.json","/tmp/ws/slide1.json","/tmp/ws/slide2.json","/tmp/ws/footer.json"], destination="/tmp/ws/presentation.json")
  6. generate_pptx(slides_json_path="/tmp/ws/presentation.json", template="sample_template_dark")
- If a JSON error occurs, use write_file with mode="str_replace" to fix the specific part instead of rewriting the entire file.
- After generating the PPTX, upload it with upload_file_to_s3_and_retrieve_s3_url and provide the S3 URL as a Markdown link: [filename.pptx](S3_URL)
```

### How it works

```
User → GenU AgentBuilder UI → Strands Agent (AgentCore Runtime)
                                 ├── sdpm MCP tools (stdio)
                                 │   ├── generate_pptx → /tmp/ws/*.pptx
                                 │   └── search_assets, analyze_template, ...
                                 ├── write_file, concat_files (built-in)
                                 └── upload_file_to_s3_and_retrieve_s3_url
                                     └── S3 URL → User
```

### Writing large files

LLM output can time out when generating large JSON in a single tool call. To avoid this:

1. Use `write_file` to write each part as a separate file
2. Use `concat_files` to join them into the final file
3. Use `write_file` with `mode="str_replace"` to fix errors without rewriting everything
