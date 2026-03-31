# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Table extraction."""
import sys
import zipfile

from .constants import _NS, EMU_PER_PX, _base_element, _hex
from .color import _resolve_scheme_color, _apply_tint, _apply_shade, extract_text_color
from .xml_helpers import _extract_fill_from_xml
from .text import _extract_styled_text

def _extract_cell(cell, theme_colors=None, color_mapping=None):
    """Extract cell as string (text only) or dict (has extra properties)."""
    tc = cell._tc
    tc_pr = tc.find('a:tcPr', _NS)
    # Use styled text extraction to preserve hyperlinks
    tf = cell.text_frame
    styled_parts = []
    for para in tf.paragraphs:
        styled_parts.append(_extract_styled_text(para.runs, theme_colors, color_mapping, paragraph=para))
    text = "\n".join(styled_parts)
    props = {}

    if tc_pr is not None:
        # Fill
        solid = tc_pr.find('a:solidFill', _NS)
        grad = tc_pr.find('a:gradFill', _NS)
        no_fill = tc_pr.find('a:noFill', _NS)
        if solid is not None:
            srgb = solid.find('a:srgbClr', _NS)
            scheme = solid.find('a:schemeClr', _NS)
            if srgb is not None:
                props["fill"] = _hex(srgb)
            elif scheme is not None:
                resolved = _resolve_scheme_color(scheme.get('val'), theme_colors, color_mapping)
                if resolved:
                    props["fill"] = resolved
        elif grad is not None:
            grad_info = _extract_fill_from_xml(tc_pr, theme_colors, color_mapping)
            if "gradient" in grad_info:
                props["gradient"] = grad_info["gradient"]
        elif no_fill is not None:
            props["fill"] = "none"

        # Borders
        borders = {}
        for side, tag in [("left", "lnL"), ("right", "lnR"), ("top", "lnT"), ("bottom", "lnB")]:
            ln = tc_pr.find(f'a:{tag}', _NS)
            if ln is None:
                continue
            border = {}
            w = ln.get('w')
            if w:
                border["width"] = round(int(w) / 12700, 1)  # EMU to pt
            if ln.find('a:noFill', _NS) is not None:
                border["fill"] = "none"
            else:
                sf = ln.find('a:solidFill', _NS)
                if sf is not None:
                    srgb = sf.find('a:srgbClr', _NS)
                    scheme = sf.find('a:schemeClr', _NS)
                    if srgb is not None:
                        border["color"] = _hex(srgb)
                    elif scheme is not None:
                        resolved = _resolve_scheme_color(scheme.get('val'), theme_colors, color_mapping)
                        if resolved:
                            border["color"] = resolved
            if border:
                borders[side] = border
        if borders:
            props["borders"] = borders

        # Vertical alignment
        anchor = tc_pr.get('anchor')
        if anchor:
            _va_reverse = {"t": "top", "ctr": "middle", "b": "bottom"}
            va = _va_reverse.get(anchor)
            if va:
                props["verticalAlign"] = va

        # Margins
        margins = {}
        for attr, key in [('marL', 'left'), ('marR', 'right'), ('marT', 'top'), ('marB', 'bottom')]:
            v = tc_pr.get(attr)
            if v:
                margins[key] = round(int(v) / EMU_PER_PX)
        if margins:
            props["margins"] = margins

    # Merge
    grid_span = tc.get('gridSpan')
    row_span = tc.get('rowSpan')
    if grid_span and int(grid_span) > 1:
        props["gridSpan"] = int(grid_span)
    if row_span and int(row_span) > 1:
        props["rowSpan"] = int(row_span)

    # Skip merged-away cells
    if tc.get('hMerge') == '1' or tc.get('vMerge') == '1':
        props["merged"] = True

    # Text styles (from first run)
    tf = cell.text_frame
    if tf.paragraphs:
        para = tf.paragraphs[0]
        if para.alignment is not None:
            align_map = {1: "left", 2: "center", 3: "right"}
            a = align_map.get(int(para.alignment))
            if a:
                props["align"] = a
        for run in para.runs:
            if run.font.bold:
                props["bold"] = True
            if run.font.italic:
                props["italic"] = True
            if run.font.underline:
                props["underline"] = True
            if run.font.size:
                props["fontSize"] = int(run.font.size.pt)
            try:
                fc = extract_text_color(run, theme_colors, color_mapping)
                if fc and run.font.color and run.font.color.type is not None:
                    props["fontColor"] = fc
                elif run.font.color and run.font.color.type is not None and not fc:
                    # Preserve explicit scheme colors (e.g. tx1=white) in table cells
                    rPr = run._r.find('{http://schemas.openxmlformats.org/drawingml/2006/main}rPr')
                    if rPr is not None:
                        scheme = rPr.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}schemeClr')
                        if scheme is not None:
                            resolved = _resolve_scheme_color(scheme.get('val'), theme_colors, color_mapping)
                            if resolved:
                                props["fontColor"] = resolved
            except Exception:
                pass
            break  # first run only

    if props:
        props["text"] = text
        return props
    return text

