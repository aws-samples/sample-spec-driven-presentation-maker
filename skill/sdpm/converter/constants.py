# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared constants and helpers for converter modules."""
import defusedxml
defusedxml.defuse_stdlib()

import xml.etree.ElementTree as ET



_NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
       'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}

EMU_PER_PX = 6350


def set_emu_per_px(slide_width_emu):
    """Set EMU_PER_PX based on actual slide width. Call before extraction."""
    import sdpm.converter.constants as _c
    _c.EMU_PER_PX = slide_width_emu / 1920
    # Update all modules that imported EMU_PER_PX
    for mod_name in ('sdpm.converter.elements', 'sdpm.converter.slide',
                     'sdpm.converter.xml_helpers', 'sdpm.converter.text',
                     'sdpm.converter.table', 'sdpm.converter.chart',
                     'sdpm.converter.pipeline', 'sdpm.converter'):
        import sys
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, 'EMU_PER_PX'):
            mod.EMU_PER_PX = _c.EMU_PER_PX

def _serialize_lstStyle(source):
    """Extract lstStyle XML string from a shape/element with text frame. Returns XML string or None."""
    try:
        txBody = source.text_frame._txBody if hasattr(source, 'text_frame') else source
        lstStyle = txBody.find(f'{{{_NS["a"]}}}lstStyle')
        if lstStyle is not None and len(lstStyle) > 0:
            return ET.tostring(lstStyle, encoding='unicode')
    except Exception:
        pass
    return None

def _extract_autofit_props(shape):
    """Extract bodyPr autofit properties. Returns dict with _spAutoFit/_noAutofit."""
    result = {}
    try:
        bodyPr = shape.text_frame._txBody.find(f'{{{_NS["a"]}}}bodyPr')
        if bodyPr is not None:
            spAuto = bodyPr.find(f'{{{_NS["a"]}}}spAutoFit')
            if spAuto is not None:
                result["_spAutoFit"] = True
            else:
                noAuto = bodyPr.find(f'{{{_NS["a"]}}}noAutofit')
                if noAuto is not None:
                    result["_noAutofit"] = True
    except Exception:
        pass
    return result

def _hex(el):
    """Get hex color string from srgbClr element. Returns '#RRGGBB' or None."""
    return f"#{el.get('val')}" if el is not None and el.get('val') else None

def _position_diff(shape, layout_ph):
    """Return dict of _x/_y/_width/_height where shape differs from layout placeholder."""
    diff = {}
    if shape.left != layout_ph.left:
        diff["_x"] = round(shape.left / EMU_PER_PX)
    if shape.top != layout_ph.top:
        diff["_y"] = round(shape.top / EMU_PER_PX)
    if shape.width != layout_ph.width:
        diff["_width"] = round(shape.width / EMU_PER_PX)
    if shape.height != layout_ph.height:
        diff["_height"] = round(shape.height / EMU_PER_PX)
    return diff

def _base_element(shape, type_name, **extra):
    """Create base element dict with position, size, rotation."""
    elem = {
        "type": type_name,
        "x": round(shape.left / EMU_PER_PX),
        "y": round(shape.top / EMU_PER_PX),
        "width": round(shape.width / EMU_PER_PX),
        "height": round(shape.height / EMU_PER_PX),
        **extra,
    }
    if shape.rotation != 0:
        elem["rotation"] = round(shape.rotation, 1)
    return elem

def _add_flip(elem, shape):
    """Add flipH/flipV to element if present in shape xfrm."""
    try:
        xfrm = shape._element.spPr.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}xfrm')
        if xfrm is not None:
            if xfrm.get('flipH') == '1':
                elem["flipH"] = True
            if xfrm.get('flipV') == '1':
                elem["flipV"] = True
    except Exception:
        pass
