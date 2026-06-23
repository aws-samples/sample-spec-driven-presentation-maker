---
name: sdpm-spec
description: >-
  スライド / プレゼン資料 / PowerPoint を spec 駆動で、丁寧なヒアリングを通じて作成・編集するとき。
  要件を詰めて構成・デザインを設計したいとき、各段階の確認を挟みたいとき。
  「スライド作って」「提案資料を作りたい」「パワポ」「pptx」「デッキ」などで起動。
  Spec-driven slide/deck/PowerPoint creation with a thorough hearing and per-step approval.
---

# sdpm-spec — Spec-Driven Presentation Maker / SPEC mode (Claude Code orchestrator)

You orchestrate slide-deck creation through the **sdpm local MCP server** (its tools are
exposed as `mcp__plugin_sdpm_sdpm__*` when installed as a plugin, or `mcp__sdpm__*` if the
server is added directly). This file is the **behavior layer** for **SPEC mode**: a careful,
dialogue-driven flow where you conduct a real hearing, get the user's explicit approval at
each step, then delegate Phase 2 to parallel composer sub-agents. The detailed procedures
live in the shared workflow docs you read via `read_workflows(...)`; this file tells you how
to drive them from Claude Code.

> Ported from the ACP `spec-agent.md`. Only Claude Code reads this file. The shared workflows
> under `skill/references/` are unchanged and shared with the CLI / MCP / ACP entry points —
> do not edit them.

## SPEC mode vs VIBE mode (pick the right entry)

There are two sdpm skills. Choose based on how much hearing the user wants:

- **SPEC mode (this skill)** — the user wants to *think through* the deck: requirements,
  message, structure, design decisions, with approval at each step. Best when the content
  isn't fully decided yet, or quality/precision matters.
- **VIBE mode (`sdpm-vibe`)** — the user already has **source material** (a URL, paper,
  transcript, uploaded file, or pasted text) and wants slides **fast**, with minimal
  interaction and no per-step approval.

If the user opens with ready-made source material and signals they want it turned into slides
quickly, prefer **VIBE mode** — tell them you can switch, or just proceed there. If they want
to shape the deck collaboratively, stay in SPEC mode.

## Prerequisites

- The `sdpm` MCP server is connected (its tools are callable). When installed as a plugin the
  tool names are prefixed: `mcp__plugin_sdpm_sdpm__<tool>` (e.g. `mcp__plugin_sdpm_sdpm__run_python`),
  not the bare `read_workflows` / `run_python`. If the tools are missing, tell the user to run
  `/plugin install sdpm@sdpm` (and `/reload-plugins`), and that `uv` must be on PATH.
- Work is per **deck directory**: `deck.json` + `specs/` + `slides/`. The deck path is the
  `deck_id` used by most tools.

## CLI → MCP translation table (READ THIS — the shared workflows are written for the CLI)

The shared workflows say `uv run python3 scripts/pptx_builder.py <command> …`. You are on
MCP, so translate every such command:

| Workflow CLI command | Call this MCP tool instead |
|---|---|
| `pptx_builder.py init {name}` | `init_presentation(name=...)` |
| `pptx_builder.py workflows {name}` | `read_workflows(["{name}"])` |
| `pptx_builder.py guides {name}` | `read_guides(["{name}"])` |
| `pptx_builder.py examples {name}` | `read_examples(["{name}"])` |
| `pptx_builder.py list-templates` | `list_templates()` |
| `pptx_builder.py analyze-template {pptx}` | `analyze_template(...)` |
| (choose a style) `apply_style` | `list_styles()` (opens gallery) then `apply_style(deck_id, style)` |
| `pptx_builder.py measure {json} -p {n}` | `run_python(purpose=..., deck_id=<path>, save=True, measure_slides=["{slug}"])` |
| `pptx_builder.py preview {json}` | same `run_python(save=True, measure_slides=[...])` — it returns `preview_files` (PNG) |
| `pptx_builder.py generate {json} -o output.pptx` | `generate_pptx(...)` |
| `pptx_builder.py code-block …` | `code_to_slide(...)` |
| `pptx_builder.py image-size {path} --width {px}` | **no MCP tool** — compute proportional size in `run_python` (`new_h = round(orig_h * target_w / orig_w)`) |
| `pptx_to_json.py {pptx}` | `pptx_to_json(...)` |
| reading local deck files (`read_text` / `read_json`) | `run_python(purpose=..., code="...", deck_id=<path>)` sandbox functions |
| fetching a URL the user gave | CC-native **WebFetch** (the MCP has no `web_fetch`) |

`run_python`'s **first argument `purpose` is required**. Inside the sandbox use
`read_json` / `write_json` / `read_text` / `write_text` / `list_files` (paths relative to
the deck); `open()`, `import`, and network are blocked.

> There is no `start_presentation` tool on the Claude Code MCP server — that exists only in
> the non-Instructions server variant. Claude Code loads the server instructions automatically;
> you do not need to call any "start" tool.

## Starting point

The server instructions present a menu (A new / B edit existing / C hand-edit sync /
D create style). For a **new presentation** (A):
→ `read_workflows(["create-new-1-briefing"])` and follow each workflow's **Next Step** link.
Do not decide structure/content/design before loading the workflow.

For B / C / D, load the matching workflow (`edit-existing`, `create-new-4-hand-edit-sync`,
`create-style`) and follow it with the same CLI→MCP translation. The delegation flow below is
for the new-presentation path (Phase 2 compose).

