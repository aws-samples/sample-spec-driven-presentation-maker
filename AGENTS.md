# Spec-Driven Presentation Maker

AI-powered presentation generation toolkit. Engine + knowledge in `sdpm/`,
served through MCP servers (`servers/`), with optional AWS cloud stack.

## First: Are you developing this repo, or using it?

**Using it to generate slides with an AI agent:**
→ Connect your agent to the local MCP server — see [Getting Started](docs/en/getting-started.md).
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
├─ references/       guides, workflows, examples (data)
├─ templates/        bundled .pptx templates (data)
└─ SKILL.md          L1 entry (agents without MCP drive the CLI directly)
personas/    Canonical mode behaviors (vibe / spec / style / composer / single)
             — served to MCP clients via the start_presentation(mode=...) tool
skills/      Mode entry points (vibe / spec / style) — thin dispatchers, no behavior text
plugin.json  Agent Plugins 1.0.0 manifest; mcp.json declares the bundled MCP server
servers/
├─ local/    stdio MCP + ACP server (no AWS)
└─ remote/   streamable-HTTP MCP server (AWS: S3 + DynamoDB)
clients/     Per-client wiring only (claude-code plugin agents, kiro installer, ACP configs live in servers/local/.kiro)
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
docstrings, logic — and both servers register those functions directly. Mode
behavior (personas) is content, not client config: `start_presentation(mode=...)`
returns it to any MCP client, so the files under `skills/` are entry points only
— they name a mode and never restate what it does.
See [Architecture](docs/en/architecture.md).

## Conventions

- Engine source of truth: `sdpm/sdpm/` — servers must stay thin binds of `sdpm.tools`
- Persona text lives only in `personas/*.md` — all layers including the L4 agent fetch
  it via `start_presentation(mode=...)`; client/agent-side files are thin wiring
  (a Kiro/CC composer definition should never duplicate behavior text)
- `skills/*/SKILL.md` may only dispatch to `start_presentation(mode=...)`; copying
  persona prose into a skill is what forced their removal in v0.5.0 and is now guarded
  by `tests/test_skill_entrypoints.py`
- Client manifests: `plugin.json` + `mcp.json` (portable, Agent Plugins 1.0.0),
  `.codex-plugin/plugin.json` + `.mcp.json` (Codex), `.claude-plugin/plugin.json`
  (Claude Code). All must keep pointing at the same `servers/local` definition —
  `tests/test_codex_adapter.py` fails on drift
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

- [Getting Started](docs/en/getting-started.md) — setup for every layer (L1–L4)
- [Architecture](docs/en/architecture.md) — data flow, auth model, MCP tool reference
- [Custom Templates & Assets](docs/en/custom-template.md)
- [Connecting Agents](docs/en/add-to-gateway.md)
- [Cost Estimates](docs/en/cost.md)
