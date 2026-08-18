## run_style_python — sandbox I/O (this environment)

In this environment, `run_style_python` does NOT inject `read_style` /
`write_style` helpers. Use normal file I/O with these parameters instead:

Workspace layout:
- `style.html` — the target style file (read/write; persisted automatically when changed)
- `ref/{name}.html` — reference styles (read-only; loaded via the `ref_styles` parameter)

Usage patterns:
- Read a reference: `run_style_python(code="html = open('ref/corporate-executive.html').read(); print(html[:500])", ref_styles=["corporate-executive"])`
- Create/edit the style: `run_style_python(code="open('style.html','w').write(html)", style_name="style-20260506-1430")`
- Read back for incremental edits: `run_style_python(code="print(open('style.html').read())", style_name="style-20260506-1430")`

The user's first message contains `[Style: <name>]` — pass it as the
`style_name` parameter on every call (not as a `write_style` argument).
Writes to style.html persist automatically — there is no save flag.
