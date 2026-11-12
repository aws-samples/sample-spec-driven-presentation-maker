[English](programmatic-access.md) | [日本語](../ja/programmatic-access.md)

# Programmatic Access

Run your own automation against a Cloud deployment, for example a bot that turns every
AWS What's New post into a short deck, on cron, AWS Lambda or AWS Step Functions. The
automation creates decks **as you**: they appear in your deck list in the Web UI, with the
chat that created them.

You sign in once in a browser. The sign-in gives your automation a refresh token, and the
automation runs unattended from it until it expires (90 days by default). Then you sign in
again.

This needs the full stack (`stacks.agent` and `stacks.webUi`) with the default Cognito user
pool. It is not available with an external OIDC IdP (`auth.oidcDiscoveryUrl`).

## Turn it on

The programmatic client is off by default. Turn it on in `infra/config.yaml`:

```yaml
auth:
  programmaticClient:
    enabled: true
    refreshTokenValidityDays: 90   # 1–3650; default 90
```

Deploy all stacks (`SdpmAuth` creates the client; `SdpmAgent` and `SdpmWebUi` accept it).
The client is an OAuth native-app client (RFC 8252) in the Cognito user pool:

| Setting | Value |
|---|---|
| Client type | Public (no client secret) |
| Flow | Authorization code with PKCE |
| Callback and sign-out URL | `http://127.0.0.1:8765` only |
| Scopes | `openid profile email sdpm-mcp/invoke` |
| Refresh token | `refreshTokenValidityDays` (default 90 days), rotation off |

The Agent Runtime authorizer (`allowedClients`) and the REST API JWT authorizer
(`jwtAudience`) accept the client's ID. The MCP runtime checks the `sdpm-mcp/invoke`
scope, which the client's tokens carry. Turning the block off deletes the client, and every
refresh token it issued stops working.

Get the client ID from the `SdpmAuth` stack:

```bash
aws cloudformation describe-stacks --stack-name SdpmAuth \
  --query "Stacks[0].Outputs[?OutputKey=='ProgrammaticClientId'].OutputValue" --output text
# or: aws ssm get-parameter --name /sdpm/auth/programmatic-client-id --query Parameter.Value --output text
```

The client ID is not a secret: a public client has no secret, and the sign-in itself
proves who you are.

## The reference client

[`examples/programmatic-client/sdpm_client.py`](../../examples/programmatic-client/sdpm_client.py)
is a single-file client that uses only this contract. Copy it into your own project and
change it as you need. It needs [uv](https://docs.astral.sh/uv/) (or Python 3.10+ with
`websockets` and `boto3`).

It reads the deployment's settings from the public `aws-exports.json` of the Web UI site
and takes three settings of its own, as options or environment variables:

| Option | Environment variable | Value |
|---|---|---|
| `--site` | `SDPM_SITE` | The Web UI URL (`https://xxxx.cloudfront.net`) |
| `--client-id` | `SDPM_CLIENT_ID` | The programmatic client ID |
| `--store` | `SDPM_TOKEN_STORE` | Where the refresh token lives: `file:<path>` (default `~/.config/sdpm-programmatic-client/token.json`) or `secretsmanager:<name or ARN>` |

`login` saves these three settings (no token) in
`~/.config/sdpm-programmatic-client/config.json`, so later commands need no options.

Every command prints one JSON object. Exit codes: `0` success (whatever the `state`),
`1` error, `2` usage, `3` the refresh token is expired, revoked or invalid (sign in again).

### login

```bash
cd examples/programmatic-client
uv run sdpm_client.py login --site https://xxxx.cloudfront.net --client-id <client id>
```

The client opens the Cognito sign-in page in your browser and waits up to 5 minutes for one
redirect on `127.0.0.1:8765`. It listens on loopback only and stops after that redirect.
It then stores the refresh token in a file only you can read (mode 0600), outside the
repository. `--no-browser` prints the URL instead of opening it.

To give the token to a Lambda function or another headless runner, store it straight in
AWS Secrets Manager; nothing is written to disk then:

```bash
uv run sdpm_client.py login --site https://xxxx.cloudfront.net --client-id <client id> \
  --store secretsmanager:sdpm/whatsnew-bot
```

The client updates the secret, or creates it when it does not exist. It needs
`secretsmanager:PutSecretValue` (and `secretsmanager:CreateSecret` for a new secret) with
your AWS credentials. The secret holds JSON: `refresh_token`, `client_id` and
`obtained_at` (Unix time of the sign-in).

### run

```bash
uv run sdpm_client.py run "Make a 3-slide deck for the team about <topic>. Do not ask questions; decide on reasonable defaults and build the PPTX."
# {"sessionId": "c6c289e49e9c05b2-0f8c6a4e-...", "accepted": "turn"}
```

`run` gets fresh tokens, opens a new session, sends the prompt in `vibe` mode and
disconnects as soon as the agent accepts it (2–4 seconds). The agent keeps working. Keep
the printed `sessionId`. `-` reads the prompt from stdin.

Write the prompt so the agent does not need to ask anything: nobody is there to answer.

### status

