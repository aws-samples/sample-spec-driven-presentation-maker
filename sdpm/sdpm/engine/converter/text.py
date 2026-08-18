# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Text extraction and processing."""
from .constants import _NS, get_emu_per_px, _serialize_lstStyle
from .color import extract_text_color

def _extract_styled_text(runs, theme_colors=None, color_mapping=None, default_font_size=None, default_text_color=None, is_placeholder=False, paragraph=None, suppress_inherited=False):
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
                formatted = _format_run(run, theme_colors, color_mapping, default_font_size, default_text_color, is_placeholder, suppress_inherited)
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
        parts.append(_format_run(run, theme_colors, color_mapping, default_font_size, default_text_color, is_placeholder, suppress_inherited))
    return ''.join(parts)

def _format_run(run, theme_colors=None, color_mapping=None, default_font_size=None, default_text_color=None, is_placeholder=False, suppress_inherited=False):
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
        # When the shape's p:style fontRef supplies the text color (emitted
        # as elem fontColor), runs without their own solidFill must NOT get
        # the inherited tx1 fallback baked in — it would override fontRef.
        has_own_color = run.font.color is not None and run.font.color.type is not None
        if not (suppress_inherited and not has_own_color):
            hex_color = extract_text_color(run, theme_colors, color_mapping, is_placeholder=is_placeholder)
            if hex_color and hex_color != default_text_color:
                styles.append(hex_color)
    except Exception:
        pass
    # Sub/superscript (a:rPr baseline) — renderers auto-shrink offset runs,
    # so dropping it makes e.g. an 80pt decorative "01" render full-size.
    try:
        rPr_bl = run._r.find(f'{{{_NS["a"]}}}rPr')
        if rPr_bl is not None and rPr_bl.get('baseline'):
            bl = int(rPr_bl.get('baseline'))
            if bl != 0:
                styles.append(f"baseline={bl}")
        # Text highlight (marker color) — a:highlight
        if rPr_bl is not None:
            hl = rPr_bl.find(f'{{{_NS["a"]}}}highlight')
            if hl is not None:
                srgb_hl = hl.find(f'{{{_NS["a"]}}}srgbClr')
                if srgb_hl is not None and srgb_hl.get('val'):
                    styles.append(f"highlight=#{srgb_hl.get('val')}")
                else:
                    scheme_hl = hl.find(f'{{{_NS["a"]}}}schemeClr')
                    if scheme_hl is not None:
                        from .color import _resolve_color_with_transforms
                        resolved_hl = _resolve_color_with_transforms(scheme_hl, theme_colors, color_mapping)
                        if resolved_hl:
                            styles.append(f"highlight={resolved_hl}")
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


