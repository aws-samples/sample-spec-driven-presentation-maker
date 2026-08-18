# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared constants and helpers for converter modules."""
import defusedxml
defusedxml.defuse_stdlib()

import xml.etree.ElementTree as ET

from contextlib import contextmanager
from contextvars import ContextVar


_NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
       'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
       'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

# Default scale: EMU per px on the 1920px basis of a standard 16:9 deck
# (12192000 EMU / 1920 px). Kept as a constant for import compatibility;
# converter internals must call get_emu_per_px() instead, which resolves
# the scale of the *current* conversion scope.
EMU_PER_PX = 6350

# Current conversion scale. A ContextVar — not a module global — so nested
# and concurrent conversions are isolated per execution context, and no
# non-standard scale can leak out of a conversion.
_CURRENT_EMU_PER_PX: ContextVar[float] = ContextVar(
    "converter_emu_per_px", default=float(EMU_PER_PX))


def get_emu_per_px() -> float:
    """EMU-per-px scale of the current conversion scope (default 6350.0)."""
    return _CURRENT_EMU_PER_PX.get()


@contextmanager
def conversion_scale(slide_width_emu):
    """Scope the converter's px scale to ``slide_width_emu / 1920``.

    The previous scale is always restored on exit — normal return,
    exception, or nested use — so error paths and reentrant conversions
    cannot poison later conversions in the same process.
    """
    from sdpm.engine import emu_per_px as _emu_per_px
    token = _CURRENT_EMU_PER_PX.set(_emu_per_px(slide_width_emu))
    try:
        yield
    finally:
        _CURRENT_EMU_PER_PX.reset(token)

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
    emu_per_px = get_emu_per_px()
    diff = {}
    if shape.left != layout_ph.left:
        diff["_x"] = round(shape.left / emu_per_px)
    if shape.top != layout_ph.top:
        diff["_y"] = round(shape.top / emu_per_px)
    if shape.width != layout_ph.width:
        diff["_width"] = round(shape.width / emu_per_px)
    if shape.height != layout_ph.height:
        diff["_height"] = round(shape.height / emu_per_px)
    return diff

def _base_element(shape, type_name, **extra):
    """Create base element dict with position, size, rotation."""
    emu_per_px = get_emu_per_px()
    elem = {
        "type": type_name,
        "x": round(shape.left / emu_per_px),
        "y": round(shape.top / emu_per_px),
        "width": round(shape.width / emu_per_px),
        "height": round(shape.height / emu_per_px),
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
