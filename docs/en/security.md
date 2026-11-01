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
- **API Gateway** (HTTP API): a Cognito JWT authorizer on every route. Only the CORS
  preflight (`OPTIONS`) is open.
- **CloudFront**: Origin Access Control for the site bucket and for slide previews, and a
  redirect from HTTP to HTTPS.
- **AgentCore Runtime**: the agent and MCP runtimes validate a JWT on every call
  (`customJwtAuthorizer`). The user ID comes from the token's `sub` claim.
- **Per-deck authorization**: a user is the deck's owner, a viewer (the deck is public), or
  has no access. The rules live in one place, `shared/authz.py`, used by both the API and the
  MCP server. See [Architecture — Authorization](architecture.md#authorization-role-based-access-control).
- **IAM**: one role per runtime and service. Some statements use `resources: ["*"]` where
  the resource ARN is not known at synth time or the action has no resource scope. Review
  these before production.
- **Secrets**: no credentials in the code. Services get access through IAM roles and
  environment variables.
- **Logs**: CloudWatch log groups keep logs for one week or one month. Bedrock model
  invocation logging is optional (`features.enableInvocationLogging`).

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
7. **Bedrock model and region**: if data residency matters, avoid cross-region inference
   profiles.

### Only if you switch AgentCore runtimes to platformVersion V2

This stack runs the AgentCore runtimes on V1. CloudFormation and the CDK cannot set the
`platformVersion` field, so a deployment of this sample does not use V2.

V2 restores every instance from one snapshot. A userspace random number generator seeded
before the snapshot is then shared across instances. Values this stack takes from the
kernel are not affected: `uuid.uuid4()` and `secrets` read `getrandom(2)` on every call, and
SigV4 signing is HMAC-based and deterministic. The exposure is limited to OpenSSL's own
DRBG behind outbound TLS. If you enable V2, replace the MCP runtime's OpenSSL with a
snapshot-safe build (`openssl-snapsafe-libs` on Amazon Linux 2023; it conflicts with
`openssl-libs` and needs `--allowerasing`), or use an AWS-provided base image that already
ships one.

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
