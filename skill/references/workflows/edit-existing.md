---
name: edit-existing
description: "Workflow B: Edit existing PPTX"
category: workflow
---

# Workflow B: Edit Existing PPTX

Convert an existing PPTX to JSON and edit it.

---

### 0. Review available guides

Run `guides` to review available guides. Read any that are relevant to the edit.

---

### 1. PPTX → JSON conversion

```bash
# Use the project directory from `init` for all output
uv run python3 scripts/pptx_to_json.py {input_pptx} -o {project_dir}
# → Generates {project_dir}/slides.json + images/
# → From here on, output_json = {project_dir}/slides.json
```

---

### 2. Edit JSON

Edit `slides.json` directly. Roundtrip JSON is valid input for pptx_builder as-is.

- Text changes: edit `text`, `items` (bullet array), or `paragraphs` (paragraph array)
- Add/remove/move elements: edit the `elements` array
- Elements inside groups: edit the `elements` array under `type: "group"` (not `children`)
- Table edits: `headers` is a cell array, `rows` is `[[cell, cell, ...], ...]` (each row is a list)
- Add/remove/reorder slides: edit the `slides` array
- Image references: point `src` to files in `{output_dir}/images/`

**Constraints:**
- You MUST edit slides one at a time — do NOT batch-edit multiple slides simultaneously because it causes context overflow and coordinate errors
- You MUST NOT carry over colors or styles from source slides — always apply the new theme's design guidelines because source styles conflict with the target theme
- For new slides or layout changes, you MUST read:
  - `python scripts/pptx_builder.py workflows slide-json-spec`
  - `python scripts/pptx_builder.py examples components/all`
  - Pattern details (`uv run python3 scripts/pptx_builder.py examples patterns/N`) — only the pages needed
  - Icon search (`icon-search`) — only for the pages needed

---

### 3. Generate + review

```bash
uv run python3 scripts/pptx_builder.py generate {output_json} -o {output_pptx}
uv run python3 scripts/pptx_builder.py measure {output_json}
uv run python3 scripts/pptx_builder.py preview {output_json}
```

Review measure output and preview PNGs, fix and regenerate as needed.

**Constraints:**
- You MUST NOT run generate until all slides are edited/added to the JSON

---

## Translation

For translating an existing PPTX to another language, use the dedicated workflow.
→ **Read `translate-pptx` before executing**
