## Vibe Workflow

Vibe mode converts source material into slides with zero user confirmation.
Execute all steps sequentially without waiting for user input.

### Step 1: Read source material

Read all material the user provided (URLs via `web_fetch`, uploaded files via `read_uploaded_file`, or inline text).
For long documents, paginate to read the full content — do not stop at the first page.

### Step 2: Initialize

Call `init_presentation(name)` to create the working directory.

### Step 3: Write specs/brief.md

Write the brief from the source material in natural prose.
The composer's only source of information is this file — include all data points, numbers, quotes, facts, technical details, and references extracted from the source.

### Step 4: Write specs/outline.md

Derive a logical slide structure from the brief. Each line = 1 slide = 1 message.

```
- [slug] What it changes in the audience and how
```

Rules:
- Aim for 5–15 slides unless the material demands more
- Use shared slug prefixes for slides that build on the same visual base
- Each slide has exactly one message

### Step 5: Art direction

1. Call `list_styles()` to see available styles
2. Choose the style that best fits the brief's purpose, audience, and tone
3. Call `apply_style(deck_id, style)` to set art direction
4. If the user specified a style or tone, honor that instead of inferring
5. Read `specs/art-direction.html` and extract `:root` CSS variables, then update `deck.json`:
   ```json
   {
     "template": "{template}.pptx",
     "fonts": {"fullwidth": "{fullwidth font}", "halfwidth": "{halfwidth font}"},
     "defaultTextColor": "{--color-text value}"
   }
   ```

### Step 6: Compose

Call `compose_slides(deck_id=..., slide_groups=[...])` immediately.
