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
provided the PPTX itself — that *is* the brief. The PPTX-derived
**placeholder template** (extracted automatically during upload and
copied into the deck as `deck/template.pptx`) means there is no template
selection step: the deck builds against the source PPTX's own layouts.

Steps 1 → 6 generate brief / outline / build / art-direction from the
PPTX content automatically; the only user-facing question is the final
review at Step 6.

The build (Step 4) runs **before** art-direction (Step 5) on purpose.
art-direction.html is consumed by the **composer** when the user
later asks to edit slides — the initial reproduction does not need
it. Building first against the source's own placeholder template
lets you read the rendered slide previews and use them as ground
truth when authoring art-direction.html.

User-facing `hearing` calls in this guide:

- **Step 6** — final review and hand-off to the edit loop.

Between Step 1 and Step 6, do not call `hearing`. Generate everything
from the PPTX content already in your context.

## State you must carry through the guide

The triggering `upload_file` response contains fields you reuse later:

- `uploadId` — Step 2 (`import_attachment(source=uploadId, ...)`)
- `suggestedName` — Step 1 (`init_presentation(name=suggestedName)`)
- `slideCount`, `themeHints` — Step 4 validation and style selection

These values stay in your conversation context. If you cannot locate
them, scroll back through the prior tool responses — do not ask the
user to re-upload.

---

## Step 1 — Initialize the deck

Call `init_presentation(name=<suggestedName>)` — **do NOT pass a template
argument**.

- Cloud `init_presentation` has no template parameter, and Local's
  template parameter would pre-populate fonts that Step 4 immediately
  overwrites with PPTX-derived fonts. Skipping the argument keeps Local
  and Cloud symmetric.
- Template (`"template.pptx"` — deck-local), fonts, and
  `defaultTextColor` are written to `deck.json` in Step 4.
- Returns the new `deck_id` (directory path in Local, deckId in Cloud).

---

## Step 2 — Import converted files

Call `import_attachment(source=<uploadId>, deck_id=<deck_id>)`.

The helper copies session files into the deck:

- `template.pptx` — PPTX-derived placeholder template (deck root)
- `attachments/{shortId}_deck.json` — PPTX-derived fonts / defaultTextColor
- `attachments/{shortId}/slides/slide-NN.json` — per-slide JSON
- `images/{shortId}_*` — extracted images (flattened into deck/images/)

The returned JSON includes `shortId`, `templatePath`, `deckJson`, and
`files[]`. Keep `shortId` — Step 3 and Step 4 need it to locate the
imported per-slide files.

---

## Step 3 — Prepare brief and outline

Populate `specs/brief.md` and `specs/outline.md` **before** Step 4
builds the deck. `specs/art-direction.html` is intentionally deferred
to Step 5 — the rendered slide previews from Step 4 are a far better
input for it than the upload-time image extraction. Each sub-step
uses `run_python(save=True)` so the intermediate state is persisted —
Cloud discards the sandbox VM between calls, so `save=False` would
lose the write.

You generate these specs from the PPTX content you imported in Step 2.
Do not call `hearing` in Step 3 — if a particular field is thin, leave
it succinct rather than asking the user.

Sandbox helpers (`read_json / write_json / read_text / write_text /
list_files`) are available on both Local and Cloud. Do NOT use `open()`
or `import` inside the sandbox code — Local forbids both and the Cloud
import is already prepended.

### 3-1. brief.md (Source Material from PPTX)

First, explore the imported slides to extract titles and text (no save):

```python
short_id = "<result['shortId'] from Step 2>"
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

### 3-2. outline.md (LLM summarization)

Summarise each slide in one line (you, the agent, produce the summary —
the sandbox does NOT call LLMs). Pass the `(slug, message)` pairs as a
Python literal:

```python
# Agent fills this list from slide content seen in Step 3-1.
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

---

## Step 4 — Place slides + build + preview + compose (single `run_python`)

Copy the PPTX-derived slide JSON into `slides/`, merge deck metadata
into `deck.json` (using the deck-local `template.pptx`), and build the
deck in a **single** `run_python` call with `save=True`.

