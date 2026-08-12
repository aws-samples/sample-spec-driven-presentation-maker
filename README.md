> 📝 [日本語版 README はこちら](README_ja.md)

# Spec-Driven Presentation Maker

[![License: MIT-0](https://img.shields.io/badge/License-MIT--0-yellow.svg)](LICENSE)
[![CI](https://github.com/aws-samples/sample-spec-driven-presentation-maker/actions/workflows/ci.yml/badge.svg)](https://github.com/aws-samples/sample-spec-driven-presentation-maker/actions/workflows/ci.yml)

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

### What you can ask for

Beyond creating a new deck from scratch, the agent is routed to these workflows
automatically — just describe what you want:

| Ask | What happens |
|---|---|
| "Make slides about …" | New presentation (briefing → outline → art direction → compose → review) |
| "Edit this PPTX" | Imports an existing PPTX into an editable deck |
| "I hand-edited the PPTX, continue from it" | Syncs your PowerPoint edits back into the deck |
| "Create a style like …" | Builds a reusable style guide (colors, typography, decoration) |
| "Translate this deck to English" | Creates a language-variant deck next to the original (source deck untouched) |

---

## Quick Start

One MCP server is the single integration surface. Connect your agent to it and ask for
slides — the server itself delivers the mode behavior via the `start_presentation` tool.
The repository is also a portable [Agent Plugins](https://agent-plugins.org) package, so
clients that support that format load the MCP server and the mode entry points together.

| Environment | Setup |
|---|---|
| Claude Code | `/plugin marketplace add aws-samples/sample-spec-driven-presentation-maker` then `/plugin install sdpm@sdpm` |
| Kiro CLI | `git clone` this repo, then `make install-kiro` |
| Kiro IDE (Powers) | Install this checkout as a Power — it is an Agent Plugins package |
| Codex | `codex plugin marketplace add ./` in the checkout, then install from the ChatGPT desktop app |
| Claude Desktop / any MCP client | Register `servers/local` as a stdio MCP server — see [Getting Started](docs/en/getting-started.md) |
| No MCP at all | Point your agent at [`sdpm/SKILL.md`](sdpm/SKILL.md) — it drives the CLI directly |
| Team / remote MCP / Web UI (AWS) | [Deploy Guide](docs/en/deploy-cloudshell.md) |

**Picking a mode.** Just asking for slides is enough — the agent calls
`start_presentation` and picks. To choose explicitly, use the entry points:
`sdpm-vibe` (fast, from material you already have), `sdpm-spec` (dialogue-driven, with
approval at each step), `sdpm-style` (build a reusable style guide), `sdpm-translate`
(translate an existing deck into another language). In clients that turn
skills into slash commands, those are `/sdpm-vibe`, `/sdpm-spec`, `/sdpm-style`,
`/sdpm-translate`. Each one
only loads the matching persona from the server — the behavior itself still lives in
`personas/`, in one place.

**Prerequisites for local use:** [`uv`](https://docs.astral.sh/uv/) on your `PATH`, plus
**LibreOffice** and **poppler** for slide previews (PNG rendering).

**Keep the checkout in place** for Claude Code / Kiro / local MCP: the server runs from it
(`uv run --directory <checkout>/servers/local`). Updating is `git pull` — persona and
knowledge files are read live from the checkout.

> **Upgrading from v0.4?** Directory layout and install flows changed — see the
> [v0.5 migration notes](docs/en/migration-v0.5.md).

---

## One-Click Deploy — Just an AWS Account to Get Started

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

```
sdpm/        Engine (json <-> pptx) + Knowledge (references, assets, templates)
personas/    Mode behaviors — served to any MCP client via start_presentation(mode=...)
skills/      Mode entry points — thin dispatchers that load a persona from the server
plugin.json  Agent Plugins manifest (+ mcp.json) — makes the root a portable plugin
servers/     local (stdio, no AWS) / remote (HTTP, S3 + DynamoDB) — thin binds of one tool contract
clients/     Per-client wiring (Claude Code / Codex manifests, Kiro installer)
agent/ api/ infra/ web-ui/   Optional AWS cloud stack (Strands Agent, REST API, CDK, React UI)
```

Everything an agent needs — tools, workflows, guides, and mode behavior — is served by
the MCP server. Client-side files are minimal wiring: per-client manifests and entry
points that name a mode without restating what it does.
See [Architecture](docs/en/architecture.md) for the full picture.

---

## Documentation

| Document | Description |
|---|---|
| [Getting Started](docs/en/getting-started.md) | Setup for every environment, from bare CLI to full AWS stack |
| [Architecture](docs/en/architecture.md) | Layer design, data flow, auth model, MCP tool reference |
| [Migration to v0.5](docs/en/migration-v0.5.md) | Upgrading from v0.4 (paths, skills removal) |
| [Recommended Deploy](docs/en/deploy-cloudshell.md) | AWS deployment via CloudShell (no CDK/Docker required) |
| [Connecting Agents](docs/en/add-to-gateway.md) | MCP client connection guide |
| [Teams & Slack Integration](docs/en/teams-slack-integration.md) | Chat platform integration |
| [Custom Templates & Assets](docs/en/custom-template.md) | Adding custom templates and icons |
| [Cost Estimates](docs/en/cost.md) | Monthly cost breakdown and optimisation tips |
| [Uninstall](docs/en/uninstall.md) | Clean up deployed AWS resources |
| [Web UI (Local Mode — experimental)](web-ui/README.md#local-mode) | Run the Web UI locally against a Kiro CLI ACP backend (no AWS) |

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