def _parse_table_style(pptx_path, style_id, theme_colors, color_mapping):
    """Parse tableStyles.xml and resolve fills/borders for a given style."""
    try:
        with zipfile.ZipFile(str(pptx_path)) as z:
            xml = z.read('ppt/tableStyles.xml')
        from lxml import etree
        root = etree.fromstring(xml)
        # Find style by ID, or use default
        target_id = style_id or root.get('def')
        style_el = None
        for s in root.findall('a:tblStyle', _NS):
            if s.get('styleId') == target_id:
                style_el = s
                break
        if style_el is None:
            return {}

        def resolve_fill(tc_style):
            """Extract fill color from tcStyle element."""
            fill_el = tc_style.find('a:fill/a:solidFill', _NS)
            if fill_el is None:
                return None
            srgb = fill_el.find('a:srgbClr', _NS)
            if srgb is not None:
                return _hex(srgb)
            scheme = fill_el.find('a:schemeClr', _NS)
            if scheme is not None:
                base = _resolve_scheme_color(scheme.get('val'), theme_colors, color_mapping)
                if base:
                    tint = scheme.find('a:tint', _NS)
                    shade = scheme.find('a:shade', _NS)
                    if tint is not None:
                        return _apply_tint(base, int(tint.get('val')) / 100000)
                    if shade is not None:
                        return _apply_shade(base, int(shade.get('val')) / 100000)
                    return base
            return None

        def resolve_border_color(tc_bdr):
            """Extract border color from tcBdr."""
            if tc_bdr is None:
                return None
            # Check any border line for color
            for tag in ['a:left', 'a:right', 'a:top', 'a:bottom', 'a:insideH', 'a:insideV']:
                ln = tc_bdr.find(f'{tag}/a:ln/a:solidFill', _NS)
                if ln is not None:
                    scheme = ln.find('a:schemeClr', _NS)
                    if scheme is not None:
                        return _resolve_scheme_color(scheme.get('val'), theme_colors, color_mapping)
                    srgb = ln.find('a:srgbClr', _NS)
                    if srgb is not None:
                        return _hex(srgb)
            return None

        def resolve_text_color(tc_txt):
            """Extract text color from tcTxStyle."""
            if tc_txt is None:
                return None
            scheme = tc_txt.find('a:schemeClr', _NS)
            if scheme is not None:
                return _resolve_scheme_color(scheme.get('val'), theme_colors, color_mapping)
            return None

        result = {}
        for part_name in ['wholeTbl', 'firstRow', 'lastRow', 'firstCol', 'lastCol', 'band1H', 'band2H']:
            part = style_el.find(f'a:{part_name}', _NS)
            if part is None:
                continue
            info = {}
            tc_style = part.find('a:tcStyle', _NS)
            if tc_style is not None:
                f = resolve_fill(tc_style)
                if f:
                    info['fill'] = f
                bc = resolve_border_color(tc_style.find('a:tcBdr', _NS))
                if bc:
                    info['borderColor'] = bc
            tc_txt = part.find('a:tcTxStyle', _NS)
            if tc_txt is not None:
                tc = resolve_text_color(tc_txt)
                if tc:
                    info['fontColor'] = tc
                if tc_txt.get('b') == 'on':
                    info['bold'] = True
            if info:
                result[part_name] = info
        return result
    except Exception:
        return {}

def _apply_style_to_cell(cell_val, style_info):
    """Apply table style info to a cell that lacks explicit properties."""
    if not style_info:
        return cell_val
    # Skip for roundtrip cells (borders present = extracted from XML, style will be inherited)
    if isinstance(cell_val, dict) and "borders" in cell_val:
        return cell_val
    is_str = isinstance(cell_val, str)
    if is_str:
        needs_upgrade = any(k in style_info for k in ('fill', 'bold'))
        if not needs_upgrade:
            return cell_val
        cell_val = {"text": cell_val}
    # Only apply if cell doesn't already have the property
    for key in ('fill', 'bold'):
        if key in style_info and key not in cell_val:
            cell_val[key] = style_info[key]
    return cell_val

def extract_table_element(shape, theme_colors=None, color_mapping=None, pptx_path=None):
    """Extract table as element dict."""
    try:
        table = shape.table
        tbl_elem = table._tbl

        elem = _base_element(shape, "table")

        # Column widths
        elem["colWidths"] = [round(col.width / EMU_PER_PX) for col in table.columns]

        # Row heights
        elem["rowHeights"] = [round(row.height / EMU_PER_PX) for row in table.rows]

        # Table style properties
        tbl_pr = tbl_elem.find('a:tblPr', _NS)
        if tbl_pr is not None:
            for attr in ['firstRow', 'lastRow', 'firstCol', 'lastCol', 'bandRow', 'bandCol']:
                if tbl_pr.get(attr) == '1':
                    elem[attr] = True
            style_id = tbl_pr.find('a:tableStyleId', _NS)
            if style_id is not None and style_id.text:
                elem["tableStyleId"] = style_id.text

        # Headers (first row)
        elem["headers"] = [_extract_cell(c, theme_colors, color_mapping) for c in table.rows[0].cells]

        # Data rows
        elem["rows"] = [
            [_extract_cell(c, theme_colors, color_mapping) for c in row.cells]
            for row in list(table.rows)[1:]
        ]

        # Apply table style fills/colors to cells without explicit values
        if pptx_path:
            style_id = elem.get("tableStyleId")
            ts = _parse_table_style(pptx_path, style_id, theme_colors, color_mapping)
            if ts:
                whole = ts.get('wholeTbl', {})
                first_row = {**whole, **ts.get('firstRow', {})} if elem.get('firstRow') else whole
                band1 = {**whole, **ts.get('band1H', {})} if elem.get('bandRow') else whole
                band2 = whole

                # Apply to headers
                elem["headers"] = [_apply_style_to_cell(c, first_row) for c in elem["headers"]]

                # Apply to data rows
                for ri, row in enumerate(elem["rows"]):
                    style = band1 if ri % 2 == 0 else band2
                    elem["rows"][ri] = [_apply_style_to_cell(c, style) for c in row]

        return elem
    except Exception as e:
        print(f"Warning: Failed to extract table: {e}", file=sys.stderr)
        return None
