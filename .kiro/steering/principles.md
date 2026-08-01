<!-- PUBLIC: This file is git-tracked and visible in the public repository. -->

# Principles

## Architecture

```
Layer 4: Agent + Web UI (agent/, web-ui/)
  ↓ uses
Layer 3: servers/remote   ← AWS (S3/DynamoDB), HTTP MCP
  ↓ binds
sdpm.tools (MCP tool contract — single definition)
  ↑ binds
Layer 2: servers/local    ← stdio MCP + ACP
  ↑ uses
Layer 1: CLI (sdpm/scripts/pptx_builder.py) + sdpm/SKILL.md
```

Layer 4 hosts the Strands Agent (SPEC agent + composer agents) and the React Web UI.
The SPEC agent handles user dialogue (Phase 1). Composer agents handle slide generation
(Phase 2+3) via the `compose_slides` tool (Agents as Tools pattern).

Mode behavior (vibe / spec / style / composer) lives in `personas/*.md` and is
served to MCP clients via `start_presentation(mode=...)`. Client-side files are thin
wiring (composer sub-agent registration). The L4 agent fetches personas through the
same port (`Source.mcp("start_presentation", ...)` in `agent/modes/`); only
transport-specific wiring (attachment wire format, compose_slides report format)
lives in `agent/prompts/`.

## Design Philosophy — Ports and Adapters

The v0.5 structure is a deliberate Ports and Adapters (Hexagonal) architecture:

| Element | Pattern role |
|---|---|
| `sdpm.engine` / `sdpm.knowledge` | Core domain — pure logic, knows nothing about the outside |
| `sdpm.api` | Facade over the core (generate / preview / init / code_block) |
| `sdpm.tools` | The **port** — every operation defined once as a contract |
| `servers/local` | Adapter: stdio MCP + ACP transport |
| `servers/remote` | Adapter: HTTP MCP + AWS infrastructure (S3 / DynamoDB) |
| CLI + `sdpm/SKILL.md` | Adapter: no-MCP path |
| `agent/`, `web-ui/` | Outer applications consuming the port |

Rules that follow from this:

1. **Dependency rule** — dependencies point inward only
   (servers → tools → engine/knowledge). The core never imports from
   servers, clients, or infra.
2. **Adapters hold only transport/infrastructure differences.** If a piece of
   logic is not about transport or storage, it belongs in the core.
3. **Deliberate deviation: no storage port.** The core defines no Storage
   abstraction; S3/DynamoDB live entirely inside `servers/remote`. This trades
   hexagonal purity for one less abstraction — acceptable while there is a
   single cloud backend. Revisit only if a second backend appears.
