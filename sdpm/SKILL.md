---
name: spec-driven-presentation-maker
description: "Generate PowerPoint presentations from JSON. Use when user wants to create slides, proposals, or presentation materials."
---

# PPTX Maker

Generate PowerPoint from JSON using corporate templates. This is the Layer 1 (no-MCP)
environment adapter: it tells you how to run the engine, not what to do — role and
procedure live in `read_workflows`.

All paths in this file are relative to this SKILL.md. `cd` to this directory before
running commands.

## Running the engine

```bash
uv run python3 scripts/pptx_builder.py {contract_name} [args]
```

Subcommand names match the MCP tool names (`generate_pptx`, `read_workflows`,
`read_guides`, `list_styles`, `init_presentation`, `analyze_template`, `search_assets`,
`list_templates`, `code_to_slide`, `diff_pptx`, `arch_diagram`, `grid`), so workflow text
that calls a tool applies verbatim here. `--help` on any subcommand shows its arguments.

CLI-only operations without a contract name:

| Operation | Command |
|---|---|
| Preview slides as PNG | `scripts/pptx_builder.py preview` |
| Measure text bounding boxes | `scripts/pptx_builder.py measure` |
| Import an existing PPTX to JSON | `scripts/pptx_to_json.py` |
| Start a deck translation | `scripts/translate_extract.py <deck> --target-lang <lang>` |
| Apply filled translations | `scripts/translate_apply.py <deck>-<lang>` |

## Files, not tool calls

There is no MCP session here — deck files (`deck.json`, `specs/`, `slides/`) are read
and written directly with normal file I/O. Everything the workflows describe as a tool
call (`read_text`, `write_file`, etc.) is just that: open the path, read or write it.

## Start here

To create slides, run `read_workflows orchestrator` and follow it.

Without a sub-agent mechanism, one agent plays both roles, one slug group at a time.
