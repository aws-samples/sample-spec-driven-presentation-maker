> 📝 [日本語版 README はこちら](README_ja.md)

# Spec-Driven Presentation Maker

[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-yellow.svg)](LICENSE)

An open-source toolkit for creating presentations using a spec-driven approach.
Design "what to communicate" first, then let AI build "how to present it."

<!-- TODO: Replace with demo GIF/video after recording -->
<!-- ![Demo](docs/images/demo.gif) -->

---

## What is Spec-Driven Presentation?

Traditional slide creation follows a "open a blank slide and figure it out as you go" approach.
Without a clear structure, time is spent tweaking visuals while the core message gets diluted.

Spec-driven presentation applies the concept of Spec-Driven Development from software engineering to presentation creation.

| | Traditional | Spec-Driven |
|---|---|---|
| Starting point | Blank slide | Source materials and requirements |
| Design | Think while building | Define logical structure as a spec first |
| Build | Manual layout | AI builds automatically following the template |
| Quality | Ad hoc | Reviewable process based on the spec |

### Workflow

```
Phase 1                    Phase 2                    Phase 3
Spec                       Build Slides               Generate + Review

┌──────────────────┐    ┌────────────────┐      ┌────────────────┐
│ Briefing         │    │                │      │ Generate PPTX  │
│ Outline          │───▶│ Build slides   │─────▶│ Visual review  │
│ Art direction    │    │                │      │ Polish         │
└──────────────────┘    └────────────────┘      └────────────────┘
  User dialogue            specs/ → JSON            PPTX + Preview
```

---

## Quick Start

> **🚀 Want to try it quickly?** Deploy the full stack from CloudShell in minutes — no local CDK or Docker required.
> See [CloudShell Deploy Guide](docs/en/deploy-cloudshell.md).

### Layer 1: Kiro CLI Skill

Copy `skill/` to your Kiro CLI skills directory. The engine, references, and sample templates are all included.

### Layer 2: Local MCP Server

```bash
cd mcp-local && uv sync
```

Add to your MCP client config:

```json
{
  "mcpServers": {
    "spec-driven-presentation-maker": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-local", "python", "server.py"]
    }
  }
}
```

### Layer 3–4: AWS Deployment

```bash
cd infra
cp config.example.yaml config.yaml   # Enable/disable stacks
npm install && npx cdk deploy --all
```

For detailed setup instructions for each layer, see [Getting Started](docs/en/getting-started.md).

---

## Architecture

Built on a 4-layer architecture. Each layer is a thin wrapper around the previous one. Use only the layers you need.

| Use Case | Layer | AWS |
|---|---|:---:|
| Personal use with Kiro CLI | Layer 1: `skill/` | Not required |
| Local MCP (Claude Desktop, VS Code, Kiro) | Layer 2: `skill/` + `mcp-local/` | Not required |
| Team deployment | Layer 3: + `mcp-server/` + `infra/` + `png-worker/` | Required |
| Full stack | Layer 4: + `agent/` + `api/` + `web-ui/` | Required |

See [Architecture](docs/en/architecture.md) for details.

### Security Architecture

- **Authentication**: Cognito User Pool with JWT tokens (Layer 4)
- **Authorization**: Resource-level RBAC enforced at API and storage layers
- **Encryption**: S3 server-side encryption (SSE-S3), DynamoDB encryption at rest
- **Network**: CloudFront with OAI for static assets, API Gateway with Cognito authorizer

---

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/en/architecture.md) | 4-layer design, data flow, auth model, MCP tool reference |
| [Getting Started](docs/en/getting-started.md) | Setup and deployment for Layer 1–4 |
| [CloudShell Deploy](docs/en/deploy-cloudshell.md) | One-command deploy from CloudShell (no local CDK/Docker) |
| [Connecting Agents](docs/en/add-to-gateway.md) | Amazon Bedrock AgentCore Gateway and MCP client configuration |
| [Teams & Slack Integration](docs/en/teams-slack-integration.md) | Chat platform integration |
| [Custom Templates & Assets](docs/en/custom-template.md) | Adding custom templates and icons |

---

## Directory Structure

```
spec-driven-presentation-maker/
├── skill/            Layer 1 — Engine, references, templates
├── mcp-local/        Layer 2 — Local stdio MCP server
├── mcp-server/       Layer 3 — Streamable HTTP MCP server
├── infra/            Layer 3-4 — CDK stacks
├── png-worker/       Layer 3 — PPTX→PNG conversion (Fargate + SQS)
├── agent/            Layer 4 — Strands Agent
├── api/              Layer 4 — Unified REST API Lambda
├── web-ui/           Layer 4 — React Web UI
├── shared/           Shared modules (authorization, schema)
├── scripts/          Deployment and operations helpers
├── tests/            Unit tests
└── docs/             Documentation
```

---

## Testing

```bash
make all    # Lint + unit tests
make test   # Unit tests only
make lint   # ruff lint only
```

---

## Contributing

Contributions are welcome.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## Code of Conduct

This project has adopted the [Amazon Open Source Code of Conduct](https://aws.github.io/code-of-conduct).

## Security

This is sample code for demonstration and educational purposes only, not for production use.
You should work with your security and legal teams to meet your organizational security,
regulatory and compliance requirements before deployment.

### Data Protection
- All S3 buckets use server-side encryption (SSE-S3)
- DynamoDB tables use AWS managed encryption
- All data in transit is encrypted via TLS
- Block Public Access is enabled on all S3 buckets

### Security Measures Implemented

- **S3 Buckets**: Public access blocked, server-side encryption (SSE-S3), versioning enabled
- **DynamoDB**: Encryption at rest enabled, point-in-time recovery enabled
- **IAM**: Least-privilege roles scoped per service; no wildcard resource permissions
- **API Gateway**: Cognito JWT authorizer on all endpoints
- **CloudFront**: Origin Access Identity (OAI), HTTPS-only, security headers
- **Secrets**: No hardcoded credentials; all secrets via environment variables or IAM roles
- **AI/GenAI**: Model outputs labeled as AI-generated; dataset compliance documented
- **Logging**: CloudWatch Logs with configurable retention; Bedrock invocation logging optional

### Before Production Deployment

1. Enable AWS CloudTrail for audit logging
2. Configure VPC endpoints for S3 and DynamoDB if running in a VPC
3. Set up AWS WAF rules on CloudFront and API Gateway
4. Review and tighten CORS configuration for your domain
5. Enable S3 access logging on all buckets
6. Configure Cognito advanced security features (MFA, compromised credentials)
7. Review Amazon Bedrock model access and region settings — avoid cross-region inference profiles if data sovereignty is a concern

See [CONTRIBUTING.md](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This project is licensed under the [MIT-0 License](LICENSE).
