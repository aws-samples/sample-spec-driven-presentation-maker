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
- `attachments/{shortId}/slides/slide-NNN.json` — per-slide JSON
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
    ("slide-001", "Introduction to the system"),
    ("slide-002", "Storage classes overview"),
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
  (`slide-001`, `slide-002`, ...) — do not rename.
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
slugs = ["slide-001", "slide-002", "slide-003"]  # agent fills from Step 3-2
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
            # Faithful reproduction: spread _originalEffects (crop, mask,
            # brightness...) into the element. The builder ignores the
            # underscore key by design — without this the original image
            # framing (e.g. a full-width cropped photo band) is lost.
            # Only skip this when you intentionally reuse the image as
            # fresh material in a NEW slide of your own design.
            oe = node.pop("_originalEffects", None)
            if oe:
                for k, v in oe.items():
                    node.setdefault(k, v)
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
PPTX's visual identity as a style specification** — design tokens
plus 5-6 demonstration slides that show *how the design rules apply*,
not what the source deck contained.

The output follows the same conventions as every other sdpm style:

- `:root` block with all design tokens as CSS variables (the style's
  *machine-readable specification* — composer reads `var()`
  references, not pixel values).
- 5-6 demonstration slides (cover, palette / type ramp / component
  swatches / ...). Each slide demonstrates the design while
  explaining the reasoning. This is **NOT** a re-render of the
  source deck's content slides.
- 1920×1080 absolute positioning, pt units, `.t-*` text classes,
  `.el` for absolute elements. (See `create-style` workflow for the
  full rule list.)

The composer reads this file when the user later asks to **edit**
slides — it consumes the tokens, not the demonstration markup.

> **Critical reframe:** art-direction.html is a *style guide*, not a
> reproduction. If your demonstration slides contain the source
> deck's headlines, bullet points, charts, or specific data, you've
> written the wrong artifact. Demonstration slides should contain
> placeholder text like "Cover Title" / "Section header" / "Body
> sample with **bold** and accent" that exists purely to show how
> the design rules render.

### 5-1. Load the style-authoring workflow + scaffold

`create-style.md` is the canonical workflow for authoring sdpm
styles. **Read it first** so you understand what tokens to define,
the demonstration slide pattern, and the critical CSS rules. The
authoring conventions there apply unchanged to art-direction.html;
this guide only adds the import-pptx-specific signal extraction in
Step 5-2.

```
read_workflows(["create-style"])
```

Key conventions you must follow (full list in the workflow):
- All design tokens in `:root` as CSS variables.
- All colors via `var()` references — never hardcoded in elements.
- Text style classes (`.t-cover-title`, `.t-slide-title`, `.t-body`,
  ...) reference CSS variables. Use class names consistently.
- Component classes (`.card`, `.accent-bar`, `.divider`, ...) also
  via CSS variables.
- Inline `style="..."` only for `left / top / width / height`.
- 5-6 demonstration slides (cover + design areas) — NOT the source
  deck's slides.

Then pull a built-in style as a structural reference:

1. Call `list_styles()`.
2. Pick any scaffold — choose whichever you can read most easily.
   The selection has no effect on the final output.
3. Call `apply_style(deck_id, <scaffold>)` (MCP tool — not via
   `run_python`).
4. Read the copied file once with `read_text("specs/art-direction.html")`
   to confirm the demonstration-slide pattern (cover slide first,
   palette swatches, type ramp, then a couple of component-only
   variants). Treat its colors / fonts / decorations as
   **structural examples**, not values to keep.

### 5-2. Extract the source PPTX's actual design tokens

`themeHints` from `upload_file` is a coarse summary (a single
background luminance, three accent colors, two font families). The
source PPTX's master/theme XML and the **rendered slide previews
generated in Step 4** carry far more precise data — layout positions,
every theme color slot, true background fills, and the actual color
frequencies on each slide.

Combine three lenses on the same source — each catches what the
others miss.