def _inherited_default_size(shape):
    """Effective size for runs with no explicit sz anywhere in the shape.

    Non-placeholder shape text inherits from presentation.xml
    defaultTextStyle; absent that, the OOXML spec default for defRPr sz
    is 1800 (18pt). The builder's shape default is 14pt, so the inherited
    size must be made explicit or rebuilt text shrinks.
    """
    try:
        pres = shape.part.package.presentation_part._element
        dts = pres.find(f'{{{_NS["p"]}}}defaultTextStyle')
        if dts is not None:
            l1 = dts.find(f'{{{_NS["a"]}}}lvl1pPr')
            d = l1.find(f'{{{_NS["a"]}}}defRPr') if l1 is not None else None
            if d is not None and d.get('sz'):
                sz = int(d.get('sz')) / 100
                return int(sz) if sz == int(sz) else sz
    except Exception:
        pass
    return 18


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
    emu_per_px = get_emu_per_px()
    tf = shape.text_frame
    if tf.margin_left is not None and tf.margin_left != 91440:
        elem["marginLeft"] = round(tf.margin_left / emu_per_px)
    if tf.margin_top is not None and tf.margin_top != 45720:
        elem["marginTop"] = round(tf.margin_top / emu_per_px)
    if tf.margin_right is not None and tf.margin_right != 91440:
        elem["marginRight"] = round(tf.margin_right / emu_per_px)
    if tf.margin_bottom is not None and tf.margin_bottom != 45720:
        elem["marginBottom"] = round(tf.margin_bottom / emu_per_px)
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

    # Line spacing (a:lnSpc) — fixed-point spacing repositions text visibly
    # (e.g. a 48pt title with 31.2pt spacing sits much higher than default).
    if tf.paragraphs:
        first_pPr = tf.paragraphs[0]._element.find(f'{{{_NS["a"]}}}pPr')
        if first_pPr is not None:
            lnSpc = first_pPr.find(f'{{{_NS["a"]}}}lnSpc')
            if lnSpc is not None:
                spcPts = lnSpc.find(f'{{{_NS["a"]}}}spcPts')
                spcPct = lnSpc.find(f'{{{_NS["a"]}}}spcPct')
                if spcPts is not None and spcPts.get('val'):
                    elem["lineSpacingPt"] = int(spcPts.get('val')) / 100
                elif spcPct is not None and spcPct.get('val'):
                    val = int(spcPct.get('val'))
                    if val != 100000:
                        elem["lineSpacingPct"] = val

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

    # p:style/a:fontRef: shapes styled via theme (e.g. white text on an
    # accent-filled bar) inherit their text color from the style, not from
    # run properties. Resolve it so the builder doesn't paint them with the
    # deck default.
    # OOXML precedence: the fontRef color is the LAST resort — an explicit
    # color in the shape's own txBody lstStyle (defRPr solidFill) beats it.
    # Adopting fontRef in that case bakes e.g. white onto a light-fill card
    # whose lstStyle actually renders dark text (white-on-white bug).
    font_ref = shape._element.find(f'{{{_NS["p"]}}}style/{{{_NS["a"]}}}fontRef')
    if font_ref is not None and theme_colors:
        lst_style_color = shape._element.find(
            f'{{{_NS["p"]}}}txBody/{{{_NS["a"]}}}lstStyle//{{{_NS["a"]}}}defRPr/{{{_NS["a"]}}}solidFill'
        )
        scheme_el = font_ref.find(f'{{{_NS["a"]}}}schemeClr')
        if scheme_el is not None and lst_style_color is None:
            from .color import _resolve_color_with_transforms
            ref_color = _resolve_color_with_transforms(scheme_el, theme_colors, color_mapping)
            if ref_color and ref_color.lower() != (default_text_color or '').lower():
                elem["fontColor"] = ref_color
                default_text_color = ref_color
    _suppress_inherited = "fontColor" in elem

    paragraphs_with_text = [p for p in tf.paragraphs if p.text.strip()]
    all_paragraphs = list(tf.paragraphs)
    # Skip default_font_size if shape has lstStyle (sizes handled by lstStyle)
    has_lstStyle = _serialize_lstStyle(shape) is not None
    default_font_size = None if has_lstStyle else _detect_font_size(paragraphs_with_text)
    if (default_font_size is None and not has_lstStyle and paragraphs_with_text
            and any(r.font.size is None for para in paragraphs_with_text for r in para.runs)):
        # Runs without explicit sz inherit the presentation default (spec
        # fallback 18pt) — make it explicit or the builder default applies.
        default_font_size = _inherited_default_size(shape)

    if _has_bullets(paragraphs_with_text):
        # Check if all text paragraphs have bullets — if mixed, use text mode
        ns_a = _NS["a"]
        non_bullet = [p for p in paragraphs_with_text if not (p._element.pPr is not None and (p._element.pPr.find(f'{{{ns_a}}}buChar') is not None or p._element.pPr.find(f'{{{ns_a}}}buAutoNum') is not None))]
        if len(non_bullet) == 0:
            items = []
            for para in paragraphs_with_text:
                t = _extract_styled_text(para.runs, theme_colors, color_mapping, default_font_size=default_font_size, default_text_color=default_text_color, paragraph=para, suppress_inherited=_suppress_inherited)
                if t.strip():
                    items.append(t)
            if items:
                elem["items"] = items
        else:
            # Mixed bullets and non-bullets — use paragraphs array
            paras = []
            for para in all_paragraphs:
                p = {}
                t = _extract_styled_text(para.runs, theme_colors, color_mapping, default_font_size=default_font_size, default_text_color=default_text_color, paragraph=para, suppress_inherited=_suppress_inherited)
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
        # Empty paragraphs with an explicit endParaRPr size act as sized
        # spacers (they shift anchored text); the joined-text form cannot
        # carry per-line sizes, so switch to paragraphs mode when present.
        ns_a = _NS["a"]

        def _end_sz(para):
            endPr = para._element.find(f'{{{ns_a}}}endParaRPr')
            if endPr is not None and endPr.get('sz'):
                return int(endPr.get('sz')) / 100
            return None

        sized_empties = [para for para in all_paragraphs
                         if not para.text.strip() and _end_sz(para)
                         and _end_sz(para) != default_font_size]
        if sized_empties:
            paras = []
            for para in all_paragraphs:
                p = {"text": _extract_styled_text(para.runs, theme_colors, color_mapping, default_font_size=default_font_size, default_text_color=default_text_color, paragraph=para, suppress_inherited=_suppress_inherited)}
                a = _get_alignment(para)
                if a:
                    p["align"] = a
                if para.runs and para.runs[0].font.size:
                    p["fontSize"] = int(para.runs[0].font.size.pt)
                esz = _end_sz(para)
                if esz:
                    p["endFontSize"] = esz
                paras.append(p)
            elem["paragraphs"] = paras
        else:
            parts = []
            for i, para in enumerate(all_paragraphs):
                if i > 0:
                    parts.append('\n')
                parts.append(_extract_styled_text(para.runs, theme_colors, color_mapping, default_font_size=default_font_size, default_text_color=default_text_color, paragraph=para, suppress_inherited=_suppress_inherited))
            elem["text"] = ''.join(parts)
            # endParaRPr pins the paragraph line height (e.g. a full-size
            # 80pt endParaRPr next to a baseline-shrunk run keeps the line
            # tall; dropping it shifts the text up). Roundtrip it when it
            # differs from the last run's size or the runs are baseline-offset.
            if all_paragraphs:
                last_p = all_paragraphs[-1]
                endPr = last_p._element.find(f'{{{_NS["a"]}}}endParaRPr')
                if endPr is not None and endPr.get('sz'):
                    end_sz = int(endPr.get('sz')) / 100
                    last_runs = last_p.runs
                    last_run_sz = (last_runs[-1].font.size.pt
                                   if last_runs and last_runs[-1].font.size else None)
                    has_baseline = any(
                        (r._r.find(f'{{{_NS["a"]}}}rPr') is not None
                         and r._r.find(f'{{{_NS["a"]}}}rPr').get('baseline'))
                        for r in last_runs)
                    if has_baseline or (last_run_sz is not None and end_sz != last_run_sz):
                        elem["_endParaSize"] = end_sz
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
