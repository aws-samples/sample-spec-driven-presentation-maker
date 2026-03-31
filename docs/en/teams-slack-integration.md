[EN](../en/teams-slack-integration.md) | [JA](../ja/teams-slack-integration.md)

# Microsoft Teams & Slack Integration

This guide explains how to use the Layer 4 Agent of Spec-Driven Presentation Maker directly from Microsoft Teams or Slack.

## Overview

The Layer 4 Agent exposes an HTTPS endpoint on Amazon Bedrock AgentCore Runtime, callable via `POST /invocations` with JWT Bearer authentication. By calling this Agent directly from a Slack Bot or Teams Bot, you can generate presentations from within your chat platform.

```
Teams / Slack
  ↓ Webhook / Bot Event
API Gateway + Lambda (bot handler)
  ↓ HTTPS + JWT Bearer (SSE streaming)
AgentCore Runtime (spec-driven-presentation-maker Agent — Layer 4)
  ↓ MCP
AgentCore Runtime (spec-driven-presentation-maker MCP Server — Layer 3)
  ↓
DynamoDB + S3 (decks, PPTX, previews)
```

The Layer 4 Agent has workflow constraints (Phase 1 → 2 → 3), MCP tool connections, and session management built in. The bot handler does not need to implement any AI logic — its only responsibilities are "message relay" and "SSE response reading."

## Prerequisites

