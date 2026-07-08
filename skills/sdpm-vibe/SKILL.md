---
name: sdpm-vibe
description: >-
  手元の素材（URL・論文・議事録・PDF・貼り付けテキスト）から、ヒアリング最小・確認なしで
  スライド / プレゼン / PowerPoint を一気に高速生成するとき。
  「これをスライドにして」「このURLから資料作って」「ざっとパワポに」などで起動。
  Rapid slide/deck/PowerPoint generation from existing source material, minimal interaction.
---

# sdpm-vibe — Spec-Driven Presentation Maker / VIBE mode (Claude Code orchestrator)

You orchestrate **rapid, material-based** slide generation through the **sdpm local MCP
server** (its tools are exposed as `mcp__plugin_sdpm_sdpm__*` when installed as a plugin, or
`mcp__sdpm__*` if the server is added directly). This file is the **behavior layer** for
**VIBE mode**: the user already has source material and wants slides fast, without a full
hearing and without per-step approval. You run Phase 1 autonomously, then delegate Phase 2
to parallel composer sub-agents.

> Ported from the ACP `vibe-agent.md`. Only Claude Code reads this file. The shared workflows
> under `skill/references/` are unchanged and shared with the CLI / MCP / ACP entry points —
> do not edit them.

## VIBE mode vs SPEC mode (pick the right entry)

- **VIBE mode (this skill)** — material-based conversion. The user has a URL, paper,
  transcript, uploaded file, or pasted text and wants slides **quickly**, minimal interaction.
- **SPEC mode (`sdpm-spec`)** — dialogue-driven. The user wants to shape requirements,
  structure, and design with a real hearing and approval at each step.

**Scope of this skill:** VIBE mode focuses on **creating a NEW deck from source material**.
If the user instead wants to edit an existing PPTX (B), sync hand edits (C), or build a reusable
style (D), use **SPEC mode (`sdpm-spec`)**, which carries those workflows.

If the user has no source material and wants to think the deck through, switch to **SPEC mode**.

## Prerequisites

- The `sdpm` MCP server is connected (its tools are callable). When installed as a plugin the
  tool names are prefixed: `mcp__plugin_sdpm_sdpm__<tool>` (e.g. `mcp__plugin_sdpm_sdpm__run_python`),
  not the bare `read_workflows` / `run_python`. If the tools are missing, tell the user to run
  `/plugin install sdpm@sdpm` (and `/reload-plugins`), and that `uv` must be on PATH.
- Work is per **deck directory**: `deck.json` + `specs/` + `slides/`. The deck path is the
  `deck_id` used by most tools.
- Write all spec files (`brief.md`, `outline.md`, `art-direction.html`) in the user's language.

## CLI → MCP translation table (READ THIS — the shared workflows are written for the CLI)

| Workflow CLI command | Call this MCP tool instead |
|---|---|
| `pptx_builder.py init {name}` | `init_presentation(name=...)` |
| `pptx_builder.py workflows {name}` | `read_workflows(["{name}"])` |
| `pptx_builder.py guides {name}` | `read_guides(["{name}"])` |
| `pptx_builder.py examples {name}` | `read_examples(["{name}"])` |
| `pptx_builder.py list-templates` | `list_templates()` |
| `pptx_builder.py analyze-template {pptx}` | `analyze_template(...)` |
| (choose a style) `apply_style` | `list_styles()` then `apply_style(deck_id, style)` |
| `pptx_builder.py measure {json} -p {n}` | `run_python(purpose=..., deck_id=<path>, save=True, measure_slides=["{slug}"])` |
| `pptx_builder.py generate {json} -o output.pptx` | `generate_pptx(...)` |
| `pptx_builder.py image-size {path} --width {px}` | **no MCP tool** — compute proportional size in `run_python` (`new_h = round(orig_h * target_w / orig_w)`) |
| reading local deck files (`read_text` / `read_json`) | `run_python(purpose=..., code="...", deck_id=<path>)` sandbox functions |
| fetching a URL the user gave | CC-native **WebFetch** (the MCP has no `web_fetch`) |
| importing an uploaded file / remote image into the deck | `import_attachment(source, deck_id)` |

`run_python`'s **first argument `purpose` is required**. Inside the sandbox use
`read_json` / `write_json` / `read_text` / `write_text` / `list_files` (paths relative to
the deck); `open()`, `import`, and network are blocked. There is no `start_presentation` tool
on the Claude Code MCP server — you do not need to call any "start" tool.

## Vibe behavior — fast, minimal interaction

- If the user's first message contains source material (URL, file, pasted text), **proceed
  immediately** — do not ask for confirmation.
- If there is **no** source material, ask exactly ONE question:
  *"What would you like to turn into slides?"* — that is the **only** pause.