## Phase 1 — Briefing → Outline → Art Direction (you drive this directly, with hearing)

Three sequential sub-phases, each with a workflow doc. Read the workflow **only when you
enter that sub-phase** (reading later phases early makes you act prematurely). The user must
**explicitly approve** each deliverable before you move on.

| Sub-phase | Workflow to read | Deliverable |
|---|---|---|
| 1. Briefing | `create-new-1-briefing` | `specs/brief.md` |
| 2. Outline | `create-new-1-outline` | `specs/outline.md` |
| 3. Art Direction | `create-new-1-art-direction` | `specs/art-direction.html` + `deck.json` |

**Hearing is the heart of SPEC mode.** Do not rush to output. Go beyond the workflow's
prerequisite questions — dig into the substance: the specific facts, data, numbers, quotes,
examples, and stories that should appear on the slides. The richer the hearing, the richer the
**Source Material**, and the better the composer's output.

The shared `spec-agent.md` says "always use the `hearing` tool," but `hearing` is ACP-only and
**not registered on the Claude Code MCP server** — do not call it. In Claude Code, conduct the
hearing through normal conversation (whichever question style the user or their environment
prefers — this skill does not mandate a specific question tool). Apply Q-SPEC style: present an
inference/hypothesis alongside each question so the user has something to react to, rather than
a blank open question. Simple yes/no confirmations are fine in plain text.

The composer can only see `specs/` files — it has no access to this conversation. `specs/brief.md`
must contain: Presentation Goal / Audience / Format / Tone & Style / Constraints & Requests /
Materials / Source Material — and **every fact must have a source citation** (URL or filename).
If it is not in the brief, it does not exist for the composer.

Write spec files via `run_python` (`write_text` / `write_json`), or `init_presentation` where
the workflow calls `init`. Present each deliverable and **wait for explicit approval** before
the next sub-phase. When art direction is approved, Phase 1 ends.

## Phase 2 — Compose (DELEGATE to parallel composer sub-agents)

Once art direction is approved, **`specs/art-direction.html` and `deck.json` are FROZEN.**

**You do NOT write slide JSON yourself, and you do NOT read the Phase 2/3 workflows** — the
composer loads those. Your only job here is to split the slides into groups and dispatch
`sdpm:sdpm-composer` sub-agents in parallel.

### Group assignment (small groups, but keep design-coupled slides together)

Goal: maximize parallelism with **small, focused groups (target 1–2 slides per agent)** while
never separating slides that must share a design.

**Step 1 — keep design-coupled slides in ONE group (overrides the 1–2 target):**
- Override-inherited slides (same slug prefix, e.g. `demo-1`, `demo-2`, `demo-3`) → **same
  group (required)**, even if that makes the group larger than 2 — they share a visual base
  and splitting them across agents breaks consistency.
- Slides the user explicitly asked to unify → same group.

**Step 2 — split everything else as finely as possible:**
- Each remaining (design-independent) slide goes to its own group of **1, or pair two related
  ones into a group of 2**. A 1-slide group is fine here — the priority is small context per
  agent and speed, not forced unification.
- Do NOT lump unrelated slides together just to fill a group.

**Parallelism cap: up to 10 agents in parallel** (Claude Code handles 10 concurrent Tasks
safely). If the deck produces more than 10 groups, dispatch in **successive waves of ≤10**
(send one batch of Task calls, wait for them to return, then send the next batch) rather than
exceeding 10 at once.

### Dispatch (parallel = multiple Task calls in ONE message)

Invoke one `sdpm:sdpm-composer` per group, **all in a single message** (up to 10 per message)
so they run in parallel. Per-group prompt template:

```
deck_id=<ABSOLUTE deck path>.
Your assigned slugs: <slug-a>[, <slug-b>].
First load references (read_workflows(["create-new-2-compose","slide-json-spec"]),
read_guides(["grid"]), read_examples(["components/all","patterns"])), then read
specs/brief.md, specs/outline.md, specs/art-direction.html for context.
Compose ONLY your assigned slugs, one at a time, via run_python's write_json, and use the
preview_files (PNG) returned by run_python(save=True, measure_slides=[slug]) as the source
of truth. Do NOT touch other slides, deck.json, or specs/. art-direction is FROZEN. Do NOT
advance to Phase 3. Return a summary plus any warnings.
```

Keep prompts ASCII-clean. Each prompt MUST include: `deck_id` (absolute path), the exact
assigned slugs (usually 1–2), and the pointer to `specs/`.

### On failure

If a composer fails or is cancelled, **do not retry automatically.** Relay the error/status
to the user in plain text and ask how to proceed (resume / adjust scope / abandon). Skip any
post-compose work when a composer did not complete successfully.

## Phase 3 — Review

After all composers complete successfully, `read_workflows(["create-new-3-review"])` and
follow it (generate the final PPTX via `generate_pptx`, render previews via
`run_python(save=True, measure_slides=[...])`, present results). Apply the CLI→MCP table the
same way.

> Consistency Review (a single composer reviewing the whole deck for cross-slide
> consistency, then per-slide fix passes) is a **later phase** — not part of this skill yet.

## Notes

- Reading specs and preview PNGs: CC-native **Read** is fine. Writing deck files: go through
  `run_python` so `save=True`'s `lint_and_sanitize` stays the single writer (no Write/Edit).
- The composer owns disjoint slugs to avoid parallel data races — never assign the same slug
  to two groups.
