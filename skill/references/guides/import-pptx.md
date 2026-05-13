---
name: import-pptx
description: "Convert an uploaded PPTX into an editable deck (invoked when upload_file returns guide='import-pptx' and user intent is edit)"
category: guide
---

# Import PPTX (Edit Existing Presentation)

Invoke this guide when **both** are true:

1. `upload_file` response contains `guide: "import-pptx"`, AND
2. The user's intent is confirmed to be **editing** the PPTX (not using
   it as reference material for a new deck).

If intent is ambiguous, use the `hearing` tool **once** to confirm before
entering this guide. If the user wants to use the PPTX as reference, stop
here and follow the normal briefing flow (use `read_uploaded_file` to
access content when writing `specs/brief.md`).

## Overview

This guide is the complete workflow for the edit branch. The user already
provided the PPTX itself — that *is* the brief. Steps 1 → 6 generate
brief / outline / art-direction from the PPTX content automatically; the
only user-facing question is template selection in Step 1.

User-facing `hearing` calls in this guide:

- **Step 1** — template selection (`single_select`).
- **Step 6** — final review and hand-off to the edit loop.

Between Step 1 and Step 6, do not call `hearing`. Generate everything
from the PPTX content already in your context.

## State you must carry through the guide

The triggering `upload_file` response contains fields you reuse later:

- `uploadId` — Step 3 (`import_attachment(source=uploadId, ...)`)
- `suggestedName` — Step 2 (`init_presentation(name=suggestedName)`)
- `slideCount`, `themeHints` — Step 1 ranking and Step 5 validation

These values stay in your conversation context. If you cannot locate
them, scroll back through the prior tool responses — do not ask the
user to re-upload.

---

## Step 1 — Template selection

Goal: pick the sdpm template that best matches the source PPTX's visual tone.

1. Read `themeHints` from the `upload_file` response (`backgroundLuminance`,
   `accentColors`, `fonts`).
2. Call `read_uploaded_file(uploadId)` to see the full slide text content.
3. Call `list_templates()` to see available sdpm templates (do NOT
   hardcode template names — always use runtime values).
4. Rank 2–3 candidates using these priorities:
   - `backgroundLuminance < 0.35` → prefer dark templates (names often
     contain "dark").
   - `backgroundLuminance > 0.65` → prefer light templates.
   - Otherwise → offer both and recommend the one whose luminance is
     closer to the PPTX.
5. Use the `hearing` tool with:
   - `inference`: brief explanation of why you picked these candidates
     (dark/light luminance, dominant accent color, tone).
   - A single `single_select` question with 2–3 template names from
     `list_templates()`; mark the top candidate as `recommended`.

After the user answers, proceed to Step 2.

---

## Step 2 — Initialize the deck

Call `init_presentation(name=<suggestedName>)` — **do NOT pass a template
argument**.

- Cloud `init_presentation` has no template parameter, and Local's
  template parameter would pre-populate fonts that Step 5 immediately
  overwrites with PPTX-derived fonts. Skipping the argument keeps Local
  and Cloud symmetric.
- Template, fonts, and `defaultTextColor` are written to `deck.json` in
  Step 5.
- Returns the new `deck_id` (directory path in Local, deckId in Cloud).

---

## Step 3 — Import converted files

Call `import_attachment(source=<uploadId>, deck_id=<deck_id>)`.

The helper copies session files into the deck:

- `attachments/{shortId}_deck.json` — PPTX-derived fonts / defaultTextColor
- `attachments/{shortId}/slides/slide-NN.json` — per-slide JSON
- `images/{shortId}_*` — extracted images (flattened into deck/images/)

The returned JSON includes `shortId`, `deckJson`, and `files[]`. Keep
`shortId` — Step 4 and Step 5 need it to locate the imported per-slide
files.

---

## Step 4 — Prepare specs (brief / outline / art-direction)

Populate `specs/brief.md`, `specs/outline.md`, and
`specs/art-direction.html` **before** Step 5 places slides. Each sub-step
uses `run_python(save=True)` so the intermediate state is persisted —
Cloud discards the sandbox VM between calls, so `save=False` would lose
the write.

You generate these specs from the PPTX content you imported in Step 3.
Do not call `hearing` in Step 4 — if a particular field is thin, leave
it succinct rather than asking the user.

Sandbox helpers (`read_json / write_json / read_text / write_text /
list_files`) are available on both Local and Cloud. Do NOT use `open()`
or `import` inside the sandbox code — Local forbids both and the Cloud
import is already prepended.

### 4-1. brief.md (Source Material from PPTX)

First, explore the imported slides to extract titles and text (no save):

```python
short_id = "<result['shortId'] from Step 3>"
files = list_files(f"attachments/{short_id}/slides")
for name in sorted(files):
    data = read_json(f"attachments/{short_id}/slides/{name}")
    title = data.get("title") or ""
    if isinstance(title, dict):
        title = title.get("text", "")
    print(name, "::", title)
```

Run that via `run_python(code=<above>, deck_id=deck_id, save=False)`
(Cloud: prepend `purpose="Inspect PPTX slides"`).

Then write `specs/brief.md` in a second call with `save=True`:

