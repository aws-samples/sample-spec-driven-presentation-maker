# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Text extraction and processing."""
from .constants import _NS, EMU_PER_PX, _serialize_lstStyle
from .color import extract_text_color

def _extract_styled_text(runs, theme_colors=None, color_mapping=None, default_font_size=None, default_text_color=None, is_placeholder=False, paragraph=None):
    """Convert a list of runs to styled text string. If paragraph is provided, handles <a:br> (soft line breaks)."""
    parts = []
    # If paragraph element is available, iterate children to capture <a:br> elements
    if paragraph is not None:
        run_idx = 0
        pending_br = False
        for child in paragraph._element:
            tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag == 'br':
                pending_br = True
            elif tag == 'r' and run_idx < len(runs):
                run = runs[run_idx]
                run_idx += 1
                formatted = _format_run(run, theme_colors, color_mapping, default_font_size, default_text_color, is_placeholder)
                if pending_br:
                    # Insert \u000b before the run (outside link tags)
                    if formatted.startswith('{{') and 'link:' in formatted:
                        formatted = '\u000b' + formatted
                    elif formatted.startswith('{{') and ':' in formatted:
                        # {{styles:text}} → {{styles:\u000btext}}
                        colon = formatted.index(':')
                        formatted = formatted[:colon+1] + '\u000b' + formatted[colon+1:]
                    else:
                        formatted = '\u000b' + formatted
                    pending_br = False
                parts.append(formatted)
        if pending_br:
            parts.append('\u000b')
        return ''.join(parts)
    # Fallback: runs only
    for run in runs:
        parts.append(_format_run(run, theme_colors, color_mapping, default_font_size, default_text_color, is_placeholder))
    return ''.join(parts)

def _format_run(run, theme_colors=None, color_mapping=None, default_font_size=None, default_text_color=None, is_placeholder=False):
    """Format a single run with styled text markup."""
    if not run.text:
        return ''
    if run.hyperlink and run.hyperlink.address:
        prefix = ''
        if run.font.size:
            pt = int(run.font.size.pt)
            if default_font_size is None or pt != default_font_size:
                prefix = f'{pt}pt,'
        return f"{{{{{prefix}link:{run.hyperlink.address}:{run.text}}}}}"
    styles = []
    if run.font.bold:
        styles.append("bold")
    if run.font.italic:
        styles.append("italic")
    if run.font.underline:
        styles.append("underline")
    if run.font.size:
        pt = int(run.font.size.pt)
        if default_font_size is None or pt != default_font_size:
            styles.append(f"{pt}pt")
    try:
        hex_color = extract_text_color(run, theme_colors, color_mapping, is_placeholder=is_placeholder)
        if hex_color and hex_color != default_text_color:
            styles.append(hex_color)
    except Exception:
        pass
    if run.font.name:
        # Check for sym font (Wingdings etc) for PUA characters
        font_name = run.font.name
        try:
            rPr = run._r.find('{http://schemas.openxmlformats.org/drawingml/2006/main}rPr')
            if rPr is not None:
                sym = rPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}sym')
                if sym is not None and sym.get('typeface'):
                    # Only use sym font for PUA characters (Wingdings etc)
                    if any(0xE000 <= ord(c) <= 0xF8FF for c in run.text):
                        font_name = sym.get('typeface')
        except Exception:
            pass
        styles.append(f"font={font_name}")
    if styles:
        escaped = run.text.replace('}', '\\}')
        return f"{{{{{','.join(styles)}:{escaped}}}}}"
    return run.text

def _detect_font_size(paragraphs):
    """Detect default font size from most common explicit size across runs."""
    sizes = {}
    none_count = 0
    for para in paragraphs:
        for run in para.runs:
            if run.font.size:
                pt = int(run.font.size.pt)
                sizes[pt] = sizes.get(pt, 0) + 1
            else:
                none_count += 1
    if not sizes:
        return None
    # If any runs have no explicit size, sizes are mixed — don't set a default
    if none_count > 0:
        return None
    most_common = max(sizes, key=sizes.get)
    return most_common