**Lens A — Visual inspection of rendered previews via `get_preview`:**

Pull the actual rendered slides into your context as images so you
can see them. PIL pixel statistics (Lens C below) give you frequency
of colors but not *meaning* — they cannot tell you that the orange
bar is a "section divider" or that the rounded box is a "card with
shadow". You have to look.

```
get_preview(deck_id, slugs=["slide-001", "slide-003", "slide-005",
                            "<a section-header slug>",
                            "<a content slug with cards / lists>"],
            quality="high")
```

Pick 4-6 slugs that span the deck's variety: cover, a section
header, a typical content slide, any slide with charts/tables, the
closing slide. `quality="high"` (1280px) is worth the extra tokens
because decoration motifs (shadows, line weights, corner radii) are
hard to see at low quality.

While inspecting each preview, write down:
- **Background** — solid? gradient? bitmap? if solid, the rough hex
  (Lens C will pin it down).
- **Title vs body color** — is the title color the same as body, or
  a separate accent? Is one of the accents used only in the title
  band?
- **Decoration motifs** — accent bars (length / weight / position),
  shadows (soft? hard? colored?), corner radii (sharp? rounded?
  pill?), divider lines (1px? thicker? colored?), card backgrounds
  (filled? bordered? shadowed?), bullet markers (round? square?
  arrow?).
- **Layout grid** — left/right margin, where the title sits, where
  body content starts, vertical rhythm. Cross-check with
  `analyze_template().layouts[]`.
- **Typography hierarchy** — relative size of cover title vs slide
  title vs body, weights, italics, font pair contrast.

These are the qualitative tokens (`--decoration-*`, `--shadow-*`,
`--radius-*`, `--size-*`) that Lens B and C cannot give you.

**Lens B — Theme XML / layouts via `analyze_template`:**

Call the MCP tool on the deck-local template (`template.pptx` was
copied here in Step 2 by `import_attachment`). It returns the full
theme color map (lt1 / dk1 / accent1-6 / hlink / folHlink), font
pairs (latin/eastAsian/complex), and per-layout placeholder
positions.

```
# Cloud (deck-local placeholder template requires deck_id):
analyze_template(template="template.pptx", deck_id=<deck_id>)

# Local (file path is fine; deck_id ignored):
analyze_template(template="template.pptx")
```

This is an MCP tool — do not wrap in `run_python`.

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

**Lens C — Pixel-frequency sampling via PIL on `previews/`:**

Theme XML tells you what colors are *defined*; the rendered slide
previews tell you what's actually *used* and in what proportion.
Step 4's build produced PNG previews under `previews/` — these are
the same images you saw via Lens A. Quantify the dominant hex values
across all of them so the visual impression is grounded in numbers:

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

Cross-reference these swatches with `theme_colors` (Lens B) and
your visual notes (Lens A):
- Frequencies near `theme_colors.lt1 / dk1` confirm the **actual
  background** (which may differ from `themeHints.backgroundLuminance`
  if the deck uses a non-default master).
- Frequencies near `theme_colors.accent1` confirm which accent is
  the deck's hero color (the most-used one is rarely accent1 — pick
  the most-frequent accent that isn't bg/text).
- Outliers (high frequency but no match) are deck-specific brand
  colors not declared in the theme — capture them as their own
  tokens (`--color-brand-orange`, etc.).
- If Lens A noticed a color that PIL ranks low (e.g. only on one
  slide), still encode it — Lens A gives the meaning, Lens C only
  the prevalence.

### 5-3. Author art-direction.html following the create-style workflow

You are now writing a style — follow the **`create-style` workflow**
you loaded in 5-1. The HTML skeleton, `:root` token conventions,
text-class naming (`.t-cover-title` / `.t-body` / ...), demonstration
slide pattern (cover + palette + type ramp + component variants,
total 5-6 slides), absolute-positioning rules, font-size unit, and
violation examples are all defined there. Do not re-invent any of
those conventions in this guide.

