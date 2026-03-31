# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Common shape formatting: fill, line, opacity, unit conversion, text styling."""
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt
from sdpm.schema.defaults import GRADIENT_DEFAULTS
from sdpm.utils.text import is_fullwidth, parse_styled_text


def _gradient_angle_to_ooxml(angle_deg: float) -> int:
    """Convert JSON gradient angle (degrees) to OOXML angle units.

    JSON convention matches PowerPoint UI: 0°=right(3 o'clock), clockwise.
    0°=left→right, 90°=top→bottom, 180°=right→left, 270°=bottom→top.
    OOXML uses 60000 units per degree with the same direction.
    """
    return int((angle_deg % 360) * 60000)


def _build_grad_fill_element(gradient: dict):
    """Build an <a:gradFill> XML element from a gradient dict.

    Returns an lxml Element ready to insert into spPr, ln, or tcPr.
    """
    from lxml import etree
    from pptx.oxml.ns import qn

    grad_fill = etree.Element(qn('a:gradFill'))
    if gradient.get('rotWithShape', GRADIENT_DEFAULTS['rotWithShape']):
        grad_fill.set('rotWithShape', '1')
    if gradient.get('flip'):
        grad_fill.set('flip', gradient['flip'])

    gs_lst = etree.SubElement(grad_fill, qn('a:gsLst'))
    for stop in gradient.get("stops", []):
        gs = etree.SubElement(gs_lst, qn('a:gs'))
        gs.set('pos', str(int(stop.get("position", 0) * 100000)))
        srgb = etree.SubElement(gs, qn('a:srgbClr'))
        srgb.set('val', stop.get("color", "#FFFFFF").lstrip("#").upper())
        if stop.get("opacity") is not None and stop["opacity"] < 1:
            alpha = etree.SubElement(srgb, qn('a:alpha'))
            alpha.set('val', str(int(stop["opacity"] * 100000)))

    grad_type = gradient.get("type", GRADIENT_DEFAULTS["type"])
    if grad_type in ("circle", "rect", "shape"):
        path_el = etree.SubElement(grad_fill, qn('a:path'))
        path_el.set('path', grad_type)
        ftr = gradient.get("fillToRect")
        if ftr:
            ft = etree.SubElement(path_el, qn('a:fillToRect'))
            for k in ('l', 't', 'r', 'b'):
                if ftr.get(k, 0) != 0:
                    ft.set(k, str(ftr[k]))
        tr = gradient.get("tileRect")
        if tr:
            tile = etree.SubElement(grad_fill, qn('a:tileRect'))
            for k in ('l', 't', 'r', 'b'):
                if tr.get(k, 0) != 0:
                    tile.set(k, str(tr[k]))
    else:
        lin = etree.SubElement(grad_fill, qn('a:lin'))
        lin.set('ang', str(_gradient_angle_to_ooxml(gradient.get("angle", 90))))
        lin.set('scaled', '1')

    return grad_fill