- spec-driven-presentation-maker Layer 3 + Layer 4 deployed (see [Getting Started — Layer 4](getting-started.md#layer-4-full-stack-aws))
- Authentication infrastructure capable of obtaining JWT tokens (see [Getting Started — Authentication Options](getting-started.md#authentication-options) for details)

---

## Calling the Agent Runtime

For both Teams and Slack, the bot handler calls the Agent Runtime in the following format.

### Endpoint

```
POST https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{ENCODED_ARN}/invocations?qualifier=DEFAULT
```

| Header | Value |
|---|---|
| `Content-Type` | `application/json` |
| `Authorization` | `Bearer {JWT_TOKEN}` |

### Request Body

```json
{
  "prompt": "Create a 5-slide presentation about AWS Well-Architected",
  "runtimeSessionId": "slack-U12345-1710000000",
  "userId": "user-sub-from-jwt"
}
```

Setting `runtimeSessionId` per user+channel enables conversation continuity.

### Response

An SSE (Server-Sent Events) stream. Text chunks, tool execution status, and final results are returned sequentially.

```
data: {"event":{"contentBlockDelta":{"delta":{"text":"Creating slides"}}}}
data: {"toolStart":{"name":"init_presentation","toolUseId":"abc123"}}
data: {"toolResult":{"toolUseId":"abc123","status":"success","content":"{\"deckId\":\"a1b2c3d4\"}"}}
data: {"keepalive":true}
```

The bot handler reads the SSE stream to completion and concatenates text chunks to build the final message.

### Getting a JWT Token

#### Default Amazon Cognito (client_credentials flow)

```python
import base64
import json
import urllib.request

creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
req = urllib.request.Request(
    f"https://{COGNITO_DOMAIN}/oauth2/token",
    data=b"grant_type=client_credentials&scope=sdpm/invoke",
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {creds}",
    },
)
with urllib.request.urlopen(req) as resp:
    token = json.loads(resp.read())["access_token"]
```

Store the client secret in AWS Secrets Manager and cache it during AWS Lambda execution.

---

## Slack Integration

### Method 1: Slack Bolt + Lambda (Recommended)

Build a Lambda-based bot using [Slack Bolt for Python](https://slack.dev/bolt-python/).

#### 1. Create a Slack App

1. [Slack API](https://api.slack.com/apps) → Create New App
2. Add the following scopes under OAuth & Permissions:
   - `app_mentions:read` — Detect mentions
   - `chat:write` — Send messages
   - `files:write` — Upload PPTX files (optional)
3. Enable Event Subscriptions:
   - Subscribe to the `app_mention` event
   - Set the Request URL to your Amazon API Gateway endpoint
4. Install to your workspace and obtain the Bot Token

#### 2. AWS Lambda Handler

```python
import json
import os
import urllib.request

from slack_bolt import App
from slack_bolt.adapter.aws_lambda import SlackRequestHandler

app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    process_before_response=True,
)


def _invoke_agent(prompt: str, session_id: str) -> str:
    """Call the Layer 4 Agent and return the final text."""
    token = _get_oauth_token()  # Cognito client_credentials
    escaped_arn = urllib.request.quote(os.environ["AGENT_RUNTIME_ARN"], safe="")
    url = (
        f"https://bedrock-agentcore.{os.environ['AWS_REGION']}.amazonaws.com"
        f"/runtimes/{escaped_arn}/invocations?qualifier=DEFAULT"
    )
    body = json.dumps({
        "prompt": prompt,
        "runtimeSessionId": session_id,
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )

    # Read SSE stream and concatenate text
    text_parts = []
    with urllib.request.urlopen(req, timeout=540) as resp:
        buffer = b""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line_bytes, buffer = buffer.split(b"\n", 1)
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:].strip())
                    delta = (data.get("event", {})
                             .get("contentBlockDelta", {})
                             .get("delta", {})
                             .get("text"))
                    if delta:
                        text_parts.append(delta)
                except (json.JSONDecodeError, KeyError):
                    pass
    return "".join(text_parts)


@app.event("app_mention")
def handle_mention(event, say):
    """Receive a mention, forward to Agent, and reply."""
    user_message = event["text"]
    thread_ts = event.get("thread_ts", event["ts"])
    user_id = event["user"]

    session_id = f"slack-{user_id}-{thread_ts}"

    say(text="Working on it...", thread_ts=thread_ts)

    response = _invoke_agent(prompt=user_message, session_id=session_id)
    say(text=response, thread_ts=thread_ts)


def handler(event, context):
    """Lambda entry point."""
    slack_handler = SlackRequestHandler(app=app)
    return slack_handler.handle(event, context)
```

#### 3. Infrastructure

```
Slack Events API
  ↓ HTTPS POST
API Gateway (REST)
  ↓ Lambda Proxy
Slack Bolt Lambda
  ↓ HTTPS + JWT Bearer (SSE)
AgentCore Runtime (spec-driven-presentation-maker Agent)
```

Required environment variables:

| Variable | Description |
|---|---|
| `SLACK_BOT_TOKEN` | Slack Bot OAuth Token (`xoxb-...`) |
| `SLACK_SIGNING_SECRET` | Slack App Signing Secret |
| `AGENT_RUNTIME_ARN` | spec-driven-presentation-maker Agent's Amazon Bedrock AgentCore Runtime ARN |
| `AWS_REGION` | AWS Region |
| `COGNITO_DOMAIN` | Amazon Cognito domain (for token retrieval) |
| `M2M_CLIENT_ID` | Amazon Cognito M2M client ID |
| `M2M_CLIENT_SECRET_NAME` | AWS Secrets Manager secret name |

#### 4. Sharing PPTX Files (Optional)

To upload the generated PPTX directly to Slack:

```python
import requests

# Extract deckId from generate_pptx toolResult
pptx_url = f"https://{PPTX_BUCKET}.s3.amazonaws.com/pptx/{deck_id}/output.pptx"
# Or generate an S3 presigned URL

app.client.files_upload_v2(
    channel=channel,
    file=requests.get(pptx_url).content,
    filename=f"{deck_name}.pptx",
    thread_ts=thread_ts,
)
```

### Method 2: Slack Workflow Builder (Low-Code)

You can build the integration without coding using Slack's Workflow Builder + Webhook steps. However, since SSE streaming reading is required, Method 1 with an intermediate Lambda is recommended.

---

## Microsoft Teams Integration

### Method 1: Azure Bot Service + Lambda

1. [Azure Portal](https://portal.azure.com/) → Bot Services → Create
2. Set the messaging endpoint to your Lambda's Amazon API Gateway URL
3. Parse Teams Bot Framework messages in the AWS Lambda handler and forward to Agent Runtime
4. Register and distribute the app in Teams Admin Center

The bot handler structure is the same as the Slack version. Only replace the message parsing with the Bot Framework SDK.

### Method 2: Power Virtual Agents (Low-Code)

You can call the Agent Runtime using Microsoft Power Virtual Agents' "HTTP Request" action. However, SSE streaming processing is limited, so a configuration with an intermediate Lambda is recommended.

---

## Session Management

The Layer 4 Agent has built-in session management via Amazon Bedrock AgentCore Memory. By setting `runtimeSessionId` appropriately, conversation continuity is possible even on chat platforms.

| Platform | Recommended Session ID Format | Effect |
|---|---|---|
| Slack | `slack-{userId}-{threadTs}` | Conversation continues per thread |
| Teams | `teams-{aadObjectId}-{conversationId}` | Conversation continues per chat |

Calling with the same session ID causes the Agent to respond while retaining the previous conversation context.

---

## Security Notes

- Store Slack Bot Token / Signing Secret in AWS Secrets Manager
- Store Amazon Cognito client secrets in AWS Secrets Manager as well
- Use least-privilege OAuth scopes for the bot
- Tokens obtained via M2M (client_credentials) flow operate as a service account. If per-user access control is needed, implement a mechanism to obtain individual JWTs for each user

---

## Related Documents

- [Getting Started](getting-started.md) — Layer 3/4 setup and deployment
- [Connecting Agents](add-to-gateway.md) — Amazon Bedrock AgentCore Gateway connection
- [Architecture](architecture.md) — Authentication and authorization model details
