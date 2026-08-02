[EN](../en/architecture.md) | [JA (日本語ドキュメントは Getting Started のみ)](../ja/getting-started.md)

# Architecture

This document describes spec-driven-presentation-maker's overall architecture, data flow, authentication and authorization model,
data model, CDK stack structure, and deployment patterns.

---

## 4-Layer Architecture

spec-driven-presentation-maker consists of 4 layers.
Each layer is a thin wrapper around the previous one — use only the layers you need.

![4layer-architecture](../assets/4layer-architecture-en.png)

### Dependency Direction

Dependencies always flow top-down.

![dependency-direction](../assets/dependency-direction-en.png)

---

## Layer 1: Engine + Knowledge (`sdpm/`)

The core presentation engine. No network, no AWS, no MCP — just Python.

- **sdpm/sdpm/engine/** — json↔pptx conversion: builder, converter, layout engine, schema lint, preview, checks, diff, analyzer
- **sdpm/sdpm/knowledge/** — knowledge retrieval: references (guides/workflows/examples) and asset search
- **sdpm/sdpm/tools/** — the MCP tool contract: every tool's name, schema, docstring, and logic defined once; both servers register these functions directly
- **sdpm/references/** — Examples (slide patterns), workflows (phase instructions), guides (design rules)
- **sdpm/templates/** — Sample .pptx templates (dark/light)
- **sdpm/scripts/** — CLI entry point (`pptx_builder.py`), asset download scripts
- **personas/** (repo root) — canonical mode behaviors (vibe / spec / style / composer), served to MCP clients via `start_presentation(mode=...)`

Key capabilities:
- Analyze any .pptx template (layouts, colors, fonts, placeholders)
- Build slides from JSON with automatic layout optimization
- Generate PPTX files from `presentation.json`
- Convert existing PPTX back to JSON (via upload-time conversion)
- Multi-source asset search (AWS icons, Material Symbols, custom)

---

## Layer 2: Local MCP Server (`servers/local/`)

A thin bind of the `sdpm.tools` contract. Runs as a stdio server (plus an ACP variant for the local Web UI).

- Registers the contract tools via FastMCP — no tool logic of its own
- **Mode behavior via `start_presentation(mode=...)`** — any MCP client (including ones with no skill/sub-agent mechanism, e.g. Claude Desktop) receives the vibe/spec/style/composer behavior as a tool response. Clients that read MCP Server Instructions also get the workflow menu automatically.
- No AWS required — all files stored locally

---

## Layer 3: Remote MCP Server

The same `sdpm.tools` contract bound to an HTTP transport, with storage swapped to Amazon DynamoDB + S3 plus authentication and authorization. Bundled knowledge (references, templates, personas) is baked into the container image; only user data (decks, uploads, user templates/styles) lives in S3/DynamoDB.

```
MCP Client → AgentCore Runtime → MCP Server Container
                                   ├── 20 MCP tools
                                   ├── LibreOffice (PPTX → PDF/SVG)
                                   ├── DynamoDB (decks, templates)
                                   ├── S3 (PPTX, previews, references, assets)
                                   └── Code Interpreter (optional)
```

Additional tools over Layer 2:
- `read_attachment` — Read content from an attached file (PDF, DOCX, XLSX, PPTX, text, images) with byte-offset paging
- `import_attachment` — Import attached files into the deck workspace
- `apply_style` — Apply a named style preset to a deck
- `run_python` — Execute Python in Amazon Bedrock AgentCore Code Interpreter sandbox (edit deck workspace, analyze data)
- `search_slides` — Semantic slide search via Amazon Bedrock Knowledge Base (optional)

### Storage

```
DynamoDB:
  USER#{userId}/DECK#{deckId}       — deck metadata
  TEMPLATE#{id}/META                — template metadata

S3 (pptx bucket):
  decks/{deckId}/deck.json          — deck metadata (template, fonts, defaultTextColor)
  decks/{deckId}/slides/{slug}.json — per-slide data
  decks/{deckId}/specs/             — brief.md, outline.md, art-direction.html
  decks/{deckId}/includes/          — code block JSON
  decks/{deckId}/compose/           — per-slide SVG compose JSON (for Web UI animation)
  previews/{deckId}/{slideId}.png   — slide previews

S3 (resource bucket):
  references/                       — examples, workflows, guides
  templates/                        — .pptx template files
  assets/                           — icons and images
```

### Deck Workspace

Using `run_python(deck_id=...)` loads the entire deck workspace into the sandbox.
The agent can read and write files using standard Python file I/O (`open`, `json.load`, etc.); modified files are written back to S3 automatically after every execution.

```
deck.json           — deck metadata (template, fonts, defaultTextColor)
slides/{slug}.json  — per-slide data (one file per slide, slug from outline)
specs/brief.md          — briefing (audience, purpose, key messages)
specs/outline.md        — one line per slide: - [slug] message
specs/art-direction.html — visual design direction (HTML style guide)
includes/           — code block JSON files
```

### Authentication

- JWT Bearer authentication via Amazon Bedrock AgentCore Runtime's `customJwtAuthorizer`
- Default is Amazon Cognito User Pool; supports any OIDC-compliant IdP
- User identity: JWT `sub` claim propagated through the entire stack
- Authorization: role-based per deck (owner / collaborator / viewer)

### Preview Generation

The MCP Server container includes LibreOffice and poppler-utils for synchronous preview generation.
When `generate_pptx` is called, previews are generated inline:

```
generate_pptx:
  1. Build PPTX from deck workspace (deck.json + slides/*.json)
  2. LibreOffice: PPTX → PDF
  3. pdftoppm: PDF → per-page PNG
  4. Pillow: PNG → WebP (quality=85)
  5. Upload WebP previews to S3
  6. LibreOffice: PPTX → SVG (for compose + text measurement)
  7. SVG → per-slide compose JSON (for Web UI animation)
```

The agent uses `get_preview` to retrieve preview images and visually review slides.

The compose pipeline (step 6–7) extracts optimized SVG components per slide and uploads them as JSON to S3. The Web UI uses these to render animated slide transitions without re-fetching full preview images.

### Text Measurement

The `run_python(measure_slides=[...])` parameter triggers LibreOffice SVG export to measure text bounding boxes,
enabling overflow detection during the Build loop without visual review.

---

## Layer 4: Agent + Web UI

A reference implementation of a full-stack application.

- **Agent** — Strands Agent on Amazon Bedrock AgentCore Runtime, connects to Layer 3 MCP Server. Includes built-in tools: `web_fetch` (URL → Markdown, supports HTML/PDF/images)
- **Web UI** — React + Tailwind CSS + shadcn/ui, deployed via S3 + Amazon CloudFront. Features animated slide preview via SVG compose pipeline
- **API** — Lambda-backed REST API (deck CRUD, file upload, chat history)
- **Auth** — Amazon Cognito User Pool with hosted UI

The agent's system prompt is minimal — workflow knowledge is dynamically retrieved from MCP Server Instructions, making the MCP Server the single source of truth.

---

## Data Flow

### Layer 4 (Full Stack) Data Flow


![data-flow](../assets/data-flow-en.png)

### Slide Generation Steps

1. User describes the presentation content via chat
2. Agent calls MCP Server tools to create a deck (`init_presentation`)
3. Analyzes the template and retrieves available layouts (`analyze_template`)
4. Following workflow files, designs briefing → outline → art direction (persisted to `specs/`)
5. Builds slides (`run_python` to edit files in the workspace)
6. Generates PPTX (`generate_pptx`) → saved to S3, previews generated synchronously
7. Retrieves preview images for review (`get_preview`)

---

## Authentication and Authorization Model

### JWT Bearer Authentication

spec-driven-presentation-maker integrates with any OIDC-compliant IdP (Identity Provider).

![jwt-auth-flow](../assets/jwt-auth-flow-en.png)

- Amazon Bedrock AgentCore Runtime's `customJwtAuthorizer` validates the JWT
- The JWT `sub` claim is propagated as `user_id` to the application
- By default, CDK creates an Amazon Cognito User Pool (for demo/quick start)
- For external IdPs, set `oidcDiscoveryUrl` and `allowedClients` in `config.yaml`

### Authorization (Role-Based Access Control)

Access is controlled per deck (presentation).

#### Role Resolution Priority

```
1. Is the user the deck creator?     → owner
2. Is there a sharing record?        → collaborator
3. Is the deck set to public?        → viewer
4. None of the above                 → none (access denied)
```

#### Permission Matrix

| Action | owner | collaborator | viewer | none |
|---|:---:|:---:|:---:|:---:|
| read (view deck info) | ✅ | ✅ | ✅ | — |
| preview (get preview images) | ✅ | ✅ | ✅ | — |
| edit_slide (edit slides) | ✅ | ✅ | — | — |
| generate_pptx (generate PPTX) | ✅ | ✅ | — | — |
| update (update deck info) | ✅ | — | — | — |
| delete_deck (delete deck) | ✅ | — | — | — |
| change_visibility (change public setting) | ✅ | — | — | — |

Authorization logic is centralized in `shared/authz.py`, used by both the API and MCP Server.
To add custom roles (e.g., team-based access), modify the `resolve_role` function.

---

## MCP Tool Reference

### Layer 2 Tools

| Category | Tool | Description |
|----------|------|-------------|
| Workflow | `init_presentation`, `analyze_template` | Initialize deck, analyze template |
| Generation | `generate_pptx`, `get_preview` | Generate PPTX, get preview |
| Assets | `search_assets`, `list_templates` | Search icons (empty query = discovery), list templates |
| References | `list_styles`, `read_examples` | Slide style examples |
| References | `list_workflows`, `read_workflows` | Phase workflow instructions |
| References | `list_guides`, `read_guides` | Design rules and guides |
| Layout | `grid` | CSS Grid coordinate calculation |
| Utility | `code_to_slide` | Code highlighting |

### Layer 3 Additional Tools

| Tool | Description |
|------|-------------|
| `read_attachment` | Read content from an attached file with byte-offset paging |
| `import_attachment` | Import attached files into the deck workspace |
| `apply_style` | Apply a named style preset to a deck |
| `run_python` | Execute Python in Code Interpreter sandbox |
| `search_slides` | Semantic slide search (optional, requires Amazon Bedrock KB) |

### Agent-Level Tools (Layer 4)

| Tool | Description |
|------|-------------|
| `web_fetch` | Fetch a URL and convert to Markdown (supports HTML, PDF, images) |

### Tool Surface Design Notes

Deliberate asymmetries between surfaces — these are design decisions, not gaps:

- **`hearing` is ACP-only (Local) / agent-level (Cloud).** Interactive hearing
  depends on a client-side UI (the ACP session prompt on Local, the Strands
  agent loop on Cloud). Plain MCP has no interaction channel, so `hearing` is
  intentionally not part of the `sdpm.tools` contract — it is a
  transport-specific addition, which the local server is allowed to carry.
- **ACP agents have no `start_presentation`.** `start_presentation(mode=...)`
  exists for clients where the mode is decided *in conversation*. ACP agents
  are spawned with a fixed persona (definitions re-derived from `acp-agents/`
  at spawn), so the mode is already known at the entry point and a mode-fetch
  tool would be dead weight.
- **The CLI surface is kept even where MCP tools overlap.** The CLI +
  `sdpm/SKILL.md` form the no-MCP adapter (Layer 1). CLI subcommands cost no
  MCP schema tokens and are the only operability for agents without MCP
  support, so overlap with MCP tools is acceptable — they are two adapters
  over the same engine.
- **`search_slides` redesign is deferred.** The KB-backed search tool is kept
  as-is on Layer 3; rethinking it (scope, index lifecycle) is a separate
  theme, tracked outside the attachment/tool-cleanup work.

---

## CDK Stack Structure

### Stack Dependencies

![cdk-dependencies](../assets/cdk-dependencies.png)

### Stack Roles

| Stack | Resources | config.yaml Key |
|---|---|---|
| SdpmData | Amazon DynamoDB table, S3 buckets ×2, reference deployment | `stacks.data` |
| SdpmRuntime | Amazon Bedrock AgentCore Runtime + ECR | `stacks.runtime` |
| SdpmAgent | Strands Agent (Amazon Bedrock AgentCore Runtime) | `stacks.agent` |
| SdpmWebUi | S3 + Amazon CloudFront + Amazon API Gateway + Lambda | `stacks.webUi` |
| SdpmAuth | Amazon Cognito User Pool (auto-created when agent or webUi enabled) | (auto) |
| SdpmCloudFrontWaf | AWS WAF WebACL for CloudFront (us-east-1) | `waf.*` |

---

## Deployment Patterns

Select which stacks to enable in `config.yaml` for incremental deployment.

### Pattern 1: Layer 3 Only (MCP Server)

Minimum deployment. Connect directly from MCP clients.

### Pattern 2: Layer 3 + PNG Preview

Enables agents to visually review slides.

### Pattern 3: Full Stack (Layer 4)

Complete deployment including Web UI. Create slides via browser chat.

For `config.yaml` examples and deployment instructions, see [Getting Started — Layer 3](getting-started.md#layer-3-remote-mcp-server-aws).

---

## Related Documents

- [Getting Started](getting-started.md) — Setup and deployment instructions
- [Custom Templates](custom-template.md) — Adding templates and assets
- [Connecting Agents](add-to-gateway.md) — MCP client connection guide
