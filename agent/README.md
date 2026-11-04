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
(spec-driven-presentation-maker MCP)      MCP Servers
```

Each session's agent is assembled by `factory.py` for its session handle, which:

1. Initializes MCP server connections (3 patterns)
2. Collects `server_instructions` from each MCP server
3. Injects instructions into the system prompt (MCP spec compliance)
4. Registers built-in tools alongside MCP tools

---

## Session Runtime

`basic_agent.py` serves two entries on one session runtime (`session_runtime.py`):

- **`/ws`** (`ws_entry.py`) — the Web UI's WebSocket. Client messages: `prompt`, `steer`,
  `cancel`, `resume(from_seq)`, `prepare`, `ping`. The server answers with control frames
  (`accepted`, `cancelAck`, `resumeAck`, `prepareAck`, `ready`, `pong`, `keepalive`, `error`)
  and the session's events as `{"seq", "ev"}`, where `ev` has the shapes of the HTTP stream
  plus `work` (busy / idle), `turn`, `turnEnd` and `steer`. Frames stay under 24,000 bytes
  (`{"batch": [...]}`, or `{"chunk", ...}` for a large event) and go out at most one per
  20 ms. The client speaks first; the session is admitted from the forwarded
  `Authorization` header on the first message and its owner checked on every message.
- **`/invocations`** — HTTP streaming for Local and external clients, with the events and
  the behaviour it always had for the turns it starts.

A session keeps its MCP clients, Agent and Memory session manager across turns
(`session_handle.py`; the JWT is swapped per turn through `token_holder.py`). It is
*working* while a turn runs or a follow-on turn is queued; a work period holds HealthyBusy
on `/ping`. A message sent while working is a steer (`steer_inbox.py`): it is added to the
next user message of the running turn before Memory stores it, or continues the turn when it
would end, or becomes a new turn when it arrives after the end. Every event is numbered in
the session's ring (`event_ring.py`), so a client that reconnects asks for what it missed.

What stops a turn: the stop button (`cancel`, which first discards the steers not yet
delivered), the 60-minute watchdog of a work period, and SIGTERM. A disconnect never does.
While a synchronous `compose_slides` runs, a steer reaches the orchestrator after it returns.

---

## MCP Server Patterns

Three connection patterns are supported. Each returns an `MCPClient` instance added to the agent's `tools` list.

### Pattern 1: AgentCore Runtime + JWT Bearer

For MCP servers deployed on Amazon Bedrock AgentCore Runtime. The caller's JWT is forwarded as-is for authentication and user_id propagation, and the caller's session id is forwarded as `Mcp-Session-Id`, with the owner prefix of the token's user, so that AgentCore routes the requests of one session to the same microVM.

```python
def _mcp_agentcore_runtime(jwt_token: str, session_id: str = "") -> MCPClient:
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    runtime_arn = os.environ["MCP_RUNTIME_ARN"]
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"

    headers = {"Authorization": f"Bearer {jwt_token}"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    return MCPClient(
        lambda: streamablehttp_client(
            url=url,
            headers=headers,
            timeout=120,
            terminate_on_close=False,
        ),
    )
```

> Do not omit `Mcp-Session-Id`. AgentCore mints a fresh session id for any request
> that arrives without one, which puts every request on a new microVM and makes it
> pay a new-session start. Measured against this project's MCP runtime in
> `ap-northeast-1`: 0.18-0.20s with a consistent id, versus 17.6-19.7s with no id
> when no warm capacity was available.

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
    tools=[*mcp_servers, web_fetch],
    ...
)
```

---

## Built-in Tools

In addition to MCP tools, the agent includes built-in tools defined locally:

| Tool | Module | Description |
|---|---|---|
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

---

## Directory Structure

```
agent/
├── basic_agent.py          # Main agent (entrypoint)
├── tools/
│   └── web_tools.py        # web_fetch
├── pyproject.toml          # dependencies (locked in the root uv.lock)
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
| [Developer guide](../docs/en/developer-guide.md) | Checkout setup and CDK deployment |
| [Connecting Agents](../docs/en/add-to-gateway.md) | AgentCore Gateway and MCP client configuration |