```bash
uv run sdpm_client.py status c6c289e49e9c05b2-0f8c6a4e-...
# {"sessionId": "...", "state": "done", "working": false, "how": "finished", "reclaimed": false,
#  "deckId": "...", "name": "...", "slideCount": 4, "hasPptx": true, "pptxUrl": "https://..."}
```

`status` asks the session whether its work period has ended and how, then reads the deck.
`state` is one of:

| `state` | Meaning |
|---|---|
| `running` | The agent is still working. A PPTX may already exist, but the agent can still change it or rebuild it under a new name. |
| `done` | The work period ended normally and the deck has a PPTX. |
| `needs_input` | The work period ended normally without a PPTX. Most likely the agent asked a question: open the deck's chat in the Web UI. |
| `failed` | The work period ended on an error, the one-hour limit, or a restart of the agent. |
| `cancelled` | Someone pressed stop in the Web UI. |

Every state except `running` is final. Poll once a minute or less often, and stop at a
final state. On dev a deck of 3 slides took 4–6 minutes. Take `pptxUrl` from the
`done` answer: it is a signed download link that expires after a short time.

The agent releases a session 15 minutes after the last connection to it (`"reclaimed":
true`). Nobody is working on a released session, so `status` reports `done` when its deck
has a PPTX and `needs_input` when it has none. Asking about a released session starts a
new agent instance for it, which takes about 2 seconds.

## The contract

A client of your own can rely on the following. Everything else (other `/ws` messages,
event fields, REST fields not listed here) may change without notice.

**Settings.** `https://<site>/aws-exports.json` has `authority` (the user pool issuer;
`<authority>/.well-known/openid-configuration` lists the authorization and token
endpoints), `agentRuntimeArn`, `apiBaseUrl` and `awsRegion`. The programmatic client ID is
the `ProgrammaticClientId` output of `SdpmAuth` (SSM `/sdpm/auth/programmatic-client-id`).

**Tokens.** Sign in with the authorization code flow and PKCE (`S256`), scope
`openid profile email sdpm-mcp/invoke`, redirect URI `http://127.0.0.1:8765`. The
`refresh_token` grant at the token endpoint returns an access token and an ID token (valid
for 60 minutes). Use the access token for `/ws` and the ID token for the REST API. A
refused refresh token is an HTTP 400 with `"error": "invalid_grant"`.

**Session id.** One new id per job: the first 16 hex characters of SHA-256 over the
token's `sub`, a hyphen, and a random UUID
(`c6c289e49e9c05b2-0f8c6a4e-2b1d-4c3e-9a7f-5d6e7f8a9b0c`). The agent refuses an id with
another user's prefix.

**Starting a job (`/ws`).**

- URL: `wss://bedrock-agentcore.<region>.amazonaws.com/runtimes/<URL-encoded agentRuntimeArn>/ws?qualifier=DEFAULT&X-Amzn-Bedrock-AgentCore-Runtime-Session-Id=<session id>`
- Subprotocols: `base64UrlBearerAuthorization.<base64url of the access token, no padding>`
  and `base64UrlBearerAuthorization`.
- The client speaks first. Send
  `{"type": "prompt", "id": "<up to 64 characters>", "prompt": "<text>", "mode": "vibe"}`.
- The agent answers `{"ctl": "accepted", "id": "...", "as": "..."}`, or
  `{"ctl": "error", "code": "...", "error": "..."}`.
- Disconnecting never cancels the job. To stay connected and watch instead, send
  `{"type": "ping"}` at least every 25 seconds and turn off the WebSocket library's
  protocol pings. The job's work period has ended when an event arrives with
  `"ev": {"work": {"state": "idle", "how": "..."}}`. Events can come grouped in
  `{"batch": [...]}` frames or split across `{"chunk": ...}` frames that concatenate to the
  event's JSON.

**Knowing the job has ended (`/ws`).** The job is complete when the session's work period
has ended, not when the deck first has a PPTX: the agent can keep working after that and
rebuild the PPTX under a new name. The orchestrator's `turnEnd` event is not the end
either: slide composing continues in the background after it.

- Connect to the session's URL as above and send `{"type": "resume", "from_seq": <n>}`.
  The agent answers `{"ctl": "resumeAck", "working": ..., "head": ..., "replay_from": ...}`,
  then sends the session's events numbered after `n` (`{"seq": ..., "ev": ...}`) in the
  current or last work period.
- `"working": true`: the job is still running.
- `"working": false` with `"head"` above 0: the period has ended, and its last event is
  `{"work": {"state": "idle", "how": "..."}}`. Send `resume` again with `from_seq` a few
  below `head` to read it. `how` is `finished`, `cancelled`, `error`, `watchdog` (the
  one-hour limit) or `sigterm` (the agent restarted). If the replay holds no such event,
  treat the job as still running.
- `"working": false` with `"head": 0`: the agent no longer holds the session (released after
  being idle). Nobody is working on it.
- Ask no more often than once a minute. Each connection to a released session starts an
  agent instance for it.

**Finding the deck (REST, `Authorization: Bearer <ID token>`).**

- `GET <apiBaseUrl>/decks`: the items carry `chatSessionId`; the job's deck is the one
  whose `chatSessionId` equals the job's session id.
