# Spec-Driven Presentation Maker

AI-powered presentation generation toolkit. Engine + knowledge in `sdpm/`,
served through MCP servers (`servers/`), with optional AWS cloud stack.

## First: Are you developing this repo, or using it?

**Using it to generate slides:**
→ Choose one of the two first-class entry points in the [README Quick Start](README.md#quick-start):
use the full experience in your browser, or connect SDPM to the AI agent you already have.
Do NOT work inside this repo for everyday slide generation.

**Developing / modifying this repo:**
→ Work in place. Use `make test` / `make lint` to verify changes. Read the
[Conventions](#conventions) and [Boundaries](#boundaries) sections first.

## Project Structure

```
sdpm/        Engine + knowledge (single source of business logic)
├─ sdpm/engine/      json <-> pptx conversion
├─ sdpm/knowledge/   references / assets retrieval
├─ sdpm/tools/       MCP tool contract (single definition for all servers)
├─ references/       workflows (role documents), guides, spec, examples (data)
├─ templates/        bundled .pptx templates (data)
└─ SKILL.md          L1 entry (agents without MCP drive the CLI directly)
skills/      Mode entry points (sdpm-create / sdpm-composer / sdpm-style / sdpm-translate)
             — thin dispatchers, no behavior text
plugin.json  Agent Plugins 1.0.0 manifest; mcp.json declares the bundled MCP server
servers/
├─ local/    stdio MCP + ACP server (no AWS)
└─ remote/   streamable-HTTP MCP server (AWS: S3 + DynamoDB)
clients/     Per-client wiring only
├─ uvx-config.json       Canonical clone-free MCP command
├─ snippets.md           Generated client installation commands (do not hand-edit)
├─ claude-desktop/       MCPB manifest and packaging rules
└─ kiro/                 Checkout-based full Kiro installer
scripts/install/  Web UI installers, launcher sources, and generated dist/install.*
agent/       L4 Strands Agent (cloud)
api/         L4 REST API Lambda
infra/       CDK stacks
web-ui/      React Web UI
shared/      Authorization / schema helpers shared by api and servers/remote
tests/       Unit tests (pytest)
docs/        Documentation
```

## Architecture in one paragraph

`sdpm.engine` (pure json↔pptx) and `sdpm.knowledge` (reference/asset retrieval)
are peers. `sdpm.tools` defines every MCP tool once — names, schemas,
docstrings, logic — and both servers register those functions directly. Role and
procedure text is content, not client config: `sdpm/references/workflows/<role>.md`
(orchestrator, composer, style, translate) is the single definition for each role,
delivered to any MCP client by the `start_*` entry tools (`start_presentation`,
`start_composing`, `start_style`, `start_translation`), each of which also returns what
that role reads first. The files under `skills/` are entry points only — they call the
entry tool and never restate what the role does.
See [Architecture](docs/en/architecture.md).

## Conventions

- Engine source of truth: `sdpm/sdpm/` — servers must stay thin binds of `sdpm.tools`
- Role + procedure text lives only in `sdpm/references/workflows/<role>.md`; skills,
  client agent definitions, `SKILL.md` and server instructions are dispatch/environment
  only (guarded by `tests/test_skill_entrypoints.py`)
- `skills/*/SKILL.md` may only call a `start_*` entry tool; copying workflow
  prose into a skill is what forced the v0.5.0 skill removal and is now guarded by
  `tests/test_skill_entrypoints.py`
- Client manifests: `plugin.json` + `mcp.json` (portable, Agent Plugins 1.0.0),
  `.codex-plugin/plugin.json` + `.mcp.json` (Codex), `.claude-plugin/plugin.json`
  (Claude Code). All must keep pointing at the same `servers/local` definition —
  `tests/test_codex_adapter.py` fails on drift
- `clients/snippets.md` is generated from `clients/uvx-config.json`; regenerate it with
  `uv run python scripts/gen_client_snippets.py` and never edit it by hand
- Slide spec: JSON — schema and examples in `sdpm/references/`
- Python: always `uv run`, never bare `python`
- Verify changes: `make lint` (ruff) and `make test` (pytest) before committing
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, ...)

## Boundaries

- Do not modify `sdpm/templates/*.pptx` directly — base templates
- Do not modify `sdpm/references/` without understanding the workflow dependency chain
- Do not hand-edit `sdpm/assets/` — regenerate via download scripts
- Do not add logic to `servers/*` that belongs in `sdpm.tools` / `sdpm.engine` / `sdpm.knowledge`
  (infrastructure-only code — S3, DynamoDB, auth — is the exception, and lives in `servers/remote`)
- Review `infra/config.yaml` before changing deployment settings

## Further Documentation

- [Getting Started](docs/en/getting-started.md) — browser, local agent, manual, and AWS setup
- [Architecture](docs/en/architecture.md) — data flow, auth model, MCP tool reference
- [Custom Templates & Assets](docs/en/custom-template.md)
- [Connecting Agents](docs/en/add-to-gateway.md)
- [Cost Estimates](docs/en/cost.md)
