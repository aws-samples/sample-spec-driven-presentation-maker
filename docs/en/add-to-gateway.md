[EN](../en/add-to-gateway.md) | [JA](../ja/add-to-gateway.md)

# Connecting Agents

spec-driven-presentation-maker is an MCP server — it connects to any AI agent that supports the Model Context Protocol. This guide covers three connection options.

## Option 1: Local MCP Server (Layer 2)

No AWS required. The server runs locally via stdio.

### As an Agent Skill

Copy `skill/` to your agent's skills directory. The SKILL.md file provides workflow instructions directly.

### As a stdio MCP Server

Add to your MCP client's configuration:

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

The server command is:

```bash
uv run --directory /path/to/mcp-local python server.py
```

Any MCP client that supports stdio servers can connect. Refer to your client's documentation for the configuration file location.

## Option 2: Amazon Bedrock AgentCore Gateway (Layer 3, recommended for teams)

For multi-user deployments, connect through Amazon Bedrock AgentCore Gateway. The Gateway provides OAuth-based authentication, tool aggregation, and Cedar-based authorization.

### Prerequisites

- Layer 3 deployed via CDK (see [Getting Started — Layer 3](getting-started.md#layer-3-remote-mcp-server-aws))
- Amazon Bedrock AgentCore Gateway configured in your AWS account

### Register as a Gateway Target

Add the spec-driven-presentation-maker Runtime as an MCP Server target on your Amazon Bedrock AgentCore Gateway:

1. Get the Runtime ARN from CDK outputs (`SdpmRuntime.RuntimeArn`)
2. Configure the Gateway to route to this Runtime
3. Set up OAuth credentials for the Gateway → Runtime connection (M2M client credentials from CDK outputs)

MCP clients that connect to the Gateway will automatically discover spec-driven-presentation-maker's tools alongside any other registered MCP servers.

### Authentication Flow

```
MCP Client → Gateway (OAuth) → Runtime (JWT Bearer) → MCP Server Container
```

The Gateway handles client authentication. The Runtime validates the JWT and extracts the user identity (`sub` claim) for per-user deck authorization.

## Option 3: Direct Runtime Access (Layer 3)

Connect directly to the Amazon Bedrock AgentCore Runtime endpoint without a Gateway. Useful for testing or single-server deployments.

### Endpoint

```
POST https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{ENCODED_ARN}/invocations?qualifier=DEFAULT
```

Where `ENCODED_ARN` is the URL-encoded Runtime ARN.

### Headers

```
Content-Type: application/json
Accept: application/json, text/event-stream
Authorization: Bearer {JWT_TOKEN}
```

### Example: List tools

```bash
# Get OAuth token
TOKEN=$(curl -s -X POST \
  "https://<CognitoDomain>.auth.<region>.amazoncognito.com/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -u "<M2MClientId>:<M2MClientSecret>" \
  -d "grant_type=client_credentials&scope=sdpm/invoke" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# URL-encode the Runtime ARN
ENCODED_ARN=$(python3 -c "import urllib.parse; print(urllib.parse.quote('<RuntimeArn>', safe=''))")

# Call tools/list
curl -X POST \
  "https://bedrock-agentcore.<region>.amazonaws.com/runtimes/${ENCODED_ARN}/invocations?qualifier=DEFAULT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":1}'
```

### Example: Call a tool

```bash
curl -X POST \
  "https://bedrock-agentcore.<region>.amazonaws.com/runtimes/${ENCODED_ARN}/invocations?qualifier=DEFAULT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_templates",
      "arguments": {}
    },
    "id": 2
  }'
```

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

## Option 4: Generative AI Use Cases on AWS (GenU) Integration

> **Note:** [Generative AI Use Cases on AWS (GenU)](https://github.com/aws-samples/generative-ai-use-cases-jp) is a separate open-source project under active development. The steps below are based on GenU v5.x as of April 2026 and may change in future releases.

[GenU](https://github.com/aws-samples/generative-ai-use-cases-jp) is an open-source web application that provides various generative AI use cases (chat, RAG, image generation, etc.) on AWS. GenU provides two ways to use AgentCore:

| | AgentCore Chat | AgentBuilder |
|---|---|---|
| UI | Built-in chat page | Custom agent creation page |
| MCP config | `mcp-configs/generic/mcp.json` | `mcp-configs/agent-builder/mcp.json` |
| System prompt | Fixed (from `config.py`) | Customizable per agent |
| CDK option | `createGenericAgentCoreRuntime: true` | `agentBuilderEnabled: true` |

Both share the same Docker image and Runtime backend. The difference is which `mcp.json` is loaded and whether the user can set a custom system prompt.

### Prerequisites

- GenU repository cloned and deployable (see [GenU README](https://github.com/aws-samples/generative-ai-use-cases-jp))
- Docker available on the build machine (required for AgentCore container image build)
- On x86_64 hosts (Intel/AMD), run `docker run --privileged --rm tonistiigi/binfmt --install arm64` before deploying (AgentCore requires ARM64 container images)
- Enable the use case(s) you want in `packages/cdk/cdk.json` or `parameter.ts`:
  - **AgentCore Chat:** `createGenericAgentCoreRuntime: true`
  - **AgentBuilder:** `agentBuilderEnabled: true`
  - You can enable both simultaneously

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

The sdpm entry is the same for both configs. Add it to the config(s) matching the use case(s) you enabled:

**AgentCore Chat** — `$GENU_RUNTIME_DIR/mcp-configs/generic/mcp.json`:

**AgentBuilder** — `$GENU_RUNTIME_DIR/mcp-configs/agent-builder/mcp.json`:

Add under `mcpServers`:

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

### How it works

```
User → GenU Web UI → Strands Agent (AgentCore Runtime)
                       ├── sdpm MCP tools (stdio)
                       │   ├── init_presentation
                       │   ├── generate_pptx → /tmp/ws/*.pptx
                       │   └── search_assets, analyze_template, ...
                       └── upload_file_to_s3_and_retrieve_s3_url
                           └── S3 URL → User
```

### Usage: AgentCore Chat

Works out of the box. The agent automatically discovers sdpm tools and receives `server_instructions`. Simply type your request:

```
AWS Lambdaについて1枚のエグゼクティブ向けスライドを作って
```

### Usage: AgentBuilder

When creating an agent in AgentBuilder, select `spec-driven-presentation-maker` from the MCP server list and set the following system prompt:

```
You are a presentation design assistant. Use the spec-driven-presentation-maker MCP tools to create PowerPoint slides.

Key rules:
- Always call read_workflows first to load the workflow before making any design decisions.
- When generating PPTX, pass the presentation JSON directly via the slides_json parameter of generate_pptx. Do NOT use Code Interpreter to write JSON files — the Code Interpreter sandbox is isolated from MCP tools and they cannot read each other's files.
- After generating the PPTX, upload it with upload_file_to_s3_and_retrieve_s3_url and provide the S3 URL as a Markdown link: [filename.pptx](S3_URL)
```

### Important: `slides_json` parameter

In AgentCore, the Code Interpreter runs in an isolated sandbox. Files written by Code Interpreter (`writeFiles`) are **not visible** to MCP tools like `generate_pptx`. Instead, pass the presentation JSON directly as a string:

```
generate_pptx(slides_json='{"template":"sample_template_dark","slides":[...]}', template="sample_template_dark")
```

This bypasses the filesystem entirely and works reliably in any environment.
