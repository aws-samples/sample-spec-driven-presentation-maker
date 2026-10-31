# GUI-only capture evidence

Each subdirectory is one captured value from the PowerPoint GUI, named by its
catalog key. The procedure and the evidence requirements live in
`scripts/animation_catalog/computer-use.md`.

These captures are development-time evidence. sdpm's runtime, CLI, MCP servers,
tests and CI never invoke PowerPoint, AppleScript or Computer Use.

## Captures

| Key | Application | Date | Control path | Evidence |
| --- | --- | --- | --- | --- |
| `transition.gallery.box.fromRight` | PowerPoint for Mac 16.113.1 | 2026-10-31 | Transitions ▸ Transition Styles ▸ Box ▸ Effect Options ▸ From Right | `.pptx`, `.xml`, `powerpoint-readback.jsonl` |

## Known incompleteness of the pilot capture

`computer-use.md` requires four artefacts per value. The pilot carries three:

1. the saved `.pptx` — present;
2. the extracted XML fragment — present;
3. the ribbon read-back at the time of application — present, in
   `powerpoint-readback.jsonl` (`durationShown: "01.60"`, `[No Sound]`,
   advance on mouse click, thumbnail `Has Transition`);
4. **the screenshot is missing**, and the value was **not re-read after closing
   and reopening the file**.

So this capture establishes what PowerPoint *wrote*, not yet that PowerPoint
*reads the same value back from a reopened file*. Treat it as evidence of the
OOXML form and of the capture loop working, not as a completed Step 1 entry.
