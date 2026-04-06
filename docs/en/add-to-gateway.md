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
