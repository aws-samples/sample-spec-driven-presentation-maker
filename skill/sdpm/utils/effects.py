# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Visual effects: shadow, glow, softEdge, reflection, bevel, 3D rotation."""
from lxml import etree
from pptx.oxml.ns import qn

# --- Effect presets ---
SHADOW_PRESETS = {
    "sm": {"type": "outer", "blur": 4, "distance": 2, "direction": 135, "color": "#000000", "opacity": 0.25},
    "md": {"type": "outer", "blur": 8, "distance": 4, "direction": 135, "color": "#000000", "opacity": 0.35},
    "lg": {"type": "outer", "blur": 16, "distance": 8, "direction": 135, "color": "#000000", "opacity": 0.45},
}
GLOW_PRESETS = {
    "sm": {"radius": 4, "color": "#4A90D9", "opacity": 0.4},
    "md": {"radius": 8, "color": "#4A90D9", "opacity": 0.5},
    "lg": {"radius": 16, "color": "#4A90D9", "opacity": 0.6},
}
REFLECTION_PRESETS = {
    "sm": {"blur": 1, "distance": 0, "size": 30, "opacity": 0.2},
    "md": {"blur": 2, "distance": 0, "size": 50, "opacity": 0.3},
    "lg": {"blur": 4, "distance": 0, "size": 70, "opacity": 0.4},
}
BEVEL_PRESETS = {
    "sm": {"type": "circle", "width": 4, "height": 4},
    "md": {"type": "circle", "width": 8, "height": 8},
    "lg": {"type": "relaxedInset", "width": 12, "height": 12},
}
ROTATION3D_PRESETS = {
    "perspective-left":        {"prst": "perspectiveLeft"},
    "perspective-right":       {"prst": "perspectiveRight"},
    "perspective-top":         {"prst": "perspectiveAbove"},
    "perspective-bottom":      {"prst": "perspectiveBelow"},
    "perspective-left-most":   {"prst": "perspectiveContrastingLeftFacing"},
    "perspective-right-most":  {"prst": "perspectiveContrastingRightFacing"},
    "isometric-top":           {"prst": "isometricTopUp"},
    "isometric-left":          {"prst": "isometricLeftDown"},
}

# OOXML spPr child order
_SPPR_ORDER = ['xfrm', 'custGeom', 'prstGeom', 'noFill', 'solidFill', 'gradFill', 'blipFill', 'pattFill',
               'grpFill', 'ln', 'effectLst', 'effectDag', 'scene3d', 'sp3d']


def _insert_ordered(parent, child):
    """Insert child element into spPr at the correct schema position."""
    child_local = child.tag.split('}')[-1]
    if child_local not in _SPPR_ORDER:
        parent.append(child)
        return
    child_idx = _SPPR_ORDER.index(child_local)
    for i, existing in enumerate(parent):
        existing_local = existing.tag.split('}')[-1]
        if existing_local in _SPPR_ORDER and _SPPR_ORDER.index(existing_local) > child_idx:
            parent.insert(i, child)
            return
    parent.append(child)


