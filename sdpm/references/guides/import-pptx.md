---
name: import-pptx
description: "Convert an attached PPTX into an editable deck (invoked when read_attachment returns guideInstruction for import-pptx and user intent is edit)"
category: guide
---

# Import PPTX (Edit Existing Presentation)

Invoke this guide when **both** are true:

1. `read_attachment` response contains `guideInstruction` pointing to
   this guide (kind=pptx), AND
2. The user's intent is confirmed to be **editing** the PPTX (not using
   it as reference material for a new deck).

If intent is ambiguous, use the `hearing` tool **once** to confirm before
entering this guide. If the user wants to use the PPTX as reference, stop
here and follow the normal briefing flow (use `read_attachment` to
access content when writing `specs/brief.md`).

## Overview

This guide is the complete workflow for the edit branch. The user already
provided the PPTX itself — that *is* the brief. The PPTX-derived
**placeholder template** is retained inside the immutable import bundle. Step 4
points the active deck at that read-only template, so there is no template
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

The `read_attachment` response header and the attachment marker
`[Attached:{"v":1,"name":"...","source":"..."}]` provide:

- `source` — Step 2 (`import_attachment(source=<source>, ...)`)
- `fileName` — Step 1 (`init_presentation(name=<derived from fileName>)`)
- `slideCount`, `themeHints` — Step 4 validation and style selection

These values stay in your conversation context. If you cannot locate
them, scroll back through the prior tool responses — do not ask the
user to re-upload.

---

## Step 1 — Initialize the deck

Call `init_presentation(name=<suggestedName>)` — **do NOT pass a template
argument**.

- Neither Cloud nor Local `init_presentation` accepts a template parameter.
  The bundle template path, fonts, and `defaultTextColor` are assigned to
  `deck.json` in Step 4; the immutable bundle itself is not modified.
- Returns the new `deck_id` (directory path in Local, deckId in Cloud).

---

## Step 2 — Import converted files

Call `import_attachment(source=<source>, deck_id=<deck_id>)`.

The tool converts the PPTX and commits an immutable bundle into the deck:

- `attachments/imports/{importKey}/deck/template.pptx` — PPTX-derived placeholder template
- `attachments/imports/{importKey}/deck/deck.json` — fonts / defaultTextColor
- `attachments/imports/{importKey}/deck/slides/slide-NN.json` — per-slide JSON
- `attachments/imports/{importKey}/extracted/images/*` — extracted images

The returned JSON includes `importKey`, `bundlePath`, `deckJson`, and
`files[]`. Keep `importKey` — Step 3 and Step 4 need it to locate the
imported per-slide files within the bundle.

---

## Step 3 — Prepare brief and outline

Populate `specs/brief.md` and `specs/outline.md` from the committed bundle before
building. The `bundlePath` returned by Step 2 is deck-relative and identical on
Local and Cloud (for example `attachments/imports/<importKey>`). Bundle files are
read-only: use `read_json` / `read_text` to inspect them, and write only to active
workspace paths such as `specs/` and `slides/`.

First inspect the imported slides:

```python
bundle_path = "<result['bundlePath'] from Step 2>"
slides_path = f"{bundle_path}/deck/slides"
for name in sorted(list_files(slides_path)):
    data = read_json(f"{slides_path}/{name}")
    title = data.get("title") or ""
    if isinstance(title, dict):
        title = title.get("text", "")
    print(name, "::", title)
```

Call via `run_python(purpose="Inspect PPTX slides", code=<above>, deck_id=deck_id)`.
Then write `specs/brief.md` with concise source summaries and bundle-relative evidence
paths. Summarise each imported slide yourself and write `specs/outline.md` with one
non-empty line per slide:

```python
pairs = [
    ("slide-01", "Introduction to the system"),
    ("slide-02", "Storage classes overview"),
]
write_text("specs/outline.md", "\n".join(f"- [{slug}] {message}" for slug, message in pairs) + "\n")
```

Do not call `hearing` in Step 3. If source content is sparse, keep the generated specs
succinct rather than asking the user.

---

## Step 4 — Activate slides + build + preview (single `run_python`)

The import tool itself never writes deck-root template, slides, or images. In one
`run_python` call, select data from the immutable bundle into the active deck:

```python
bundle_path = "<result['bundlePath'] from Step 2>"
slides_path = f"{bundle_path}/deck/slides"
slugs = [name.removesuffix(".json") for name in sorted(list_files(slides_path))]
image_mapping = {<paste result['imageMapping'] from Step 2>}

# Point the active deck at the immutable bundle template; do not copy or modify it.
deck = read_json("deck.json")
imported = read_json(f"{bundle_path}/deck/deck.json")
deck["template"] = f"{bundle_path}/deck/template.pptx"
deck["fonts"] = imported.get("fonts", {})
deck["defaultTextColor"] = imported.get("defaultTextColor")
write_json("deck.json", deck)

def rewrite_image_refs(node):
    if isinstance(node, dict):
        if node.get("type") == "image" and isinstance(node.get("src"), str):
            original = node["src"].split("/", 1)[-1]
            mapped = image_mapping.get(original)
            if mapped:
                node["src"] = f"{bundle_path}/{mapped}"
        effects = node.pop("_originalEffects", None)
        if effects:
            for key, value in effects.items():
                node.setdefault(key, value)
        for value in node.values():
            rewrite_image_refs(value)
    elif isinstance(node, list):
        for value in node:
            rewrite_image_refs(value)

for slug in slugs:
    slide = read_json(f"{slides_path}/{slug}.json")
    rewrite_image_refs(slide)
    write_json(f"slides/{slug}.json", slide)
print("activated:", slugs)
```

Call:

```text
run_python(
    purpose="Activate imported PPTX slides and build",
    code=<above>,
    deck_id=deck_id,
    measure_slides=slugs,
)
```

Keep Step 4 in one call so Cloud writeback, build, preview, and measurement share the
same execution. The active slide JSON may reference bundle images, but code must never
write below `attachments/imports/`. Call `generate_pptx(deck_id=deck_id)` only at final
handoff.

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

`themeHints` from `read_attachment` is a coarse summary (a single
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

Call the MCP tool on the immutable bundle template returned in Step 2. It returns the full
theme color map (lt1 / dk1 / accent1-6 / hlink / folHlink), font
pairs (latin/eastAsian/complex), and per-layout placeholder
positions.

```
# Cloud (deck-owned bundle path requires deck_id):
analyze_template(template=f"{bundlePath}/deck/template.pptx", deck_id=<deck_id>)

# Local (pass the absolute deck path plus bundlePath):
analyze_template(template=f"{deck_id}/{bundlePath}/deck/template.pptx")
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

Write incrementally via `run_python` — one call for the
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
(Cloud: `compose_slides`; Local: dispatch composers per your persona's
Delegation to Composer section).

---

## Notes on lossy conversion

The PPTX→JSON converter has known limitations:

- Connectors are rendered as straight lines.
- Arrow-head styles are not preserved.
- Complex gradients may render differently.
- Some strings are emitted TWICE: once in the slide's `placeholders` dict and
  once as a `textbox` element carrying `_phIdx`. Both point at the same
  placeholder — edit one representation, not both, or the text doubles.

After the first rebuild, render the ORIGINAL pptx (LibreOffice → PNG) and
compare slide by slide — visual regressions are the ground truth; `measure`
warnings alone cannot confirm or rule them out.

Do NOT proactively warn the user about this — the converter is tracked
for improvement separately. Address specific visual regressions only
if the user reports them after previewing the deck.
