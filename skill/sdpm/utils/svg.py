# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SVG utilities: rendering, recoloring, dimensions, QR code generation."""
import math
import re
from pathlib import Path


def _recolor_svg(svg_bytes: bytes, color: str) -> bytes | None:
    """Recolor single-color SVG. Returns None if multi-color (skip)."""
    import sys
    text = svg_bytes.decode("utf-8")

    attr_colors = re.findall(r'(?:fill|stroke)\s*[=:]\s*["\']?\s*(#[0-9a-fA-F]{3,8}|rgb[^)]*\))', text)
    unique = set(c.lower().strip() for c in attr_colors)

    if len(unique) == 0:
        # No explicit fill/stroke — add fill to <svg> root element (e.g. Material Symbols)
        text = re.sub(r'<svg\b', f'<svg fill="{color}"', text, count=1)
        return text.encode("utf-8")
    if len(unique) > 1:
        print(f"Warning: iconColor skipped (multi-color SVG, {len(unique)} colors found)", file=sys.stderr)
        return None

    original = unique.pop()

    # No change needed — target color matches original
    if original.lower() == color.lower():
        return None

    has_fill = bool(re.search(r'fill\s*[=:]\s*["\']?\s*' + re.escape(original), text, re.IGNORECASE))
    has_stroke = bool(re.search(r'stroke\s*[=:]\s*["\']?\s*' + re.escape(original), text, re.IGNORECASE))

    if has_fill:
        text = re.sub(r'(fill\s*[=:]\s*["\']?\s*)' + re.escape(original), lambda m: m.group(1) + color, text, flags=re.IGNORECASE)
    if has_stroke:
        text = re.sub(r'(stroke\s*[=:]\s*["\']?\s*)' + re.escape(original), lambda m: m.group(1) + color, text, flags=re.IGNORECASE)

    return text.encode("utf-8")


def get_svg_dimensions(svg_path: Path) -> tuple[int, int]:
    """Get SVG dimensions from viewBox or width/height attributes."""
    from lxml import etree
    tree = etree.parse(str(svg_path))
    root = tree.getroot()

    vb = root.get('viewBox')
    if vb:
        parts = vb.replace(',', ' ').split()
        if len(parts) == 4:
            return int(float(parts[2])), int(float(parts[3]))

    w = root.get('width', '').replace('px', '')
    h = root.get('height', '').replace('px', '')
    if w and h:
        try:
            return int(float(w)), int(float(h))
        except ValueError:
            pass
    return 100, 100


def generate_qr_svg(url: str, size: int = 200, color: str | None = None,
                    gradient: dict | None = None, theme: str = "dark") -> bytes:
    """Generate a QR code as SVG with round dots and rounded finder patterns."""
    import qrcode

    default_color = "#FFFFFF" if theme == "dark" else "#000000"
    fill_color = color or default_color

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.modules
    n = len(matrix)
    cell = size / n
    r = cell * 0.42

    finder_origins = [(0, 0), (0, n - 7), (n - 7, 0)]
    finder_cells = set()
    for fr, fc in finder_origins:
        for dr in range(7):
            for dc in range(7):
                finder_cells.add((fr + dr, fc + dc))

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">']

    fill_ref = fill_color
    if gradient:
        angle = gradient.get("angle", 0)
        rad = math.radians(angle)
        x1 = 50 - 50 * math.cos(rad)
        y1 = 50 - 50 * math.sin(rad)
        x2 = 50 + 50 * math.cos(rad)
        y2 = 50 + 50 * math.sin(rad)
        stops_xml = ""
        for s in gradient.get("stops", []):
            stops_xml += f'<stop offset="{s["position"]*100}%" stop-color="{s["color"]}"/>'
        parts.append(f'<defs><linearGradient id="qg" x1="{x1}%" y1="{y1}%" x2="{x2}%" y2="{y2}%">{stops_xml}</linearGradient></defs>')
        fill_ref = "url(#qg)"

    for row in range(n):
        for col in range(n):
            if matrix[row][col] and (row, col) not in finder_cells:
                cx = (col + 0.5) * cell
                cy = (row + 0.5) * cell
                parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill_ref}"/>')

    for fr, fc in finder_origins:
        ox = fc * cell
        oy = fr * cell
        s7 = 7 * cell
        s3 = 3 * cell
        rx_outer = cell * 0.8
        rx_inner = cell * 0.6
        sw = cell * 0.85
        parts.append(f'<rect x="{ox + sw/2:.1f}" y="{oy + sw/2:.1f}" width="{s7 - sw:.1f}" height="{s7 - sw:.1f}" rx="{rx_outer:.1f}" fill="none" stroke="{fill_ref}" stroke-width="{sw:.1f}"/>')
        inner_x = ox + 2 * cell
        inner_y = oy + 2 * cell
        parts.append(f'<rect x="{inner_x:.1f}" y="{inner_y:.1f}" width="{s3:.1f}" height="{s3:.1f}" rx="{rx_inner:.1f}" fill="{fill_ref}"/>')

    parts.append('</svg>')
    return '\n'.join(parts).encode('utf-8')


def add_svg_to_slide(slide, svg_bytes: bytes, x, y, width, height):
    """Add SVG directly to PPTX slide via OpenXML asvg:svgBlip."""
    from lxml import etree
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.opc.package import Part
    from pptx.opc.packuri import PackURI

    slide_part = slide.part

    idx = 1
    while True:
        partname = f'/ppt/media/svg_image{idx}.svg'
        if not any(partname == str(p.partname) for p in slide_part.package.iter_parts()):
            break
        idx += 1

    svg_part = Part(PackURI(partname), 'image/svg+xml', slide_part.package, svg_bytes)
    rId = slide_part.relate_to(svg_part, RT.IMAGE)

    spTree = slide.shapes._spTree
    shape_id = max((int(sp.get('id', 0)) for sp in spTree.iter() if sp.get('id', '').isdigit()), default=0) + 1

    SVG_BLIP_URI = '{96DAC541-7B7A-43D3-8B79-37D633B846F1}'
    pic_xml = (
        f'<p:pic xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        f' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
        f' xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main">'
        f'<p:nvPicPr>'
        f'<p:cNvPr id="{shape_id}" name="SVG {shape_id}"/>'
        f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>'
        f'<p:nvPr/>'
        f'</p:nvPicPr>'
        f'<p:blipFill>'
        f'<a:blip r:embed="{rId}">'
        f'<a:extLst>'
        f'<a:ext uri="{SVG_BLIP_URI}">'
        f'<asvg:svgBlip r:embed="{rId}"/>'
        f'</a:ext>'
        f'</a:extLst>'
        f'</a:blip>'
        f'<a:stretch><a:fillRect/></a:stretch>'
        f'</p:blipFill>'
        f'<p:spPr>'
        f'<a:xfrm>'
        f'<a:off x="{x}" y="{y}"/>'
        f'<a:ext cx="{width}" cy="{height}"/>'
        f'</a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'</p:spPr>'
        f'</p:pic>'
    )

    pic_element = etree.fromstring(pic_xml)
    spTree.append(pic_element)
    return pic_element
