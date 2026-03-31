> 📝 [日本語版 README はこちら](README_ja.md)

# Agent — Spec-Driven Presentation Maker

Layer 4 agent built with [Strands Agents](https://github.com/strands-agents/sdk-python), deployed on [Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html). Connects to MCP servers for presentation tools, AWS documentation, and pricing data, with built-in file upload and web fetch capabilities.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Amazon Bedrock AgentCore Runtime                       │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Strands Agent (basic_agent.py)                   │  │
│  │                                                   │  │
│  │  ┌─────────────┐  ┌────────────┐  ┌───────────┐  │  │
│  │  │ MCP Servers  │  │ Built-in   │  │ Bedrock   │  │  │
│  │  │ (3 patterns) │  │ Tools      │  │ Memory    │  │  │
│  │  └──────┬───┬──┘  └────────────┘  └───────────┘  │  │
│  └─────────┼───┼─────────────────────────────────────┘  │
│            │   │                                        │
└────────────┼───┼────────────────────────────────────────┘
             │   │
   ┌─────────┘   └──────────┐
   ▼                        ▼
AgentCore Runtime     Public / Local
(pptx-maker MCP)      MCP Servers
```

The agent is created via `create_agent()`, which:

1. Initializes MCP server connections (3 patterns)
2. Collects `server_instructions` from each MCP server
3. Injects instructions into the system prompt (MCP spec compliance)
4. Registers built-in tools alongside MCP tools

---

## MCP Server Patterns

Three connection patterns are supported. Each returns an `MCPClient` instance added to the agent's `tools` list.

### Pattern 1: AgentCore Runtime + JWT Bearer

For MCP servers deployed on Amazon Bedrock AgentCore Runtime. The caller's JWT is forwarded as-is for authentication and user_id propagation.

```python
def _mcp_agentcore_runtime(jwt_token: str) -> MCPClient:
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    runtime_arn = os.environ["MCP_RUNTIME_ARN"]
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"

    return MCPClient(
        lambda: streamablehttp_client(
            url=url,
            headers={"Authorization": f"Bearer {jwt_token}"},
            timeout=120,
            terminate_on_close=False,
        ),
    )
```

### Pattern 2: Public Remote MCP (no auth)

For publicly accessible MCP servers. No authentication required.

```python
def _mcp_aws_knowledge() -> MCPClient:
    return MCPClient(
        lambda: streamablehttp_client(url="https://knowledge-mcp.global.api.aws"),
    )
```

### Pattern 3: Local stdio MCP

For MCP servers that run as local processes using stdio transport.

```python
def _mcp_aws_pricing() -> MCPClient:
    from mcp.client.stdio import StdioServerParameters, stdio_client

    return MCPClient(
        lambda: stdio_client(StdioServerParameters(
            command="awslabs.aws-pricing-mcp-server",
            env={**os.environ, "AWS_REGION": "us-east-1", "FASTMCP_LOG_LEVEL": "ERROR"},
        )),
    )
```

### Registering MCP Servers

All MCP clients are passed to the agent in `create_agent()`:

```python
mcp_servers = [
    _mcp_agentcore_runtime(jwt_token=jwt_token),  # Pattern 1
    _mcp_aws_knowledge(),                          # Pattern 2
    _mcp_aws_pricing(),                            # Pattern 3
]

agent = Agent(
    tools=[*mcp_servers, read_uploaded_file, list_uploads, web_fetch],
    ...
)
```

---

## Built-in Tools

In addition to MCP tools, the agent includes built-in tools defined locally:

| Tool | Module | Description |
|---|---|---|
| `read_uploaded_file(upload_id)` | `tools/upload_tools.py` | Read content of an uploaded file |
| `list_uploads(session_id)` | `tools/upload_tools.py` | List all uploads in a session |
| `web_fetch(url)` | `tools/web_tools.py` | Fetch a web page as Markdown |

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `MCP_RUNTIME_ARN` | L3 MCP Server Runtime ARN | (required) |
| `COGNITO_DOMAIN` | Amazon Cognito M2M domain (from L3) | (required for M2M) |
| `M2M_CLIENT_ID` | Amazon Cognito M2M client ID | (required for M2M) |
| `M2M_CLIENT_SECRET_NAME` | AWS Secrets Manager name for client secret | (required for M2M) |
| `M2M_SCOPE` | OAuth scope | `sdpm/invoke` |
| `MEMORY_ID` | Bedrock AgentCore Memory ID | `""` |
| `MODEL_ID` | Bedrock model ID | `global.anthropic.claude-sonnet-4-6` |
| `AWS_REGION` / `AWS_DEFAULT_REGION` | AWS region | `us-east-1` |
| `DECKS_TABLE` | DynamoDB table name | (required) |
| `PPTX_BUCKET` | S3 bucket name | (required) |

---

## Directory Structure

```
agent/
├── basic_agent.py          # Main agent (entrypoint)
├── tools/
│   ├── upload_tools.py     # read_uploaded_file, list_uploads
│   └── web_tools.py        # web_fetch
├── requirements.txt
├── Dockerfile
└── __init__.py
```

---

## Docker

Build:

```bash
docker build -t sdpm-agent .
```

- Exposes port **8080**
- Entrypoint: `opentelemetry-instrument python -m basic_agent`
- Health check: `http://localhost:8080/ping` (30s interval, 3 retries)

---

## Documentation

| Document | Description |
|---|---|
| [Architecture](../docs/en/architecture.md) | 4-layer design, data flow, auth model |
| [Getting Started](../docs/en/getting-started.md) | Setup and deployment for Layer 1–4 |
| [Connecting Agents](../docs/en/add-to-gateway.md) | AgentCore Gateway and MCP client configuration |