```python
short_id = "<result['shortId']>"
lines = ["# Brief", "", "## Source Material", ""]
for name in sorted(list_files(f"attachments/{short_id}/slides")):
    slug = name.removesuffix(".json")
    data = read_json(f"attachments/{short_id}/slides/{name}")
    title = data.get("title") or ""
    if isinstance(title, dict):
        title = title.get("text", "")
    lines.append(f"### {slug}")
    lines.append(f"Source: attachments/{short_id}/slides/{name}")
    if title:
        lines.append(f"Title: {title}")
    lines.append("")
write_text("specs/brief.md", "\n".join(lines) + "\n")
print("brief.md written")
```

Call as `run_python(code=<above>, deck_id=deck_id, save=True)`
(Cloud: prepend `purpose="Write brief.md from PPTX content"`).

### 4-2. outline.md (LLM summarization)

Summarise each slide in one line (you, the agent, produce the summary —
the sandbox does NOT call LLMs). Pass the `(slug, message)` pairs as a
Python literal:

```python
# Agent fills this list from slide content seen in Step 1 / 4-1.
pairs = [
    ("slide-01", "Introduction to the system"),
    ("slide-02", "Storage classes overview"),
    # ... one entry per slide, matching attachments/{shortId}/slides/*.json
]
lines = [f"- [{slug}] {msg}" for slug, msg in pairs]
write_text("specs/outline.md", "\n".join(lines) + "\n")
print("outline.md written:", len(pairs))
```

Call with `run_python(code=<above>, deck_id=deck_id, save=True)`
(Cloud: add `purpose="Write outline.md from PPTX content"`).

Requirements (outline lint will otherwise reject the write on Cloud):

- Each slug MUST match the filename of an imported slide
  (`slide-01`, `slide-02`, ...) — do not rename.
- Messages MUST be non-empty.
- One line per slide, no sub-items.

### 4-3. art-direction.html (style selection)

1. Call `list_styles()` to see available styles.
2. Pick a style using these priorities:
   1. **Background luminance match** — dark style for dark PPTX, light
      for light.
   2. **Accent hue proximity** — if `themeHints.accentColors` is
      populated, prefer a style with a similar palette.
   3. **Format / tone match** — proposal vs report vs marketing based on
      slide content.
3. Call `apply_style(deck_id, <style>)` (MCP tool — not via `run_python`).

---

## Step 5 — Place slides + build + preview + compose (single `run_python`)

Copy the PPTX-derived slide JSON into `slides/`, merge deck metadata
into `deck.json`, and build the deck in a **single** `run_python` call
with `save=True`.

**Do not split Step 5 into multiple calls.** Each Cloud `run_python`
runs in a fresh sandbox VM that is discarded afterward, so intermediate
`save=False` writes are lost. Keeping Step 5 in one call ensures the
copy, S3 writeback, build, preview, and compose all share a single VM.

Assemble the slug list from Step 4-2 as a Python literal:

```python
short_id = "<result['shortId']>"
selected_template = "<template name chosen in Step 1>"
slugs = ["slide-01", "slide-02", "slide-03"]  # agent fills from Step 4-2

# 1. Merge PPTX-derived metadata into deck.json
deck = read_json("deck.json")
imported = read_json(f"attachments/{short_id}_deck.json")
deck["template"] = selected_template
deck["fonts"] = imported.get("fonts", {})
deck["defaultTextColor"] = imported.get("defaultTextColor")
write_json("deck.json", deck)

# 2. Pre-flight check — every slug must have a corresponding imported slide
missing = []
for slug in slugs:
    try:
        _ = read_json(f"attachments/{short_id}/slides/{slug}.json")
    except Exception:
        missing.append(slug)
if missing:
    print("ERROR missing:", missing)
else:
    # 3. Copy each slide JSON from attachments/ into slides/
    for slug in slugs:
        data = read_json(f"attachments/{short_id}/slides/{slug}.json")
        write_json(f"slides/{slug}.json", data)
    print("placed:", slugs)
```

Call as:

```
run_python(
    code=<above>,
    deck_id=deck_id,
    save=True,
    measure_slides=slugs,
)
```

Cloud: prepend `purpose="Import PPTX slides into deck and build"`.

Because `specs/outline.md` was populated in Step 4-2, `save=True`
triggers a full build that includes every slide, followed by preview
and SVG compose.

---

## Step 6 — Present to the user

Call `get_preview` to surface visuals:

- Local: `get_preview(slides_json_path=deck_id, pages="")`
- Cloud: `get_preview(deck_id, slugs=[...])`

Then use a single `hearing` (the second and final hearing of this
guide) to wrap up: surface what was auto-generated and let the user
direct the next edits. Suggested `inference`:

> 「PPTX を取り込んで以下の内容で deck を生成しました:
> - 概要 (brief): <briefの主旨を1〜2行>
> - 構成 (outline): <スライド数> ページ
> - スタイル: <選んだ style 名>
>
> このまま編集に進めて良いですか?他に変えたいところはありますか?」

A `free_text` question is appropriate here ("どこを変えたいですか?").
After the user responds, return control to the normal edit loop
(Cloud: `compose_slides`; Local: `use_subagent` with `sdpm-composer`).

---

## Notes on lossy conversion

`pptx_to_json` has known limitations:

- Connectors are rendered as straight lines.
- Arrow-head styles are not preserved.
- Complex gradients may render differently.

Do NOT proactively warn the user about this — the converter is tracked
for improvement separately. Address specific visual regressions only
if the user reports them after previewing the deck.