This Step contributes only the **import-pptx-specific token
sourcing**: where each token value comes from. Map each token kind
to the lens that produced it in 5-2:

| Token kind                                 | Source                               |
|--------------------------------------------|--------------------------------------|
| `--color-bg`                               | Lens B `theme_colors.lt1` (light deck) or `dk1` (dark deck), confirmed by Lens C frequency. **Do not** use a guessed neutral or the scaffold's bg. |
| `--color-fg` / text                        | Lens B `theme_colors.dk1` (light deck) or `lt1` (dark deck) |
| `--color-accent-N` (1 per accent in use)   | Lens B `theme_colors.accent1..6`. Hero is the most-used accent per Lens C, not necessarily accent1. |
| Brand color outside the theme              | Lens C outliers (high frequency, not in theme_colors). Encode as `--color-brand-<name>`. Lens A confirms semantic role. |
| `--font-heading` / `--font-body`           | Lens B `fonts.latin / eastAsian / complex`, verbatim. No system-font substitution. |
| `--size-cover-title` / `--size-slide-title` / `--size-body` | Lens B `layouts[]` text-frame heights → derive pt sizes; cross-check with Lens A visual hierarchy. |
| `--radius-*` / `--shadow-*` / `--border-*` / decoration motifs | Lens A only. If Lens A did not see it, do not declare it. |
| Margin / grid (where title sits, body x/y) | Lens B `layouts[]` placeholder x/y/width/height. |

After populating tokens, write the demonstration slides. **The
demonstration slides are NOT a re-render of the source deck.** Read
the create-style workflow's "Plan slide composition" section: each
slide demonstrates one design rule with placeholder content like
"Cover Title" / "Section header" / "Body sample paragraph" /
"Component swatches". Do not paste source-deck headlines, bullet
lists, charts, or specific data into the demonstration slides — that
content lives in `slides/` (placed by Step 4), not in the style
specification.

Write incrementally via `run_python(save=True)` — one call for the
skeleton + `:root` + first slide, then one or two more for the
remaining slides (per the create-style workflow's incremental writing
guidance):

```python
# Cloud: prepend purpose="Author art-direction.html — skeleton + tokens"
header = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title><source-PPTX visual system name></title>
<style>
  :root {
    /* ...design tokens populated from the table above... */
  }
  body { margin: 0; padding: 40px; background: #E5E5E5; zoom: 0.7; }
  .slide { position: relative; width: 1920px; height: 1080px; margin: 0 auto 40px; background: var(--color-bg); overflow: hidden; }
  .el { position: absolute; }
  /* .t-cover-title / .t-slide-title / .t-body / ... — each maps to
     CSS variables defined in :root. */
  /* Component classes (.card, .accent-bar, .divider) — only those
     Lens A actually saw in the source. */
</style>
</head>
<body>
"""
cover_slide = """  <div class="slide">
    <!-- Cover demonstration: title + style name. Placeholder text only. -->
  </div>
"""
write_text("specs/art-direction.html", header + cover_slide)
```

Subsequent calls append palette swatches, type ramp, and
component-only demonstration slides — see the create-style workflow
for the standard demonstration-slide set.

Quality bar before considering this Step done:

- `:root` declares every color, font, and size the slides reference.
  No hardcoded hex / pt anywhere outside `:root`.
- Demonstration slides use `.t-*` text classes and `var(--*)`
  references exclusively (verify with a `grep` for `style="font-size`
  or `style="color`).
- Demonstration slide *content* is placeholder copy — not the
  source deck's content.
- `--color-bg` matches what Lens A and Lens C agree the source
  background actually is (dark theme decks have `--color-bg` set
  to dark, not white).
- Total demonstration slides: 5-6 (cover counted).
- **No re-build is needed after writing art-direction.html.** Step 4
  already produced the as-is reproduction the user can review. The
  file you write here is consumed by the composer the next time the
  user asks to edit slides; until then the deck stays at its Step 4
  state.

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
