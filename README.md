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


![workflow](./docs/assets/workflow-en.png)

---

## Quick Start

Choose your environment and follow the setup guide:

| Environment | Setup |
|---|---|
| Agent skill (Claude Code, Codex CLI, Cursor, Kiro, Copilot) | [Getting Started — Layer 1](docs/en/getting-started.md#layer-1-kiro-cli-skill) |
| Local MCP client (Claude Desktop, Claude Cowork) | [Getting Started — Layer 2](docs/en/getting-started.md#layer-2-local-mcp-server) |
| Remote MCP / Web UI (AWS deployment) | [Deploy Guide](docs/en/deploy-cloudshell.md) |

### 🧩 Claude Code Plugin (one-command install)

Claude Code users can install everything with a plugin — no manual MCP config. The plugin
registers the **local MCP server**, an **orchestrator skill**, and a **compose sub-agent**
that builds slides in parallel.

**Prerequisites (install once, not bundled with the plugin):**

- [`uv`](https://docs.astral.sh/uv/) on your `PATH` — runs the local MCP server and resolves
  its Python dependencies on first launch (cold start takes a few tens of seconds).
- **LibreOffice** and **poppler** — required to render slide previews (HTML/SVG → PNG).

**Install (automatic — downloads this repo, registers MCP + skill + sub-agent):**

```bash
# In Claude Code:
/plugin marketplace add aws-samples/sample-spec-driven-presentation-maker
/plugin install sdpm@sdpm
```

`/plugin install` clones the repo (so `mcp-local/` and `skill/` come with it), auto-starts
the `sdpm` MCP server via `uv`, and registers the `sdpm` skill and the `sdpm:sdpm-composer`
sub-agent. Verify with `/plugin list`, `/mcp` (expect `sdpm` connected), and `/agents`
(expect `sdpm:sdpm-composer`). Then just ask Claude Code to "make slides about ..." — the
skill drives briefing → outline → art direction, then delegates Phase 2 (compose) to parallel
composer sub-agents, and finishes with review.

> **Which entry point?** **Kiro CLI** → use the Layer 1 skill. **Claude Desktop / other MCP
> clients** → use the Layer 2 local MCP server. **Claude Code** → use this plugin (it wraps the
> same Layer 2 MCP server with a CC-native skill + parallel compose sub-agent).

### 🚀 One-Click Deploy — Just an AWS Account to Get Started

| Region | Launch |
|--------|--------|
| Tokyo (ap-northeast-1) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://ap-northeast-1.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |
| N. Virginia (us-east-1) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://us-east-1.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |
| Oregon (us-west-2) | [![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://us-west-2.console.aws.amazon.com/cloudformation/home#/stacks/create/review?stackName=SdpmDeploymentStack&templateURL=https://aws-ml-jp.s3.ap-northeast-1.amazonaws.com/asset-deployments/SdpmDeploymentStack.yaml) |

See the [Deploy Guide](docs/en/deploy-cloudshell.md) for parameter details and alternative deployment methods.

---

## Workshop

A hands-on workshop is available with sample data for various real-world scenarios. Practice generating slides from URLs, PDFs, CSVs, meeting minutes, and more — with industry-specific scenarios for manufacturing, financial services, healthcare, IT, and others.

📖 **[Workshop](https://catalog.us-east-1.prod.workshops.aws/workshops/a275330a-0ae0-40b2-ad35-264e263c3882/en-US)**

---

## Architecture

Built on a 4-layer architecture. Each layer is a thin wrapper around the previous one. Use only the layers you need.

| Use Case | Layer | AWS |
|---|---|:---:|
| Personal use with Kiro CLI | Layer 1: `skill/` | Not required |
| Local MCP (Claude Desktop, VS Code, Kiro) | Layer 2: `skill/` + `mcp-local/` | Not required |
| Team deployment | Layer 3: + `mcp-server/` + `infra/` | Required |
| Full stack | Layer 4: + `agent/` + `api/` + `web-ui/` | Required |

See [Architecture](docs/en/architecture.md) for details.

---

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/en/architecture.md) | 4-layer design, data flow, auth model, MCP tool reference |
| [Getting Started](docs/en/getting-started.md) | Setup and deployment for Layer 1–4 |
| [Recommended Deploy](docs/en/deploy-cloudshell.md) | Recommended path for AWS deployments (CloudShell or any local Linux/macOS/WSL, no CDK/Docker required) |
| [Connecting Agents](docs/en/add-to-gateway.md) | MCP client connection guide |
| [Teams & Slack Integration](docs/en/teams-slack-integration.md) | Chat platform integration |
| [Custom Templates & Assets](docs/en/custom-template.md) | Adding custom templates and icons |
| [Cost Estimates](docs/en/cost.md) | Monthly cost breakdown and optimisation tips |
| [Uninstall](docs/en/uninstall.md) | Clean up deployed AWS resources |
| [Web UI (Local Mode — experimental)](web-ui/README.md#local-mode) | Run the Web UI locally against a Kiro CLI ACP backend (no AWS) |

---

## Directory Structure

```
spec-driven-presentation-maker/
├── skill/            Layer 1 — Engine, references, templates
├── mcp-local/        Layer 2 — Local stdio MCP server
├── mcp-server/       Layer 3 — Streamable HTTP MCP server (LibreOffice built-in)
├── infra/            Layer 3-4 — CDK stacks
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

### Security Measures Implemented

- **S3 Buckets**: Public access blocked, server-side encryption (SSE-S3), versioning enabled
- **DynamoDB**: Encryption at rest enabled, point-in-time recovery enabled
- **Data in transit**: All traffic encrypted via TLS
- **IAM**: Least-privilege roles scoped per service; no wildcard resource permissions
- **API Gateway**: Cognito JWT authorizer on all endpoints
- **CloudFront**: Origin Access Identity (OAI), HTTPS-only, security headers
- **Secrets**: No hardcoded credentials; all secrets via environment variables or IAM roles
- **AI/GenAI**: Model outputs labeled as AI-generated; dataset compliance documented
- **Logging**: CloudWatch Logs with configurable retention; Bedrock invocation logging optional

### Environment-Dependent Settings (Not Applied by Default)

The following controls depend on your organization's environment, network topology, or security policy — they cannot be safely defaulted in a sample stack. Evaluate each before production use.

1. **AWS CloudTrail** — account-level setting; enable separately to avoid disrupting existing CloudTrail configurations
2. **VPC endpoints for S3 and DynamoDB** — only relevant if you deploy inside a VPC (this stack does not)
3. **AWS WAF IP restrictions** — built-in support, but IP ranges are environment-specific: set `waf.allowedIpV4AddressRanges` / `waf.allowedIpV6AddressRanges` in `config.yaml`, or pass `--waf-ipv4` / `--waf-ipv6` to `deploy.sh`
4. **CORS tightening** — depends on your domain
5. **S3 access logging** — log destination bucket and retention are your choice
6. **Cognito advanced security (MFA, compromised-credentials detection)** — omitted by default to keep the demo frictionless
7. **Bedrock model / region selection** — avoid cross-region inference profiles if data sovereignty is a concern

### Reporting Security Issues

Found a potential vulnerability? Please do not file a public GitHub issue — follow the process in [CONTRIBUTING.md](CONTRIBUTING.md#security-issue-notifications).

## License

This project is licensed under the [MIT-0 License](LICENSE).