- Do **NOT** conduct multi-turn hearings or requirement gathering.
- Do **NOT** ask the user to review/approve the brief, outline, or art direction.
- Do **NOT** present choices for confirmation before composing.
- Move as fast as possible from material to finished slides.
- You are responsible for **Phase 1 only**. Do NOT read Phase 2 or later workflows — the
  composer loads those. You do NOT write slide JSON yourself.

## Vibe Workflow (Steps 1–5 in order, then delegate in Step 6)

**CRITICAL:** You MUST complete Steps 1–5 IN ORDER before Step 6. Delegating to composers
before `specs/brief.md` and `specs/outline.md` exist will FAIL — the composer reads `specs/`
and has no other source of information. There are no shortcuts. Execute steps sequentially
**without waiting for user input**.

### Step 1 — Read source material
Read everything the user provided: URLs via CC-native **WebFetch**, uploaded files (bring them
in via `import_attachment(source, deck_id)` once the deck exists, or read inline text). For
long documents, paginate to read the **full** content — do not stop at the first page.

### Step 2 — Initialize
Call `init_presentation(name)` to create the working directory (`deck.json`, `specs/`, `slides/`).

### Step 3 — Write `specs/brief.md` (MANDATORY)
The composer cannot work without this file. Write it via
`run_python(purpose=..., deck_id=<path>, code='write_text("specs/brief.md", content)')`.
Include **all** data points, numbers, quotes, facts, technical details, and references
extracted from the source — with citations. This file is the composer's only source of truth.
Recommended sections: Presentation Goal / Audience / Format / Tone & Style / Constraints &
Requests / Materials / Source Material.

### Step 4 — Write `specs/outline.md` (MANDATORY)
Write it via `run_python(purpose=..., deck_id=<path>, code='write_text("specs/outline.md", content)')`.
Derive a logical slide structure from the brief. Each line = 1 slide = 1 message:
```
- [slug] What it changes in the audience and how
```
Rules: aim for **5–15 slides** unless the material demands more; use shared **slug prefixes**
for slides that build on the same visual base (e.g. `demo-1`, `demo-2`); each slide has exactly
one message.

### Step 5 — Art direction
1. Call `list_styles()` to see available styles.
2. Choose the style that best fits the brief's purpose, audience, and tone (if the user
   specified a style/tone, honor that instead of inferring).
3. Call `apply_style(deck_id, style)` to set art direction.
4. Read `specs/art-direction.html` via `run_python` (`read_text("specs/art-direction.html")`),
   extract the `:root` CSS variables, then update `deck.json` via `write_json`:
   ```json
   {
     "template": "{template}.pptx",
     "fonts": {"fullwidth": "{fullwidth font}", "halfwidth": "{halfwidth font}"},
     "defaultTextColor": "{--color-text value}"
   }
   ```
After Step 5, **`specs/art-direction.html` and `deck.json` are FROZEN.**

### Step 6 — Compose (DELEGATE to parallel composer sub-agents)
Prerequisite: Steps 2–5 complete. Split slides into groups and dispatch `sdpm:sdpm-composer`
sub-agents in parallel.

**Group assignment (small groups, keep design-coupled slides together):**
- **Step 1 — keep design-coupled slides in ONE group:** override-inherited slides (same slug
  prefix, e.g. `demo-1`, `demo-2`) → same group (required), even if larger than 2; slides the
  user asked to unify → same group.
- **Step 2 — split everything else as finely as possible:** each remaining design-independent
  slide → its own group of 1, or pair two related ones into a group of 2. 1-slide groups are
  fine. Do NOT lump unrelated slides together, and do NOT split by outline order.
- **Parallelism cap: up to 10 agents in parallel** (Claude Code handles 10 concurrent Tasks
  safely). If there are more than 10 groups, dispatch in successive waves of ≤10.

**Dispatch:** invoke one `sdpm:sdpm-composer` per group, **all in a single message** (up to 10)
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

## After compose

Only when composers complete successfully:
1. Review the reports and `preview_files` (PNG) the composers returned.
2. Generate the final deck: `read_workflows(["create-new-3-review"])`, build via
   `generate_pptx`, render previews via `run_python(save=True, measure_slides=[...])`.
3. Present the result to the user with the preview images.
4. For modification requests, translate them into instructions and invoke composers again
   (target only the affected slugs; describe the problem, not the solution).

## On failure

If a composer fails or is cancelled, **do not retry automatically.** Relay the error/status to
the user in plain text and ask how to proceed (resume / adjust scope / abandon). Skip the
after-compose steps entirely when a composer did not complete successfully.

## Notes

- Reading specs and preview PNGs: CC-native **Read** is fine. Writing deck files: go through
  `run_python` so `save=True`'s `lint_and_sanitize` stays the single writer (no Write/Edit).
- The composer owns disjoint slugs to avoid parallel data races — never assign the same slug
  to two groups.
