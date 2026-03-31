# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""XML extraction helpers for fill, line, effects, 3D."""
import defusedxml
defusedxml.defuse_stdlib()

import xml.etree.ElementTree as ET



from .constants import _NS, _hex, EMU_PER_PX
from .color import _resolve_scheme_color, _resolve_color_with_transforms, apply_color_transforms


def _apply_srgb_transforms(hex_color, transforms):
    """Apply lumMod/lumOff/tint/shade transforms to an srgbClr."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if 'lumMod' in transforms or 'lumOff' in transforms:
        mod = int(transforms.get('lumMod', '100000')) / 100000
        off = int(transforms.get('lumOff', '0')) / 100000
        r = min(255, max(0, int(r * mod + 255 * off)))
        g = min(255, max(0, int(g * mod + 255 * off)))
        b = min(255, max(0, int(b * mod + 255 * off)))
    if 'tint' in transforms:
        t = int(transforms['tint']) / 100000
        rl, gl, bl = pow(r/255, 2.2), pow(g/255, 2.2), pow(b/255, 2.2)
        rl, gl, bl = rl + (1-rl)*t, gl + (1-gl)*t, bl + (1-bl)*t
        r, g, b = int(pow(max(0,rl), 1/2.2)*255), int(pow(max(0,gl), 1/2.2)*255), int(pow(max(0,bl), 1/2.2)*255)
    if 'shade' in transforms:
        s = int(transforms['shade']) / 100000
        rl, gl, bl = pow(r/255, 2.2)*s, pow(g/255, 2.2)*s, pow(b/255, 2.2)*s
        r, g, b = int(pow(max(0,rl), 1/2.2)*255), int(pow(max(0,gl), 1/2.2)*255), int(pow(max(0,bl), 1/2.2)*255)
    return f"#{min(255,max(0,r)):02X}{min(255,max(0,g)):02X}{min(255,max(0,b)):02X}"

def extract_line_dash(shape):
    """Extract line dash type from shape XML."""
    try:
        sp_pr = shape._element.find(f'{{{_NS["p"]}}}spPr')
        if sp_pr is not None:
            ln = sp_pr.find('a:ln', _NS)
            if ln is not None:
                prst_dash = ln.find('a:prstDash', _NS)
                if prst_dash is not None:
                    dash_val = prst_dash.get('val')
                    if dash_val and dash_val != 'solid':
                        return dash_val
    except Exception:
        pass
    return None



# ── Color resolution ─────────────────────────────────────────────────────

def _resolve_line_from_style(shape, theme_colors, color_mapping, theme_styles=None):
    """Resolve line color/width from style reference (lnRef). Returns dict or None."""
    try:
        style = shape._element.find(f'{{{_NS["p"]}}}style')
        if style is None:
            return {"line": "none"}
        ln_ref = style.find(f'{{{_NS["a"]}}}lnRef')
        if ln_ref is None:
            return {"line": "none"}
        idx = ln_ref.get('idx')
        scheme_clr = ln_ref.find(f'{{{_NS["a"]}}}schemeClr')
        if scheme_clr is not None and idx and int(idx) > 0:
            resolved = _resolve_scheme_color(scheme_clr.get('val'), theme_colors, color_mapping)
            if resolved:
                # Try to get actual width from theme lnStyleLst
                width = {1: 0.5, 2: 1.0, 3: 1.5}.get(int(idx), 1.0)
                if theme_styles and theme_styles.get("line"):
                    style_idx = int(idx) - 1
                    if 0 <= style_idx < len(theme_styles["line"]):
                        ln_xml = theme_styles["line"][style_idx]
                        import re
                        m = re.search(r'\bw="(\d+)"', ln_xml)
                        if m:
                            width = round(int(m.group(1)) / 12700, 1)
                return {"line": resolved, "lineWidth": width}
        return {"line": "none"}
    except Exception:
        return {"line": "none"}

def _extract_effects_from_xml(sp_pr, theme_colors=None, color_mapping=None):
    """Extract visual effects (shadow, glow, softEdge) from spPr XML. Returns dict."""
    result = {}
    if sp_pr is None:
        return result
    effect_lst = sp_pr.find(f'{{{_NS["a"]}}}effectLst')
    if effect_lst is None:
        return result

    # Shadow (outer)
    outer = effect_lst.find(f'{{{_NS["a"]}}}outerShdw')
    if outer is not None:
        s = {"type": "outer"}
        if outer.get('blurRad'):
            s["blur"] = round(int(outer.get('blurRad')) / EMU_PER_PX)
        if outer.get('dist'):
            s["distance"] = round(int(outer.get('dist')) / EMU_PER_PX)
        if outer.get('dir'):
            s["direction"] = round(int(outer.get('dir')) / 60000)
        clr = outer.find(f'{{{_NS["a"]}}}srgbClr')
        if clr is not None:
            s["color"] = f"#{clr.get('val', '000000')}"
            alpha = clr.find(f'{{{_NS["a"]}}}alpha')
            if alpha is not None:
                s["opacity"] = round(int(alpha.get('val', 100000)) / 100000, 2)
        result["shadow"] = s

    # Shadow (inner)
    inner = effect_lst.find(f'{{{_NS["a"]}}}innerShdw')
    if inner is not None:
        s = {"type": "inner"}
        if inner.get('blurRad'):
            s["blur"] = round(int(inner.get('blurRad')) / EMU_PER_PX)
        if inner.get('dist'):
            s["distance"] = round(int(inner.get('dist')) / EMU_PER_PX)
        if inner.get('dir'):
            s["direction"] = round(int(inner.get('dir')) / 60000)
        clr = inner.find(f'{{{_NS["a"]}}}srgbClr')
        if clr is not None:
            s["color"] = f"#{clr.get('val', '000000')}"
            alpha = clr.find(f'{{{_NS["a"]}}}alpha')
            if alpha is not None:
                s["opacity"] = round(int(alpha.get('val', 100000)) / 100000, 2)
        result["shadow"] = s

    # Glow
    glow = effect_lst.find(f'{{{_NS["a"]}}}glow')
    if glow is not None:
        g = {}
        if glow.get('rad'):
            g["radius"] = round(int(glow.get('rad')) / EMU_PER_PX)
            g["_radiusEmu"] = int(glow.get('rad'))
        clr = glow.find(f'{{{_NS["a"]}}}srgbClr')
        scheme = glow.find(f'{{{_NS["a"]}}}schemeClr')
        if clr is not None:
            g["color"] = _hex(clr)
            alpha = clr.find(f'{{{_NS["a"]}}}alpha')
            if alpha is not None:
                g["opacity"] = round(int(alpha.get('val', '100000')) / 100000, 2)
        elif scheme is not None:
            resolved = _resolve_scheme_color(scheme.get('val'), theme_colors, color_mapping)
            if resolved:
                g["color"] = resolved
            alpha = scheme.find(f'{{{_NS["a"]}}}alpha')
            if alpha is not None:
                g["opacity"] = round(int(alpha.get('val', '100000')) / 100000, 2)
        result["glow"] = g

    # Soft Edge
    se = effect_lst.find(f'{{{_NS["a"]}}}softEdge')
    if se is not None and se.get('rad'):
        result["softEdge"] = round(int(se.get('rad')) / EMU_PER_PX)

    # Reflection
    ref = effect_lst.find(f'{{{_NS["a"]}}}reflection')
    if ref is not None:
        r = {}
        if ref.get('blurRad'):
            r["blur"] = round(int(ref.get('blurRad')) / EMU_PER_PX)
        if ref.get('stA'):
            r["opacity"] = round(int(ref.get('stA')) / 100000, 2)
        if ref.get('endPos'):
            r["size"] = round(int(ref.get('endPos')) / 1000)
        if ref.get('dist') and int(ref.get('dist')) > 0:
            r["distance"] = round(int(ref.get('dist')) / EMU_PER_PX)
        result["reflection"] = r

    return result

def _extract_3d_from_xml(sp_pr):
    """Extract 3D effects (bevel, rotation3d) from spPr XML. Returns dict."""
    result = {}
    if sp_pr is None:
        return result

    # Bevel
    sp3d = sp_pr.find(f'{{{_NS["a"]}}}sp3d')
    if sp3d is not None:
        bevel_t = sp3d.find(f'{{{_NS["a"]}}}bevelT')
        if bevel_t is not None:
            b = {}
            if bevel_t.get('prst'):
                b["type"] = bevel_t.get('prst')
            if bevel_t.get('w'):
                b["width"] = round(int(bevel_t.get('w')) / 12700)
            if bevel_t.get('h'):
                b["height"] = round(int(bevel_t.get('h')) / 12700)
            result["bevel"] = b

    # 3D Rotation
    scene3d = sp_pr.find(f'{{{_NS["a"]}}}scene3d')
    if scene3d is not None:
        camera = scene3d.find(f'{{{_NS["a"]}}}camera')
        if camera is not None:
            prst = camera.get('prst', '')
            _cam_map = {
                'perspectiveLeft': 'perspective-left', 'perspectiveRight': 'perspective-right',
                'perspectiveAbove': 'perspective-top',
                'isometricTopUp': 'isometric-top', 'isometricLeftDown': 'isometric-left',
            }
            if prst in _cam_map:
                result["rotation3d"] = _cam_map[prst]
            else:
                rot = camera.find(f'{{{_NS["a"]}}}rot')
                if rot is not None:
                    r = {}
                    for attr, key in [('lat', 'rotX'), ('lon', 'rotY'), ('rev', 'rotZ')]:
                        v = rot.get(attr)
                        if v and int(v) != 0:
                            r[key] = round(int(v) / 60000)
                    fov = camera.get('fov')
                    if fov:
                        r["perspective"] = round(int(fov) / 60000)
                    if r:
                        result["rotation3d"] = r

    return result

def _extract_fill_from_xml(sp_pr, theme_colors=None, color_mapping=None):
    """Extract fill/gradient/opacity from spPr XML. Returns dict."""
    result = {}
    if sp_pr is None:
        return {"fill": "none"}
    no_fill = sp_pr.find('a:noFill', _NS)
    if no_fill is not None:
        return {"fill": "none"}
    # Solid fill (direct child only)
    solid = sp_pr.find('a:solidFill', _NS)
    if solid is not None:
        srgb = solid.find('a:srgbClr', _NS)
        scheme = solid.find('a:schemeClr', _NS)
        if srgb is not None:
            result["fill"] = _hex(srgb)
            alpha = srgb.find('a:alpha', _NS)
            if alpha is not None:
                result["opacity"] = round(int(alpha.get('val')) / 100000, 2)
        elif scheme is not None:
            resolved = _resolve_color_with_transforms(scheme, theme_colors, color_mapping)
            if resolved:
                result["fill"] = resolved
            alpha = scheme.find('a:alpha', _NS)
            if alpha is not None:
                result["opacity"] = round(int(alpha.get('val')) / 100000, 2)
        return result if "fill" in result else {"fill": "none"}
    # Gradient fill
    grad = sp_pr.find('a:gradFill', _NS)
    if grad is not None:
        stops = []
        for gs in grad.findall('.//a:gs', _NS):
            pos = round(int(gs.get('pos', '0')) / 100000, 2)
            srgb = gs.find('.//a:srgbClr', _NS)
            scheme = gs.find('.//a:schemeClr', _NS)
            stop_info = {"position": pos}
            if srgb is not None:
                color_hex = _hex(srgb)
                # Apply color transforms (lumMod, lumOff, etc.) on srgbClr
                transforms = {}
                for t_name in ('lumMod', 'lumOff', 'satMod', 'satOff', 'tint', 'shade'):
                    t_el = srgb.find(f'a:{t_name}', _NS)
                    if t_el is not None:
                        transforms[t_name] = t_el.get('val')
                if transforms:
                    color_hex = _apply_srgb_transforms(color_hex, transforms)
                stop_info["color"] = color_hex
                alpha = srgb.find('a:alpha', _NS)
                if alpha is not None:
                    stop_info["opacity"] = round(int(alpha.get('val')) / 100000, 2)
            elif scheme is not None:
                resolved = _resolve_color_with_transforms(scheme, theme_colors, color_mapping)
                if resolved:
                    stop_info["color"] = resolved
                alpha = scheme.find('a:alpha', _NS)
                if alpha is not None:
                    stop_info["opacity"] = round(int(alpha.get('val')) / 100000, 2)
            if "color" in stop_info:
                stops.append(stop_info)
        if stops:
            grad_info = {"stops": stops}
            lin_el = grad.find('a:lin', _NS)
            path_el = grad.find('a:path', _NS)
            if lin_el is not None:
                xml_angle = round(int(lin_el.get('ang', '0')) / 60000, 1)
                grad_info["angle"] = xml_angle
                grad_info["type"] = "linear"
            elif path_el is not None:
                grad_info["type"] = path_el.get('path', 'circle')  # circle, rect, shape
                fill_to = path_el.find('a:fillToRect', _NS)
                if fill_to is not None:
                    grad_info["fillToRect"] = {
                        "l": int(fill_to.get('l', '0')),
                        "t": int(fill_to.get('t', '0')),
                        "r": int(fill_to.get('r', '0')),
                        "b": int(fill_to.get('b', '0')),
                    }
                tile = grad.find('a:tileRect', _NS)
                if tile is not None:
                    grad_info["tileRect"] = {
                        "l": int(tile.get('l', '0')),
                        "t": int(tile.get('t', '0')),
                        "r": int(tile.get('r', '0')),
                        "b": int(tile.get('b', '0')),
                    }
            else:
                grad_info["angle"] = 90
                grad_info["type"] = "linear"
            if grad.get('flip'):
                grad_info["flip"] = grad.get('flip')
            if grad.get('rotWithShape'):
                grad_info["rotWithShape"] = grad.get('rotWithShape') == '1'
            result["gradient"] = grad_info
            return result
    # Pattern fill
    patt = sp_pr.find('a:pattFill', _NS)
    if patt is not None:
        pf = {"pattern": patt.get('prst', 'dkDnDiag')}
        fg_clr = patt.find('a:fgClr', _NS)
        if fg_clr is not None:
            srgb = fg_clr.find('a:srgbClr', _NS)
            if srgb is not None:
                pf["fgColor"] = _hex(srgb)
        bg_clr = patt.find('a:bgClr', _NS)
        if bg_clr is not None:
            srgb = bg_clr.find('a:srgbClr', _NS)
            if srgb is not None:
                pf["bgColor"] = _hex(srgb)
        return {"patternFill": pf}
    return {"fill": "none"}

def _extract_line_from_xml(sp_pr, theme_colors=None, color_mapping=None):
    """Extract line/lineGradient/lineWidth from spPr XML. Returns dict."""
    result = {}
    if sp_pr is None:
        return {"line": "none"}
    ln = sp_pr.find('a:ln', _NS)
    if ln is None:
        return {"line": "none"}
    w = ln.get('w')
    if w:
        result["lineWidth"] = round(int(w) / 12700, 1)
        result["_lineWidthEmu"] = int(w)
    # noFill
    if ln.find('a:noFill', _NS) is not None:
        result["line"] = "none"
        return result
    # gradFill
    grad = ln.find('a:gradFill', _NS)
    if grad is not None:
        stops = []
        for gs in grad.findall('.//a:gs', _NS):
            pos = round(int(gs.get('pos', '0')) / 100000, 2)
            srgb = gs.find('.//a:srgbClr', _NS)
            scheme = gs.find('.//a:schemeClr', _NS)
            color = None
            opacity = None
            if srgb is not None:
                color = _hex(srgb)
                alpha = srgb.find('a:alpha', _NS)
                if alpha is not None:
                    opacity = round(int(alpha.get('val')) / 100000, 2)
            elif scheme is not None:
                color = _resolve_color_with_transforms(scheme, theme_colors, color_mapping)
                alpha = scheme.find('a:alpha', _NS)
                if alpha is not None:
                    opacity = round(int(alpha.get('val')) / 100000, 2)
            if color:
                stop_info = {"position": pos, "color": color}
                if opacity is not None:
                    stop_info["opacity"] = opacity
                stops.append(stop_info)
        if stops:
            grad_info = {"stops": stops}
            lin_el = grad.find('a:lin', _NS)
            path_el = grad.find('a:path', _NS)
            if lin_el is not None:
                grad_info["angle"] = round(int(lin_el.get('ang', '0')) / 60000, 1)
                grad_info["type"] = "linear"
            elif path_el is not None:
                grad_info["type"] = path_el.get('path', 'circle')
                fill_to = path_el.find('a:fillToRect', _NS)
                if fill_to is not None:
                    grad_info["fillToRect"] = {k: int(fill_to.get(k, '0')) for k in ('l','t','r','b')}
                tile = grad.find('a:tileRect', _NS)
                if tile is not None:
                    grad_info["tileRect"] = {k: int(tile.get(k, '0')) for k in ('l','t','r','b')}
            else:
                grad_info["angle"] = 0
                grad_info["type"] = "linear"
            if grad.get('rotWithShape'):
                grad_info["rotWithShape"] = grad.get('rotWithShape') == '1'
            if grad.get('flip'):
                grad_info["flip"] = grad.get('flip')
            result["lineGradient"] = grad_info
        return result
    # solidFill
    solid = ln.find('a:solidFill', _NS)
    if solid is not None:
        srgb = solid.find('a:srgbClr', _NS)
        scheme = solid.find('a:schemeClr', _NS)
        if srgb is not None:
            result["line"] = _hex(srgb)
        elif scheme is not None:
            resolved = _resolve_color_with_transforms(scheme, theme_colors, color_mapping)
            if resolved:
                result["line"] = resolved
    if "line" not in result and "lineGradient" not in result:
        # Only set none if ln has noFill; otherwise leave unset for style resolution
        if ln.find('a:noFill', _NS) is not None:
            result["line"] = "none"
    return result

def parse_gradient_from_style(fill_style_xml, theme_colors, placeholder_color=None):
    """Parse gradient from theme fill style XML."""
    if not fill_style_xml:
        return None
    try:
        fill_elem = ET.fromstring(fill_style_xml)
        
        if fill_elem.tag.endswith('gradFill'):
            grad_fill = fill_elem
        else:
            grad_fill = fill_elem.find('.//a:gradFill', _NS)
        
        if grad_fill is None:
            return None
        
        gradient = {"stops": [], "angle": 0}
        
        gs_lst = grad_fill.find('.//a:gsLst', _NS)
        if gs_lst is not None:
            for gs in gs_lst.findall('.//a:gs', _NS):
                pos = int(gs.get('pos', 0)) / 100000.0
                
                color = "#000000"
                scheme_clr = gs.find('.//a:schemeClr', _NS)
                if scheme_clr is not None:
                    clr_val = scheme_clr.get('val')
                    if clr_val == 'phClr':
                        if placeholder_color and placeholder_color in theme_colors:
                            color = theme_colors[placeholder_color]
                        else:
                            color = theme_colors.get('dk1', '#000000')
                    elif clr_val in theme_colors:
                        color = theme_colors[clr_val]
                    
                    transforms = {}
                    transform_order = ['lumMod', 'lumOff', 'satMod', 'satOff', 'tint', 'shade']
                    for tag_name in transform_order:
                        for child in scheme_clr:
                            tag = child.tag.split('}')[-1]
                            if tag == tag_name:
                                transforms[tag] = child.get('val')
                                break
                    
                    if transforms:
                        color = apply_color_transforms(color, transforms)
                
                gradient["stops"].append({"position": pos, "color": color})
        
        return gradient
    except (ET.ParseError, Exception):
        return None


def _extract_visual_effects(sp_pr, theme_colors=None, color_mapping=None):
    """Extract effects + 3D from spPr. Returns merged dict."""
    result = _extract_effects_from_xml(sp_pr, theme_colors, color_mapping)
    result.update(_extract_3d_from_xml(sp_pr))
    return result
