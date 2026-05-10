# Spec-Driven Presentation Maker

AI-powered presentation generation toolkit with a 4-layer architecture.

## First: Are you developing this repo, or using it?

**Using it to generate slides with an AI agent:**
→ Install the skill into your agent's skill directory (or as a pip package). See [Layer 1](#layer-1-agent-skill).
Do NOT work inside this repo for everyday slide generation.

**Developing / modifying this repo:**
→ Work in place. Use `make test` / `make lint` to verify changes. Read the [Conventions](#conventions) and [Boundaries](#boundaries) sections first.

---

## Which Layer to Use

| Environment | Layer | AWS |
|---|---|:---:|
| SKILL.md-compatible agent (Claude Code, Codex CLI, Cursor, Kiro, Copilot) | **L1** `skill/` | No |
| Local MCP client (Claude Desktop, Claude Cowork) | **L2** `mcp-local/` | No |
| Remote-only MCP client (Claude.ai web) | **L3** `mcp-server/` + `infra/` | Yes |
| Web UI in browser | **L4** Full stack | Yes |

---

## Layer 1: Agent Skill

The skill entry point is `skill/SKILL.md` — agents read it to discover workflows.

**Install as pip package (recommended for end users):**

```bash
pip install git+https://github.com/aws-samples/sample-spec-driven-presentation-maker.git#subdirectory=skill
```

**Install into an agent's skill directory** (e.g. `~/.kiro/skills/sdpm/`):
copy or symlink `skill/` into the agent's configured skill path. Consult your agent's docs for the exact location.

**Work from source (developers only):**

```bash
cd skill && uv sync
```

Optional: download icons (AWS / Material):

```bash
uv run python3 scripts/download_aws_icons.py
uv run python3 scripts/download_material_icons.py
```

---

## Layer 2: Local MCP Server

```bash
cd mcp-local && uv sync
```

Add to your MCP client config:

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

---

## Layer 3 / 4: AWS Deployment

```bash
bash scripts/deploy.sh --region us-east-1 --layer3   # Layer 3 only
bash scripts/deploy.sh --region us-east-1            # Layer 4 full stack
```

Windows users or anyone without Bash: use [AWS CloudShell](https://console.aws.amazon.com/cloudshell/).
Full details (post-deploy steps, options, troubleshooting): [Recommended Deploy Guide](docs/en/deploy-cloudshell.md).

---

## Experimental: Web UI Local Mode

Runs the Layer 4 Web UI against a local [Kiro](https://kiro.dev/) CLI ACP backend — no AWS needed.
Requires `kiro-cli` on `PATH`.

```bash
cd web-ui && npm ci && npm run dev:local
```

See [`web-ui/README.md#local-mode`](web-ui/README.md#local-mode).

---

## Project Structure

```
skill/       L1 — Engine, references, templates, SKILL.md
mcp-local/   L2 — Local stdio MCP server
mcp-server/  L3 — Streamable HTTP MCP server (AWS)
infra/       L3-4 — CDK stacks
agent/       L4 — Strands Agent
api/         L4 — REST API Lambda
web-ui/      L4 — React Web UI
```

## Conventions

- Engine source of truth: `skill/sdpm/`
- Slide spec: JSON — schema and examples in `skill/references/`
- Python: always `uv run`, never bare `python`
- Verify changes: `make lint` (ruff) and `make test` (pytest) before committing
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, ...)

## Boundaries

- Do not modify `skill/templates/*.pptx` directly — base templates
- Do not modify `skill/references/` without understanding the workflow dependency chain
- Do not hand-edit `skill/assets/` — regenerate via download scripts
- Review `infra/config.yaml` before changing deployment settings

## Further Documentation

- [Architecture](docs/en/architecture.md) — Data flow, auth model, MCP tool reference
- [Custom Templates & Assets](docs/en/custom-template.md) — Adding .pptx templates and icons
- [Connecting Agents](docs/en/add-to-gateway.md) — MCP client connection guide
- [Cost Estimates](docs/en/cost.md) — Monthly cost breakdown