**Do not split Step 4 into multiple calls.** Each Cloud `run_python`
runs in a fresh sandbox VM that is discarded afterward, so intermediate
`save=False` writes are lost. Keeping Step 4 in one call ensures the
copy, S3 writeback, build, preview, and compose all share a single VM.

Assemble the slug list from Step 3-2 as a Python literal:

```python
short_id = "<result['shortId']>"
slugs = ["slide-01", "slide-02", "slide-03"]  # agent fills from Step 3-2
# image_mapping is in the import_attachment result. It maps the original
# converter-emitted filename (e.g. "slide1_image1.png") to its
# deck-relative path after rename (e.g. "images/<shortId>_slide1_image1.png").
image_mapping = {<paste image_mapping dict from Step 2 result here>}

# 1. Merge PPTX-derived metadata into deck.json (deck-local placeholder template)
deck = read_json("deck.json")
imported = read_json(f"attachments/{short_id}_deck.json")
deck["template"] = "template.pptx"  # deck-local; copied by import_attachment
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
    # 3. Copy each slide JSON from attachments/ into slides/, rewriting
    #    image src refs through image_mapping. import_attachment renames
    #    extracted images (e.g. "slide1_image1.png" → deck/images/<shortId>_slide1_image1.png),
    #    so the converter-emitted src strings ("images/slide1_image1.png")
    #    no longer resolve and the build silently drops the picture.
    def _rewrite_image_refs(node):
        if isinstance(node, dict):
            if node.get("type") == "image" and isinstance(node.get("src"), str):
                src = node["src"]
                # src looks like "images/<original_name>"
                base = src.split("/", 1)[1] if src.startswith("images/") else src
                mapped = image_mapping.get(base)
                if mapped:
                    node["src"] = mapped
            for v in node.values():
                _rewrite_image_refs(v)
        elif isinstance(node, list):
            for item in node:
                _rewrite_image_refs(item)

    for slug in slugs:
        data = read_json(f"attachments/{short_id}/slides/{slug}.json")
        _rewrite_image_refs(data)
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

Because `specs/outline.md` was populated in Step 3-2, `save=True`
triggers a full build that includes every slide, followed by preview
and SVG compose. The PPTX-derived placeholder template means **layout
mismatch is impossible** — the build should succeed in one shot.

After the `run_python` call returns successfully, call
`generate_pptx(deck_id=deck_id)` once. This persists `output.pptx`
to the deck workspace and updates the deck record's `pptxS3Key`, so
the Web UI can offer a "Download PPTX" button immediately. Without
this call the UI sees no PPTX yet and hides the download action,
even though the slides have rendered.

---

## Step 5 — art-direction.html (deck-specific style)

Goal: produce a `specs/art-direction.html` that **describes the source
PPTX's visual identity**, written from scratch, expressed in the same
authoring conventions the built-in sdpm styles use.

The output is **the source PPTX's own style sheet**. The composer
reads this file as the single source of truth for colors, typography,
decoration motifs, and component patterns when the user later asks
to **edit** slides. The initial reproduction in Step 4 does not
consume art-direction.html — running it after build means you can
read the actual rendered slide previews as the most reliable input.

### 5-1. Read a reference scaffold

`apply_style` copies one of the built-in styles to
`specs/art-direction.html` for you to **reference how art-direction
files are written** (CSS-variable conventions, slide dimensions,
class naming, the structure of the `<style>` block, the demonstration
slide layout in `<body>`). Treat its colors / fonts / decorations as
**examples of how to write tokens, not as values to keep**.

1. Call `list_styles()`.
2. Pick any scaffold — choose whichever you can read most easily.
   The selection has no effect on the final output.
3. Call `apply_style(deck_id, <scaffold>)` (MCP tool — not via
   `run_python`).
4. Read the copied file once with `read_text("specs/art-direction.html")`
   to refresh the authoring conventions in your context.

### 5-2. Extract the source PPTX's actual design tokens

`themeHints` from `upload_file` is a coarse summary (a single
background luminance, three accent colors, two font families). The
source PPTX's master/theme XML and the **rendered slide previews
generated in Step 4** carry far more precise data — layout positions,
every theme color slot, true background fills, and the actual color
frequencies on each slide.

**Theme XML / layouts via `analyze_template`:**

Call the MCP tool on the deck-local template (`template.pptx` was
copied here in Step 2 by `import_attachment`). It returns the full
theme color map (lt1 / dk1 / accent1-6 / hlink / folHlink), font
pairs (latin/eastAsian/complex), and per-layout placeholder
positions.

```python
result = analyze_template(template="template.pptx")  # MCP tool
# Cloud: this is an MCP tool, not a run_python call
```

Capture from the result:
- `theme_colors` — the canonical 12 theme slots. Use these as the
  primary source for `--color-*` tokens. accent1-6 names map to
  whatever the source PPTX intends (corporate primary, secondary,
  highlight, etc.). Read every accent — `themeHints.accentColors`
  truncates to 3.
- `fonts.latin / fonts.eastAsian / fonts.complex` — carry these
  through verbatim. Don't substitute with system fonts unless the
  source explicitly uses one.
- `layouts[]` — placeholder positions per layout. Use these to size
  cover title, slide title, content area in `--size-*` and the
  body x/y/width/height in your demonstration slides.

**Per-slide actual colors via PIL on rendered previews:**

Theme XML tells you what colors are *defined*; the rendered slide
previews tell you what's actually *used* and in what proportion.
Step 4's build produced PNG previews under `previews/` — these are
the slides as they'll actually appear. Sample dominant hex values
from a few representative previews:

```python
from collections import Counter
from PIL import Image
import os