4. **Personas are content, not client config** ("server-driven behavior").
   Behavior is served through the port via `start_presentation(mode=...)`,
   so client-side files stay minimal wiring and never duplicate behavior text.

   Deciding *how* a client obtains a persona is a two-axis judgement:

   - **When is the mode known?** If it is only decided in conversation
     (user picks vibe/spec/style), the agent must fetch via
     `start_presentation` — the default. If the mode is fixed at the
     entry point (a dedicated composer sub-agent, the L4 agent's modes),
     the persona may be embedded into the system prompt — but only when
     it is **re-derived at reference/build time from `personas/`**
     (never a hand-maintained copy).
   - **Does the definition cross a distribution boundary?** Anything
     copied into user-owned locations (`~/.kiro/agents/`, plugin files)
     drifts silently after `git pull`. Prefer definitions that resolve
     the persona live from the checkout / server; treat boundary-crossing
     copies as generated artifacts that must be re-derivable.

   Two orthogonal follow-ons: *delivery* (through the port vs. file read)
   and *placement* (system prompt vs. task prompt) are independent choices —
   picking one does not constrain the other. Tool docstrings (e.g.
   `start_presentation`'s mode list) are the discovery layer — the
   equivalent of skill frontmatter; do not create skill stubs for modes.
5. **Change-locality goal** — the structure is optimised so that:
   prompt changes touch only `personas/`; engine changes touch only
   `sdpm/sdpm/engine/`; a new client touches only `clients/`; a new tool
   touches only `sdpm/sdpm/tools/`.

Known debt against this philosophy (tracked for v0.5.x):
`api/index.py` has no test coverage.
(v0.5.2 resolved: `converter/elements.py` monolith → `converter/elements/`
package with an enforced dependency DAG; scale state → ContextVar scope.)

## Engine & Knowledge (`sdpm/sdpm/`)

The single source of truth for all business logic, split into two peer subpackages:

- `sdpm.engine` — json ↔ pptx conversion
  (`builder`, `converter`, `layout`, `schema`, `preview`, `checks`, `diff`, `analyzer`)
- `sdpm.knowledge` — knowledge storage & retrieval
  (`reference`, `assets`)
- `sdpm.api` — High-level API facade (generate, preview, init, code_block)
- `sdpm.config` — Config + path anchors (ASSETS_DIR, REFERENCES_DIR, TEMPLATES_DIR, ...)
- `sdpm.utils` — Shared utilities

## Skill root (`sdpm/`)

Distribution root containing the `sdpm` Python package + CLI + reference
documents + templates. Installed as `sdpm-skill` and consumed by Layer 2 and Layer 3.

## Tool contract (`sdpm.tools`)

Every MCP tool is defined once here: name, signature, docstring, and logic
(delegating to `sdpm.engine` / `sdpm.knowledge`). Servers register these
functions directly (`mcp.tool()(tools.xxx)`) — never redefine a tool body
in a server.

`start_presentation(mode=...)` is part of the contract and serves
`personas/*.md` to any MCP client.

## Local server (`servers/local/`) — Layer 2

stdio MCP + ACP server for local environments. Must be a **thin bind** of
`sdpm.tools`. Local-transport specifics (session-scoped upload staging,
browser style gallery, ACP hearing UI) are the only allowed additions.

## Remote server (`servers/remote/`) — Layer 3

HTTP MCP server running on AWS with S3/DynamoDB dependencies.

- Binds contract tools where possible; workspace tools materialize the S3
  deck into a tmpdir and delegate to `sdpm.api` (same code path as local)
- Infrastructure-dependent operations (user templates/styles on S3, DynamoDB
  records, presigned URLs, Code Interpreter) may have independent implementations
- However, use Engine logic when equivalent functionality exists
- Server instructions are a deliberate divergence: Local serves the shared
  interactive menu (`sdpm.tools.instructions`); Remote serves a short
  agent-facing form (its client is the L4 agent, which already carries the
  persona) — see the comment above `_INSTRUCTIONS` in `servers/remote/server.py`

## Logic Sharing Principles

### Engine is the source of truth
The Engine API is the canonical implementation. CLI, MCP Local, and MCP Remote are consumers.

### What to share

Share:
- Data retrieval and transformation logic (file scanning, frontmatter stripping, pptx notes extraction)
- Business rules (template resolution, icon validation, autofit, imbalance check)
- Computation logic (grid calculation, code highlighting, layout)

Do not share:
- I/O format differences (CLI: print/stdin, MCP Local: JSON, MCP Remote: S3/DynamoDB)
- Environment-specific processing (MCP Remote S3 Storage, CLI argparse)
- UI layer concerns (error message formatting, browser launch behavior)

### Decision flow when uncertain
1. Does the logic exist in the Engine? → Use it
2. Is it infrastructure-dependent? → S3/DynamoDB dependencies allow MCP Remote independent implementation
3. Is the difference only in presentation/output? → Engine API returns data, each layer controls output

## PR前ローカルチェック

PR作成前に以下をローカルで実行し、CI待ちを減らす:

```bash
ash scan --mode local --fail-on-findings
```

## Web UI: Dual-Mode (Cloud / Local)

Single Next.js codebase serves two modes via build-time feature toggle `NEXT_PUBLIC_MODE`.
Cloud mode is the primary target; Local mode exists for users who want to try the app without deploying to AWS.

```
Cloud (default)  — AWS direct (AgentCore, S3, Cognito), static export via CloudFront
Local            — Next.js API Routes → kiro-cli ACP, filesystem storage
```

### Branching rules

| Layer | How to branch |
|-------|--------------|
| UI components | `<CloudOnly>` / `<LocalOnly>` (declarative) |
| Service layer | `IS_LOCAL` early return at function entry point |
| API Routes (`src/app/api/`) | Local-only. Excluded from cloud build by `build:cloud` |
| Local-only logic | Isolated in `src/lib/local/` |

### Web-first principle
- Web (Cloud) code must remain the cleanest path — no Local logic mixed in
- Local is a subset: no auth, no public/shared decks, no Bedrock search
- `build:cloud` output must be identical whether Local code exists or not

### Build strategy
- `output: "export"` and `trailingSlash: true` are cloud-only (`next.config.ts`)
- `build:cloud` temporarily moves `src/app/api/` out to enable static export (with `trap EXIT` for safe restore)
- This is a known workaround — Next.js does not support `output: "export"` + API Routes coexistence

### Session persistence (Local)
- `.session` file in deck directory — ACP sessionId
- `.chat.json` file in deck directory — chat messages for UI display
- `session/load` restores agent context; replay is not used for UI (Obsidian agent-client pattern)

## Adding a New Bedrock Model

Update these 3 files:

1. **`agent/model_profiles.py`** — Invocation profile (temperature, cache, compose_capable)
2. **`infra/lib/model-metadata.ts`** — Display name, description, composable flag
3. **`infra/config.yaml`** — Add to `model.allowedModelIds`

`compose_capable` / `composable` controls whether the model appears in the Create picker.
Set to `false` for models below Sonnet-class capability.

## Web UI: Typography & Sizing

### Tailwind class convention

Use Tailwind standard classes. Arbitrary values (`text-[Npx]`) are prohibited except `text-[11px]` and `text-[15px]`.

| Class | Size | Use for |
|-------|------|---------|
| `text-sm` | 14px | Body, chat, navigation, card titles, buttons |
| `text-xs` | 12px | Meta info, labels, secondary text |
| `text-[11px]` | 11px | Badges only (absolute floor, no TW equivalent) |
| `text-[15px]` | 15px | Outline headings (between sm and base) |

### Rules

- **11px absolute floor** — nothing smaller, ever
- **14px for anything users read** — body, chat messages, navigation, card titles
- **12px for supporting info** — timestamps, metadata, toolbar labels
- **No opacity-based text sizing** — use explicit Tailwind classes

### Rationale (ISO 9241-303)

At 60cm viewing distance, 10px text subtends only 7.9′ visual angle (ISO minimum: 16′).
14px at 50cm = 13.2′, comfortable for most adults including mild presbyopia.
13px→14px costs only 7% information density (33→31 lines per 700px).