- `GET <apiBaseUrl>/decks/<deckId>`: `slideCount` and `pptxUrl` (set when the deck has a
  PPTX). Read it after the work period has ended, and take the download link from that
  answer.

## Lambda and Step Functions

Cognito has no device-code flow, so the first sign-in always needs a browser. A headless
runner uses the refresh token you stored in Secrets Manager with `login --store
secretsmanager:<name>`.

**Lambda function.** Package `sdpm_client.py` with `websockets` (`boto3` is in the Lambda
Python runtime), for example
`uv pip install --target package websockets && cp sdpm_client.py package/`. Handler:

```python
import sdpm_client as sdpm


def handler(event, context):
    # SDPM_SITE, SDPM_CLIENT_ID and SDPM_TOKEN_STORE=secretsmanager:sdpm/whatsnew-bot
    settings = sdpm.Settings.resolve()
    if event["action"] == "start":
        return sdpm.start_job(settings, event["prompt"])
    return sdpm.job_status(settings, event["sessionId"])
```

Set the timeout to 3 minutes. The execution role needs `secretsmanager:GetSecretValue` on
that one secret (and `kms:Decrypt` on its key when it is a customer managed key), and
nothing else: the function calls SDPM with your tokens over HTTPS, not with IAM. If the
deployment restricts IP addresses with WAF, the function's outbound addresses must be
allowed.

**State machine.** Start the job, poll once a minute while it is `running`, succeed on
`done`, fail on any other final state, and send an alert when the refresh token has
expired. A refused refresh token raises `RefreshTokenExpired`, which Step Functions sees as
the error name:

```json
{
  "Comment": "One deck from a prompt, created as the signed-in user",
  "TimeoutSeconds": 3600,
  "StartAt": "Start",
  "States": {
    "Start": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": { "FunctionName": "<function ARN>", "Payload": { "action": "start", "prompt.$": "$.prompt" } },
      "OutputPath": "$.Payload",
      "Catch": [{ "ErrorEquals": ["RefreshTokenExpired"], "Next": "SignInAgain" }],
      "Next": "Wait"
    },
    "Wait": { "Type": "Wait", "Seconds": 60, "Next": "Status" },
    "Status": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": { "FunctionName": "<function ARN>", "Payload": { "action": "status", "sessionId.$": "$.sessionId" } },
      "OutputPath": "$.Payload",
      "Catch": [{ "ErrorEquals": ["RefreshTokenExpired"], "Next": "SignInAgain" }],
      "Next": "Done?"
    },
    "Done?": {
      "Type": "Choice",
      "Choices": [
        { "Variable": "$.state", "StringEquals": "done", "Next": "Done" },
        { "Variable": "$.state", "StringEquals": "running", "Next": "Wait" }
      ],
      "Default": "NotDone"
    },
    "Done": { "Type": "Succeed" },
    "NotDone": { "Type": "Fail", "Error": "DeckNotDone", "Cause": "needs_input, failed or cancelled: open the deck's chat in the Web UI" },
    "SignInAgain": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "<alert topic ARN>",
        "Message": "The SDPM refresh token has expired. Run: sdpm_client.py login --store secretsmanager:sdpm/whatsnew-bot"
      },
      "Next": "Failed"
    },
    "Failed": { "Type": "Fail", "Error": "RefreshTokenExpired" }
  }
}
```

Start it from an Amazon EventBridge schedule, once per item. To be reminded before the
token expires instead of after, compare the secret's `obtained_at` with
`refreshTokenValidityDays` in a scheduled check. Refresh-token rotation stays off: one
token lasts its full validity, and the runner never has to write the secret.

## Security notes

- **A refresh token is everything you can do in the chat.** Whoever holds it can create,
  read and delete your decks and use the agent as you, until it expires. Treat it like a
  password.
- **Store it encrypted.** Use the 0600 file on your own machine, or Secrets Manager (encrypted
  with AWS KMS; with a customer managed key, the key policy limits who can decrypt). Never
  put it in the repository, in environment variables of shared systems, or in a container
  image.
- **Least privilege.** Only the runner's role may read the stored token, with `GetSecretValue` on that
  one secret ARN. Your own credentials write it at `login`.
- **Never log tokens.** The reference client prints no token and no authorization code. Do
  not log the secret value, the token endpoint responses or the `/ws` URL with its
  subprotocol. Step Functions history holds only session ids and deck details; `pptxUrl` is
  a short-lived signed link.
- **Sign-in.** The loopback listener binds `127.0.0.1` only, accepts one redirect and stops.
  PKCE and the `state` value tie the redirect to the sign-in that started it.
- **Revoking.** `aws cognito-idp admin-user-global-sign-out --user-pool-id <id> --username <user>`
  revokes all of the user's refresh tokens (Web UI sessions included). Turning
  `auth.programmaticClient` off deletes the client and every token it issued.
- **Audit.** Access tokens carry the programmatic client's ID in `client_id`, so calls made by
  automation can be told apart from Web UI calls.

See also [Security](security.md) and
[Architecture — Authentication and Authorization Model](architecture.md#authentication-and-authorization-model).