_ALIGN_MAP = {1: "left", 2: "center", 3: "right", 4: "justify"}

def _get_alignment(paragraph):
    """Get alignment string from paragraph, or None."""
    if paragraph.alignment is not None:
        return _ALIGN_MAP.get(int(paragraph.alignment))
    return None

def _has_bullets(paragraphs):
    """Check if any paragraph has bullet or numbering markers."""
    for para in paragraphs:
        try:
            pPr = para._element.pPr
            if pPr is not None:
                if pPr.find('.//a:buChar', _NS) is not None or pPr.find('.//a:buAutoNum', _NS) is not None:
                    return True
        except Exception:
            pass
    return False

def _extract_shape_text(shape, elem, theme_colors, color_mapping=None, builder_text_color=None):
    """Extract text content from shape into elem dict (items/text, fontSize, align, margins)."""
    tf = shape.text_frame
    if tf.margin_left is not None and tf.margin_left != 91440:
        elem["marginLeft"] = round(tf.margin_left / EMU_PER_PX)
    if tf.margin_top is not None and tf.margin_top != 45720:
        elem["marginTop"] = round(tf.margin_top / EMU_PER_PX)
    if tf.margin_right is not None and tf.margin_right != 91440:
        elem["marginRight"] = round(tf.margin_right / EMU_PER_PX)
    if tf.margin_bottom is not None and tf.margin_bottom != 45720:
        elem["marginBottom"] = round(tf.margin_bottom / EMU_PER_PX)
    if tf.vertical_anchor is not None:
        _va_reverse = {1: "top", 3: "middle", 4: "bottom"}
        va = _va_reverse.get(int(tf.vertical_anchor))
        if va:
            elem["verticalAlign"] = va
    body_pr = shape._element.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}bodyPr')
    if body_pr is not None:
        vert = body_pr.get('vert')
        if vert:
            elem["textDirection"] = vert
        if body_pr.get('wrap') == 'none':
            elem["autoWidth"] = True

    default_text_color = builder_text_color
    if not default_text_color and color_mapping and theme_colors:
        tx1 = color_mapping.get('tx1', 'dk1')
        if tx1 in theme_colors:
            default_text_color = theme_colors[tx1]
        # Also consider the mapped text color (what builder uses)
        # If clrMap maps tx1→lt1, the actual text color is lt1's value
        # We need to keep colors that differ from the builder's default
        bg1_ref = color_mapping.get('bg1', 'lt1')
        _builder_text_color = theme_colors.get(tx1)
        # If bg1 maps to dk1, this is a dark theme: builder text = lt1 value
        if bg1_ref == 'dk1':
            _builder_text_color = theme_colors.get('lt1')
        elif bg1_ref == 'lt1':
            _builder_text_color = theme_colors.get('dk1')
        # Use builder's text color as default so explicit colors are preserved
        if _builder_text_color:
            default_text_color = _builder_text_color

    paragraphs_with_text = [p for p in tf.paragraphs if p.text.strip()]
    all_paragraphs = list(tf.paragraphs)
    # Skip default_font_size if shape has lstStyle (sizes handled by lstStyle)
    has_lstStyle = _serialize_lstStyle(shape) is not None
    default_font_size = None if has_lstStyle else _detect_font_size(paragraphs_with_text)

    if _has_bullets(paragraphs_with_text):
        # Check if all text paragraphs have bullets — if mixed, use text mode
        ns_a = _NS["a"]
        non_bullet = [p for p in paragraphs_with_text if not (p._element.pPr is not None and (p._element.pPr.find(f'{{{ns_a}}}buChar') is not None or p._element.pPr.find(f'{{{ns_a}}}buAutoNum') is not None))]
        if len(non_bullet) == 0:
            items = []
            for para in paragraphs_with_text:
                t = _extract_styled_text(para.runs, theme_colors, color_mapping, default_font_size=default_font_size, default_text_color=default_text_color, paragraph=para)
                if t.strip():
                    items.append(t)
            if items:
                elem["items"] = items
        else:
            # Mixed bullets and non-bullets — use paragraphs array
            paras = []
            for para in all_paragraphs:
                p = {}
                t = _extract_styled_text(para.runs, theme_colors, color_mapping, default_font_size=default_font_size, default_text_color=default_text_color, paragraph=para)
                p["text"] = t
                pPr = para._element.find(f'{{{ns_a}}}pPr')
                if pPr is not None:
                    a = pPr.get('algn')
                    if a:
                        p["align"] = a
                    if pPr.find(f'{{{ns_a}}}buChar') is not None:
                        bc = pPr.find(f'{{{ns_a}}}buChar')
                        p["bullet"] = bc.get('char', '•') if bc is not None else True
                # Per-paragraph fontSize from first run (always record if explicit)
                if para.runs and para.runs[0].font.size:
                    p["fontSize"] = int(para.runs[0].font.size.pt)
                # endParaRPr fontSize (for empty paragraphs or line height)
                endPr = para._element.find(f'{{{ns_a}}}endParaRPr')
                if endPr is not None and endPr.get('sz'):
                    esz = int(endPr.get('sz'))
                    p["endFontSize"] = esz / 100  # hundredths of pt → pt
                paras.append(p)
            elem["paragraphs"] = paras
    else:
        parts = []
        for i, para in enumerate(all_paragraphs):
            if i > 0:
                parts.append('\n')
            parts.append(_extract_styled_text(para.runs, theme_colors, color_mapping, default_font_size=default_font_size, default_text_color=default_text_color, paragraph=para))
        elem["text"] = ''.join(parts)
        # Extract indent/marL from first paragraph for single-text shapes
        if paragraphs_with_text:
            pPr = paragraphs_with_text[0]._element.find(f'{{{_NS["a"]}}}pPr')
            if pPr is not None:
                _indent = pPr.get('indent')
                if _indent is not None:
                    elem["indent"] = int(_indent)
                _marL = pPr.get('marL')
                if _marL is not None:
                    elem["marL"] = int(_marL)

    if default_font_size:
        elem["fontSize"] = default_font_size
    elem["align"] = _get_alignment(tf.paragraphs[0]) if tf.paragraphs else "left"
    if not elem.get("align"):
        elem["align"] = "left"
    # Extract character spacing
    spc_vals = set()
    for p in tf.paragraphs:
        for r in p.runs:
            rPr = r._r.find('{http://schemas.openxmlformats.org/drawingml/2006/main}rPr')
            s = rPr.get('spc') if rPr is not None else None
            if s:
                spc_vals.add(int(s))
    if len(spc_vals) == 1:
        elem["_spc"] = spc_vals.pop()
    # Extract autofit from bodyPr
    try:
        bodyPr = tf._txBody.find('{http://schemas.openxmlformats.org/drawingml/2006/main}bodyPr')
        if bodyPr is not None:
            if bodyPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}spAutoFit') is not None:
                elem["_spAutoFit"] = True
            elif bodyPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}noAutofit') is not None:
                elem["_noAutofit"] = True
    except Exception:
        pass

    # Detect cap=none and bold=off overrides (when lstStyle has cap=all / b=1)
    try:
        runs = [r for p in tf.paragraphs for r in p.runs]
        if runs:
            if all(r._r.find('{http://schemas.openxmlformats.org/drawingml/2006/main}rPr') is not None and
                   r._r.find('{http://schemas.openxmlformats.org/drawingml/2006/main}rPr').get('cap') == 'none'
                   for r in runs):
                elem["_capNone"] = True
            if all(r._r.find('{http://schemas.openxmlformats.org/drawingml/2006/main}rPr') is not None and
                   r._r.find('{http://schemas.openxmlformats.org/drawingml/2006/main}rPr').get('b') == '0'
                   for r in runs):
                elem["_boldOff"] = True
    except Exception:
        pass
