## Inputs (this environment)

`start_style` was not called here — its `styles` and `base` are not in your context.
Use `list_styles()` for the catalogue and read a bundled style's HTML through
`run_style_python` with `ref_styles` (below) to get the skeleton to imitate.

## run_style_python — sandbox I/O (this environment)

In this environment, `run_style_python` does NOT inject `read_style` /
`write_style` helpers. Use normal file I/O with these parameters instead:

Workspace layout:
- `style.html` — the target style file (read/write; persisted automatically when changed)
- `ref/{name}.html` — reference styles (read-only; loaded via the `ref_styles` parameter)

Usage patterns:
- Read a reference: `run_style_python(code="html = open('ref/report.html').read(); print(html[:500])", ref_styles=["report"])`
- First save (title, `:root`, cover): `run_style_python(code="open('style.html','w').write(html)", style_name="<name>")`
- Add the next slide: `run_style_python(code="p='style.html'; h=open(p).read(); i=h.rindex('</body>'); open(p,'w').write(h[:i]+slide+h[i:])", style_name="<name>")`
  — `slide` holds that one `.slide` plus the CSS and comments it introduces; put new CSS into the
  existing `<style>` the same way.
- Change a slide: read `style.html`, replace that slide's part of the string, write it back.
- Read back: `run_style_python(code="print(open('style.html').read())", style_name="<name>")`

`<name>` is the style's name: the one in `[Style: <name>]` when the user's first
message carries it, otherwise the name you chose for a new style. Pass it as the
`style_name` parameter on every call (not as a `write_style` argument).
Writes to style.html persist automatically — there is no save flag.