def apply_effects(element, elem_def, emu_per_px=6350):
    """Apply visual effects (shadow, glow, softEdge, reflection, bevel, 3D rotation)."""
    shadow = elem_def.get("shadow")
    glow = elem_def.get("glow")
    soft_edge = elem_def.get("softEdge")
    reflection = elem_def.get("reflection")
    bevel = elem_def.get("bevel")
    rotation3d = elem_def.get("rotation3d")

    if not any([shadow, glow, soft_edge, reflection, bevel, rotation3d]):
        return

    sp_pr = element.spPr if hasattr(element, 'spPr') else element.find(qn('p:spPr'))
    if sp_pr is None:
        sp_pr = element.find(qn('pic:spPr'))
    if sp_pr is None:
        return

    if any([shadow, glow, soft_edge, reflection]):
        for existing in sp_pr.findall(qn('a:effectLst')):
            sp_pr.remove(existing)
        effect_lst = etree.Element(qn('a:effectLst'))
        _insert_ordered(sp_pr, effect_lst)

        if shadow:
            if isinstance(shadow, str):
                shadow = SHADOW_PRESETS.get(shadow, SHADOW_PRESETS["md"])
            shdw_type = shadow.get("type", "outer")
            blur = int(shadow.get("blur", 8) * emu_per_px)
            dist = int(shadow.get("distance", 4) * emu_per_px)
            direction = int(shadow.get("direction", 315) * 60000)
            color = shadow.get("color", "#000000").lstrip("#")
            opacity = shadow.get("opacity", 0.35)
            tag = qn('a:outerShdw') if shdw_type == "outer" else qn('a:innerShdw')
            shdw = etree.SubElement(effect_lst, tag)
            shdw.set('blurRad', str(blur))
            shdw.set('dist', str(dist))
            shdw.set('dir', str(direction))
            shdw.set('algn', 'bl')
            shdw.set('rotWithShape', '0')
            srgb = etree.SubElement(shdw, qn('a:srgbClr'))
            srgb.set('val', color)
            alpha = etree.SubElement(srgb, qn('a:alpha'))
            alpha.set('val', str(int(opacity * 100000)))

        if glow:
            if isinstance(glow, str):
                glow = GLOW_PRESETS.get(glow, GLOW_PRESETS["md"])
            radius = glow.get("_radiusEmu") or int(glow.get("radius", 8) * emu_per_px)
            color = glow.get("color", "#4A90D9").lstrip("#")
            opacity = glow.get("opacity", 0.5)
            glow_el = etree.SubElement(effect_lst, qn('a:glow'))
            glow_el.set('rad', str(radius))
            srgb = etree.SubElement(glow_el, qn('a:srgbClr'))
            srgb.set('val', color)
            alpha = etree.SubElement(srgb, qn('a:alpha'))
            alpha.set('val', str(int(opacity * 100000)))

        if soft_edge:
            radius = int(soft_edge * emu_per_px)
            se = etree.SubElement(effect_lst, qn('a:softEdge'))
            se.set('rad', str(radius))

        if reflection:
            if isinstance(reflection, str):
                reflection = REFLECTION_PRESETS.get(reflection, REFLECTION_PRESETS["md"])
            ref = etree.SubElement(effect_lst, qn('a:reflection'))
            ref.set('blurRad', str(int(reflection.get("blur", 2) * emu_per_px)))
            ref.set('stA', str(int(reflection.get("opacity", 0.3) * 100000)))
            ref.set('endA', '0')
            ref.set('endPos', str(int(reflection.get("size", 50) * 1000)))
            ref.set('dist', str(int(reflection.get("distance", 0) * emu_per_px)))
            ref.set('dir', str(int(reflection.get("direction", 90) if isinstance(elem_def.get("reflection"), dict) else 90) * 60000))
            ref.set('sy', '-100000')
            ref.set('algn', 'bl')
            ref.set('rotWithShape', '0')

    if bevel:
        if isinstance(bevel, str):
            bevel = BEVEL_PRESETS.get(bevel, BEVEL_PRESETS["md"])
        if sp_pr.find(qn('a:scene3d')) is None:
            scene3d = etree.Element(qn('a:scene3d'))
            _insert_ordered(sp_pr, scene3d)
            camera = etree.SubElement(scene3d, qn('a:camera'))
            camera.set('prst', 'orthographicFront')
            light = etree.SubElement(scene3d, qn('a:lightRig'))
            light.set('rig', 'threePt')
            light.set('dir', 't')
        sp3d = sp_pr.find(qn('a:sp3d'))
        if sp3d is None:
            sp3d = etree.Element(qn('a:sp3d'))
            _insert_ordered(sp_pr, sp3d)
        bevel_t = etree.SubElement(sp3d, qn('a:bevelT'))
        bevel_t.set('w', str(int(bevel.get("width", 8) * 12700)))
        bevel_t.set('h', str(int(bevel.get("height", 8) * 12700)))
        bevel_t.set('prst', bevel.get("type", "circle"))

    if rotation3d:
        if isinstance(rotation3d, str):
            rotation3d = ROTATION3D_PRESETS.get(rotation3d, ROTATION3D_PRESETS["perspective-left"])
        scene3d = sp_pr.find(qn('a:scene3d'))
        if scene3d is None:
            scene3d = etree.Element(qn('a:scene3d'))
            _insert_ordered(sp_pr, scene3d)
        camera = scene3d.find(qn('a:camera'))
        if camera is None:
            camera = etree.SubElement(scene3d, qn('a:camera'))
        prst = rotation3d.get("prst")
        if prst:
            camera.set('prst', prst)
        else:
            perspective = rotation3d.get("perspective", 120)
            camera.set('prst', 'perspectiveFront' if perspective > 0 else 'orthographicFront')
            if perspective > 0:
                camera.set('fov', str(int(perspective * 60000)))
            rot = etree.SubElement(camera, qn('a:rot'))
            rot.set('lat', str(int(rotation3d.get("rotX", 0) * 60000)))
            rot.set('lon', str(int(rotation3d.get("rotY", 0) * 60000)))
            rot.set('rev', str(int(rotation3d.get("rotZ", 0) * 60000)))
        light = scene3d.find(qn('a:lightRig'))
        if light is None:
            light = etree.SubElement(scene3d, qn('a:lightRig'))
        light.set('rig', 'threePt')
        light.set('dir', 't')