# Step 4 wrote rendered slide previews here
preview_files = sorted(p for p in os.listdir("previews") if p.endswith(".png"))
sample = preview_files[:6]  # cover + a few content slides
all_pixels = []
for f in sample:
    img = Image.open(os.path.join("previews", f)).convert("RGB").resize((150, 150))
    all_pixels.extend(img.getdata())
common = Counter(all_pixels).most_common(20)
# Convert RGB tuples to #RRGGBB hex
swatches = ["#{:02X}{:02X}{:02X}".format(r, g, b) for (r, g, b), _ in common]
print("Top 20 hex by pixel frequency:", swatches)
```

Cross-reference these swatches with `theme_colors`:
- Frequencies near `theme_colors.lt1 / dk1` confirm the **actual
  background** (which may differ from `themeHints.backgroundLuminance`
  if the deck uses a non-default master).
- Frequencies near `theme_colors.accent1` confirm which accent is
  the deck's hero color (the most-used one is rarely accent1 — pick
  the most-frequent accent that isn't bg/text).
- Outliers (high frequency but no match) are deck-specific brand
  colors not declared in the theme — capture them as their own
  tokens (`--color-brand-orange`, etc.).

### 5-3. Rewrite the file as the source PPTX's own style

Now write a fresh `specs/art-direction.html` that captures the source
PPTX's visual system. Use only signals you can ground in the source,
in this order of authority:

1. **`analyze_template` output** — theme XML colors, fonts, layout
   positions. These are the original PPTX's authoring values, not
   guesses.
2. **PIL pixel-frequency swatches from `previews/`** — confirms which
   theme entries are actually on screen, and surfaces brand colors
   not in the theme.
3. **`themeHints` from `upload_file`** — fall back to this only when
   `analyze_template` and PIL agree it's representative; treat it as
   a sanity check rather than a primary source.
4. **Slide JSON in `slides/`** (now placed by Step 4) — sample text
   colors, bullet styles, divider lines, banner shapes, card
   backgrounds, font weights, spacing patterns that recur across
   the deck.
5. **Slide preview thumbnails** — use them to confirm decoration
   motifs (line styles, shadows, corner shapes, accent bars, icon
   framing) before encoding them.

Compose the new document in your context, then write it in a single
`run_python(save=True)` call:

```python
new_art = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title><name of the source-PPTX visual system></title>
<style>
  :root {
    /* Colors — every value below must be source-derived */
    --color-primary: <text color seen in source titles>;
    --color-accent:  <theme_colors.accent1 or PIL hero accent>;
    --color-bg:      <theme_colors.lt1 or PIL dominant bg hex>;
    /* ...add as many tokens as the source needs, name them after the
       role they play in the source (e.g. --color-banner, --color-divider).
       Don't carry over scaffold-specific tokens (gold-frame, diamond,
       etc.) unless the source uses an analogous element. */

    /* Typography — pulled from analyze_template fonts */
    --font-heading: <fonts.latin or eastAsian primary>;
    --font-body:    <same family as heading unless source uses a pair>;

    /* Sizes / spacing / decoration tokens */
    --size-cover-title: <pt seen in source cover>;
    /* ... */
  }

  body { margin: 0; padding: 40px; background: #E5E5E5; zoom: 0.7; }
  .slide { position: relative; width: 1920px; height: 1080px; margin: 0 auto 40px; background: var(--color-bg); overflow: hidden; }
  .el { position: absolute; }

  /* Text styles — keep the t-* class naming the scaffolds use so the
     composer's reference points still resolve. Define each to match
     the source: font-family, size, weight, color, line-height, etc. */
  .t-cover-title { /* ... */ }
  .t-slide-title { /* ... */ }
  .t-section-header { /* ... */ }
  .t-body { /* ... */ }
  .t-caption { /* ... */ }

  /* Components — define ONLY the decoration motifs the source PPTX
     actually uses. Drop the scaffold's gold-frame / diamond / etc.
     and add what's really there: e.g. orange accent bar, soft shadow
     card, square bullet list, subtle 1px divider. */
  .accent-bar { /* ... */ }
  .card        { /* ... */ }
  .divider     { /* ... */ }
</style>
</head>
<body>

<!-- Demonstration slides — show the composer how the system applies.
     Mirror the demo-slide structure of the scaffolds (cover slide +
     palette slide + a few content variants), but every value must be
     source-derived. -->

<div class="slide">
  <!-- Cover slide rendered with the source's palette and motifs -->
</div>

<div class="slide">
  <!-- Color palette swatches with the source's actual hex values -->
</div>

<!-- ... -->

</body>
</html>
"""
write_text("specs/art-direction.html", new_art)
print("art-direction.html written for source PPTX")
```

(Cloud: prepend `purpose="Author art-direction.html from rendered previews"`.)

Guidelines:

- **The scaffold is reference-only.** Look at it to learn the
  authoring conventions, then write fresh content. Do not preserve
  scaffold-specific colors, fonts, or decoration classes that don't
  match the source.
- **Every token must be source-grounded.** If you don't have evidence
  (theme_colors, PIL swatches, slide JSON, preview), don't invent —
  leave that token out. Defining fewer tokens is better than
  fabricating them.
- **Keep the structural conventions.** 1920×1080 `.slide`, absolute
  `.el` placement, `t-*` text class names, `:root` token block,
  demonstration slides at the bottom of `<body>`. These are what the
  composer expects.
- **No re-build is needed after writing art-direction.html.** Step 4
  already produced an as-is reproduction the user can review. The
  file you write here is consumed by the composer the next time the
  user asks to edit slides — at that point compose_slides reads it
  and applies it to whatever slides change. Until then, the deck
  stays at its Step 4 state.

---

## Step 6 — Present to the user

Call `get_preview` to surface visuals:

- Local: `get_preview(slides_json_path=deck_id, pages="")`
- Cloud: `get_preview(deck_id, slugs=[...])`

Then use a single `hearing` (the only user-facing hearing of this
guide) to wrap up: surface what was auto-generated and let the user
direct the next edits. Suggested `inference`:

> 「PPTX を取り込んで以下の内容で deck を生成しました:
> - 概要 (brief): <briefの主旨を1〜2行>
> - 構成 (outline): <スライド数> ページ
> - art-direction: 元 PPTX の theme XML とプレビュー画像から抽出したスタイル
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