class FormattingMixin:
    """Mixin providing shape formatting and text styling methods."""

    def _apply_shape_formatting(self, shape, elem):
        """Apply fill, gradient, and line formatting to a shape."""
        gradient = elem.get("gradient")
        fill_color = elem.get("fill")
        
        if gradient:
            self._apply_gradient_fill(shape, gradient)
        elif fill_color == "none":
            shape.fill.background()
        elif fill_color:
            shape.fill.solid()
            hex_color = fill_color.lstrip("#")
            shape.fill.fore_color.rgb = RGBColor(
                int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            )
            opacity = elem.get("opacity")
            if opacity is not None and 0 <= opacity < 1:
                self._set_fill_opacity(shape, opacity)
        
        line_color = elem.get("line")
        line_width = elem.get("lineWidth", 1)
        line_gradient = elem.get("lineGradient")

        # Default: no line for shapes/textboxes/freeforms (override style lnRef)
        if line_color is None and not line_gradient:
            line_color = "none"

        if line_gradient:
            from lxml import etree
            from pptx.oxml.ns import qn
            sp_pr = shape._element.spPr
            ln = sp_pr.find(qn('a:ln'))
            if ln is None:
                ln = etree.SubElement(sp_pr, qn('a:ln'))
            ln.set('cap', 'flat')
            if elem.get("_lineWidthEmu") is not None:
                ln.set('w', str(elem["_lineWidthEmu"]))
            elif elem.get("lineWidth") is not None:
                ln.set('w', str(int(line_width * 12700)))
            # Remove existing fill
            for child in list(ln):
                if child.tag.endswith('}solidFill') or child.tag.endswith('}noFill') or child.tag.endswith('}gradFill'):
                    ln.remove(child)
            grad = _build_grad_fill_element(line_gradient)
            ln.append(grad)
        elif line_color and line_color != "none":
            shape.line.fill.solid()
            hex_color = line_color.lstrip("#")
            shape.line.color.rgb = RGBColor(
                int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            )
            shape.line.width = Pt(line_width)
            # Set line cap to flat for freeform shapes
            try:
                from pptx.oxml.ns import qn
                sp_pr = shape._element.spPr
                ln = sp_pr.find(qn('a:ln'))
                if ln is not None:
                    ln.set('cap', 'flat')
            except Exception:
                pass
            # Apply line opacity
            line_opacity = elem.get("lineOpacity")
            if line_opacity is not None and 0 <= line_opacity < 1:
                try:
                    from lxml import etree
                    from pptx.oxml.ns import qn as _qn
                    _ln = shape._element.spPr.find(_qn('a:ln'))
                    if _ln is not None:
                        _sf = _ln.find(_qn('a:solidFill'))
                        if _sf is not None:
                            _clr = _sf.find(_qn('a:srgbClr'))
                            if _clr is not None:
                                _alpha = etree.SubElement(_clr, _qn('a:alpha'))
                                _alpha.set('val', str(int(line_opacity * 100000)))
                except Exception:
                    pass
        elif line_color == "none":
            shape.line.fill.background()
            if elem.get("_lineWidthEmu") is not None:
                from pptx.oxml.ns import qn as _qn
                ln = shape._element.spPr.find(_qn('a:ln'))
                if ln is not None:
                    ln.set('w', str(elem["_lineWidthEmu"]))
            elif line_width is not None:
                from pptx.oxml.ns import qn as _qn
                ln = shape._element.spPr.find(_qn('a:ln'))
                if ln is not None:
                    ln.set('w', str(int(line_width * 12700)))
    
    def _px_to_emu(self, px):
        """Convert pixels (1920x1080 basis) to EMU."""
        return Emu(int(px * self.EMU_PER_PX))
    
    def _apply_gradient_fill(self, shape, gradient):
        """Apply gradient fill (linear or path) to a shape via direct XML."""
        from pptx.oxml.ns import qn

        sp_pr = shape._element.spPr
        for tag in ('a:noFill', 'a:solidFill', 'a:gradFill'):
            for el in sp_pr.findall(qn(tag)):
                sp_pr.remove(el)

        grad_fill = _build_grad_fill_element(gradient)

        ln_el = sp_pr.find(qn('a:ln'))
        if ln_el is not None:
            sp_pr.insert(list(sp_pr).index(ln_el), grad_fill)
        else:
            sp_pr.append(grad_fill)
    
    def _set_fill_opacity(self, shape, opacity):
        """Set fill opacity using low-level XML manipulation.
        
        Args:
            shape: Shape object
            opacity: 0.0 (fully transparent) to 1.0 (fully opaque)
        """
        from lxml import etree
        # alpha value in OOXML is percentage * 1000 (e.g., 50% = 50000)
        alpha_val = int(opacity * 100000)
        solidFill = shape.fill._xPr.solidFill
        if solidFill is not None:
            srgbClr = solidFill.srgbClr
            if srgbClr is not None:
                # Remove existing alpha if present
                nsmap = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
                for existing in srgbClr.findall('a:alpha', nsmap):
                    srgbClr.remove(existing)
                # Add alpha element
                alpha_elem = etree.SubElement(srgbClr, '{http://schemas.openxmlformats.org/drawingml/2006/main}alpha')
                alpha_elem.set('val', str(alpha_val))
    

    def _apply_styled_text(self, paragraph, text, default_color=None, default_font_size=None, font_family=None, no_default_color=False, no_default_font=False):
        """Apply styled text to a paragraph.
        
        Supports:
        - {{bold:text}}
        - {{italic:text}}
        - {{#RRGGBB:text}}
        - {{NNpt:text}}
        - {{link:URL:text}} - hyperlink
        
        Args:
            font_family: If specified, use this font for halfwidth chars (e.g., 'Lucida Console' for code)
        """
        segments = parse_styled_text(text)
        paragraph.clear()
        from lxml import etree
        from pptx.oxml.ns import qn
        
        for seg in segments:
            if font_family:
                sub_runs = self._split_by_width(seg["text"], halfwidth_font=font_family)
            else:
                sub_runs = self._split_by_width(seg["text"])
            
            for sub_text, font_name in sub_runs:
                # Handle line breaks (\n and \u000b)
                lines = sub_text.replace('\u000b', '\n').split('\n')
                for li, line in enumerate(lines):
                    if li > 0:
                        br = etree.SubElement(paragraph._p, qn('a:br'))
                        # Copy styles to br rPr
                        br_rPr = etree.SubElement(br, qn('a:rPr'))
                        if seg.get("bold"):
                            br_rPr.set('b', '1')
                        if seg.get("underline"):
                            br_rPr.set('u', 'sng')
                    run = paragraph.add_run()
                    run.text = line
                    run.font.name = seg.get("fontName") or (None if no_default_font else font_name) or None
                    # Set sym font for symbol fonts (Wingdings etc)
                    actual_font = run.font.name
                    if actual_font and actual_font.startswith(('Wingdings', 'Symbol', 'Webdings')):
                        from lxml import etree as _et
                        from pptx.oxml.ns import qn as _qn
                        rPr = run._r.get_or_add_rPr()
                        sym = _et.SubElement(rPr, _qn('a:sym'))
                        sym.set('typeface', actual_font)
                    # Apply all styles per run so multi-line labels render consistently
                    font_size = seg.get("fontSize") or default_font_size
                    if font_size:
                        run.font.size = Pt(font_size)
                    if "color" in seg:
                        hex_color = seg["color"].lstrip("#")
                        run.font.color.rgb = RGBColor(int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))
                    elif "link" not in seg and not no_default_color:
                        tc = self.theme_colors["text"].lstrip("#")
                        run.font.color.rgb = default_color or RGBColor.from_string(tc)
                    if seg.get("bold"):
                        run.font.bold = True
                    if seg.get("italic"):
                        run.font.italic = True
                    if seg.get("underline"):
                        run.font.underline = True
                    if "link" in seg:
                        run.hyperlink.address = seg["link"]
                        run.font.underline = True
    
    def _apply_text_gradient(self, shape, gradient):
        """Apply gradient fill to text in a shape."""
        from lxml import etree
        from pptx.oxml.ns import qn
        
        stops = gradient.get("stops", [])
        angle = gradient.get("angle", 0)
        
        # Find all run elements and apply gradient
        tx_body = shape._element.find(qn('p:txBody'))
        if tx_body is None:
            return
        
        for r in tx_body.findall('.//' + qn('a:r')):
            rPr = r.find(qn('a:rPr'))
            if rPr is None:
                rPr = etree.Element(qn('a:rPr'))
                r.insert(0, rPr)
            
            # Remove existing solidFill and gradFill
            for sf in rPr.findall(qn('a:solidFill')):
                rPr.remove(sf)
            for gf in rPr.findall(qn('a:gradFill')):
                rPr.remove(gf)
            
            # Create gradFill element
            grad_fill = etree.Element(qn('a:gradFill'))
            gs_lst = etree.SubElement(grad_fill, qn('a:gsLst'))
            
            for stop_info in stops:
                pos = int(stop_info.get("position", 0) * 100000)
                color_hex = stop_info.get("color", "#FFFFFF").lstrip("#")
                stop_opacity = stop_info.get("opacity")
                
                gs = etree.SubElement(gs_lst, qn('a:gs'))
                gs.set('pos', str(pos))
                srgb_clr = etree.SubElement(gs, qn('a:srgbClr'))
                srgb_clr.set('val', color_hex.upper())
                
                # Add opacity if specified
                if stop_opacity is not None and stop_opacity < 1:
                    alpha = etree.SubElement(srgb_clr, qn('a:alpha'))
                    alpha.set('val', str(int(stop_opacity * 100000)))
            
            # Add linear gradient with angle
            lin = etree.SubElement(grad_fill, qn('a:lin'))
            lin.set('ang', str(_gradient_angle_to_ooxml(angle)))
            lin.set('scaled', '0')
            
            # Insert gradFill at the beginning of rPr (before latin, ea, cs)
            rPr.insert(0, grad_fill)

    def _apply_text_gradient_runs(self, shape, grad_runs):
        """Apply gradient fill only to runs matching specified text."""
        from lxml import etree
        from pptx.oxml.ns import qn

        grad_map = {gr["text"]: gr["gradient"] for gr in grad_runs}
        tx_body = shape._element.find(qn('p:txBody'))
        if tx_body is None:
            return
        for r in tx_body.findall('.//' + qn('a:r')):
            t = r.find(qn('a:t'))
            if t is None or t.text not in grad_map:
                continue
            gradient = grad_map[t.text]
            rPr = r.find(qn('a:rPr'))
            if rPr is None:
                rPr = etree.Element(qn('a:rPr'))
                r.insert(0, rPr)
            for sf in rPr.findall(qn('a:solidFill')):
                rPr.remove(sf)
            grad_fill = etree.Element(qn('a:gradFill'))
            gs_lst = etree.SubElement(grad_fill, qn('a:gsLst'))
            for stop in gradient.get("stops", []):
                gs = etree.SubElement(gs_lst, qn('a:gs'))
                gs.set('pos', str(int(stop["position"] * 100000)))
                srgb = etree.SubElement(gs, qn('a:srgbClr'))
                srgb.set('val', stop["color"].lstrip("#").upper())
            lin = etree.SubElement(grad_fill, qn('a:lin'))
            lin.set('ang', str(_gradient_angle_to_ooxml(gradient.get("angle", 0))))
            lin.set('scaled', '0')
            rPr.insert(0, grad_fill)
    
    def _split_by_width(self, text, halfwidth_font=None):
        """Split text into runs by character width (fullwidth/halfwidth).

        Args:
            text: Text string to split.
            halfwidth_font: Font to use for halfwidth characters (default: self.fonts["halfwidth"]).

        Returns:
            list: List of (text, font_name) tuples.
        """
        if not text:
            return []

        fw_font = self.fonts["fullwidth"]
        hw_font = halfwidth_font or self.fonts["halfwidth"]
        runs = []
        current = []
        current_is_full = is_fullwidth(text[0])

        for char in text:
            char_is_full = is_fullwidth(char)
            if char_is_full == current_is_full:
                current.append(char)
            else:
                runs.append(("".join(current), fw_font if current_is_full else hw_font))
                current = [char]
                current_is_full = char_is_full

        if current:
            runs.append(("".join(current), fw_font if current_is_full else hw_font))

        return runs
    
