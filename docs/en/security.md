# Security

## This is sample code

This project is sample code for demonstration and education. It is not meant for production
use as is. Work with your security and legal teams to meet your organization's security,
regulatory and compliance requirements before you deploy it.

## What the AWS stack sets up

These settings come with every deployment of the CDK stacks in `infra/`:

- **S3 buckets** (decks and resources): Block Public Access, server-side encryption
  (SSE-S3), and a bucket policy that refuses requests without TLS. The deck bucket writes
  server access logs under `access-logs/`. Versioning is not enabled.
- **DynamoDB**: encryption at rest with an AWS-managed key, and point-in-time recovery.
- **Web UI API** (API Gateway HTTP API `SdpmHttpApi`, Layer 4): a Cognito JWT authorizer on
  every route. Only the CORS preflight (`OPTIONS`) is open.
- **MCP discovery API** (API Gateway HTTP API `sdpm-mcp-discovery`): created whenever the
  stack uses its own Cognito user pool, which is the default and the One-Click Deploy setup.
  It lets external MCP clients find the OAuth settings and sign in (see
  [Connecting Agents](add-to-gateway.md)). Its routes (`/.well-known/*`, `/authorize`,
  `/token`, `/register`, `/` and `/mcp`) have no API Gateway authorizer, and the WAF IP restriction
  is not attached to it. `/` and `/mcp` refuse requests without a bearer token and forward the
  token to the MCP runtime, which validates it. `/register` is open Dynamic Client
  Registration: any caller can create a Cognito app client (see the review list below).
- **CloudFront**: Origin Access Control for the site bucket and for slide previews, and a
  redirect from HTTP to HTTPS.
- **AgentCore Runtime**: the agent and MCP runtimes validate a JWT on every call
  (`customJwtAuthorizer`). The user ID comes from the token's `sub` claim. A resource-based
  policy on each runtime and its endpoints allows only `InvokeAgentRuntime` and
  `StopRuntimeSession`, the operations the app uses. The agent and the MCP server admit a
  session only for its owner: the session id carries a prefix derived from the token's
  `sub`, and each runtime process serves one user (`shared/session_owner.py`).
- **Per-deck authorization**: a user is the deck's owner, a viewer (the deck is public), or
  has no access. The rules live in one place, `shared/authz.py`, used by both the API and the
  MCP server. See [Architecture — Authorization](architecture.md#authorization-role-based-access-control).
- **IAM**: one role per runtime and service. Some statements use `resources: ["*"]` where
  the resource ARN is not known at synth time or the action has no resource scope. Review
  these before production.
- **Secrets**: no credentials in the code. Services get access through IAM roles and
  environment variables.
- **Logs**: the CloudWatch log groups the stacks define keep logs for one week or one month.
  AgentCore creates the runtime log groups (`/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT`)
  itself; the stacks give them the retention set in `observability.logRetentionDays`
  (default 30 days). These groups hold conversation text: the Strands tracer records
  messages as span events, and the OpenTelemetry exporter writes them to the
  `otel-rt-logs` stream of the agent runtime log group. Bedrock request and response
  bodies from the botocore instrumentation are not recorded
  (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` on both runtimes). Bedrock
  model invocation logging is optional (`features.enableInvocationLogging`).

## Settings that depend on your environment

These controls depend on your organization's environment, network or policy, so the
sample cannot set safe defaults for them. Evaluate each one before production use.

1. **AWS CloudTrail** is an account-level setting. Enable it separately so that existing
   CloudTrail configurations are not disturbed.
2. **VPC endpoints for S3 and DynamoDB** matter only if you deploy inside a VPC. This stack
   does not use a VPC.
3. **AWS WAF IP restrictions** are built in, but the IP ranges are yours to choose. Set
   `waf.allowedIpV4AddressRanges` / `waf.allowedIpV6AddressRanges` in `config.yaml`, or pass
   `--waf-ipv4` / `--waf-ipv6` to `deploy.sh`. See the
   [Developer guide](developer-guide.md#waf-ip-address-restriction).
4. **CORS** should be narrowed to your own domain.
5. **S3 access logs**: the deck bucket already writes server access logs into itself. Where
   logs should be kept, and for how long, is your choice.
6. **Cognito advanced security** (MFA, compromised-credential detection) is off by default
   to keep the demo simple.
7. **Cognito self sign-up** is off by default (`auth.selfSignUp: false`): an administrator
   creates the users ([Deploy guide](deploy-cloudshell.md#creating-a-cognito-user-layer-4)).
   With `auth.selfSignUp: true`, anyone who reaches the sign-in page can create an account
   and use the Bedrock-backed agent. To accept only your organization's addresses, list its
   email domains in `auth.allowedEmailDomains`; a Cognito Pre sign-up Lambda trigger checks
   each sign-up request ([Developer guide](developer-guide.md#default-amazon-cognito-user-pool)).
8. **Open Dynamic Client Registration** (`auth.enableDCR`, default `true`): the discovery
   API's `/register` creates a Cognito app client for any caller. This suits personal and
   demo use. To allow only known MCP clients, set `auth.enableDCR: false` and list their
   callback URLs in `auth.mcpCallbackUrls`
   ([Connecting Agents](add-to-gateway.md#connection-method-b-static-client-registration-authmcpcallbackurls)).
9. **Bedrock model and region**: if data residency matters, avoid cross-region inference
   profiles.

### AgentCore runtime platform versions

The MCP runtime runs on `platformVersion` V2 (`infra/lib/runtime-stack.ts`); the agent
runtime runs on V1. V2 restores every instance from one snapshot taken after startup, so
whatever the process holds at that point is the same in every instance. The MCP server
keeps only static data there (imported modules, parsed AWS API definitions, the bundled
styles and role documents); it builds AWS clients, resolves credentials and opens
connections on the first request after a restore. Values this stack takes from the kernel
are not affected: `uuid.uuid4()` and `secrets` read `getrandom(2)` on every call, and SigV4
signing is HMAC-based and deterministic.

What remains is OpenSSL's own DRBG behind outbound TLS from the MCP runtime: seeded before
the snapshot, it starts from the same state in every restored instance. Swapping in a
snapshot-safe OpenSSL build does not change that, because AgentCore Runtime does not reseed
those builds after a restore
([Optimize for V2](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-v2-optimize.html)).
This sample accepts the risk. If your organization does not, set `platformVersion` to `"V1"`
in `infra/lib/runtime-stack.ts`; the MCP server runs on both.

## Local install

The local Web UI (`sdpm webui`, or `npm run dev:local` in a checkout) has no sign-in. It is
meant for one user on one computer:

- It listens on `127.0.0.1` only, so other machines cannot reach it.
- It refuses POST requests whose `Origin` is another site. A web page open in the same
  browser cannot drive the local agent, upload files, or change styles and templates.

The local MCP server talks to its client over stdio and opens no network port.

## HTML decks

An HTML deck runs scripts, so SDPM never serves it from the Web UI's own origin. Each deck
carries a Content-Security-Policy that allows only the scripts it was built with and blocks
network access. The Web UI plays decks in a sandboxed iframe. The cloud stack serves them
through S3 presigned URLs that expire after 15 minutes (4 hours for **Present**). For the
details and the accepted risks, see
[Architecture — HTML Deck Security](architecture.md#html-deck-security).

## Reporting a vulnerability

If you find a potential security issue, do not open a public GitHub issue. Follow the
process in [CONTRIBUTING.md](../../CONTRIBUTING.md#security-issue-notifications).
