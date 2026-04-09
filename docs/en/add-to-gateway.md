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
