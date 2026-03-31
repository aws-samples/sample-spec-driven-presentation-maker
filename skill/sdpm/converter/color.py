# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Color extraction and resolution."""
import colorsys
import defusedxml
defusedxml.defuse_stdlib()

import sys
import xml.etree.ElementTree as ET

import zipfile


from .constants import _NS

_THEME_ENUM_TO_NAME = {
    1: 'lt1', 2: 'dk1', 3: 'lt2', 4: 'dk2',
    5: 'accent1', 6: 'accent2', 7: 'accent3', 8: 'accent4',
    9: 'accent5', 10: 'accent6', 13: 'tx1', 14: 'bg1'
}

def extract_text_color(run, theme_colors=None, color_mapping=None, is_placeholder=False):
    """Extract text color from run, converting theme colors to RGB.
    Returns None for scheme colors that map to the default text role (tx1)."""
    try:
        if run.font.color and run.font.color.type == 1:  # RGB
            rgb = run.font.color.rgb
            return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        elif run.font.color and run.font.color.type == 2:  # SCHEME
            from pptx.oxml.ns import qn
            rPr = run._r.find(qn('a:rPr'))
            if rPr is not None:
                scheme_el = rPr.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}schemeClr')
                if scheme_el is not None:
                    scheme_val = scheme_el.get('val')
                    # Skip if this is the default text color role (unless placeholder with custom lstStyle)
                    tx1_ref = color_mapping.get('tx1', 'dk1') if color_mapping else 'dk1'
                    if scheme_val in ('tx1', tx1_ref) and not is_placeholder:
                        has_transforms = scheme_el.find(f'{{{_NS["a"]}}}lumMod') is not None or scheme_el.find(f'{{{_NS["a"]}}}lumOff') is not None
                        if not has_transforms:
                            return None
                    resolved = _resolve_color_with_transforms(scheme_el, theme_colors, color_mapping)
                    if resolved:
                        return resolved
            color_name = _THEME_ENUM_TO_NAME.get(run.font.color.theme_color)
            if color_name:
                tx1_ref = color_mapping.get('tx1', 'dk1') if color_mapping else 'dk1'
                if color_name in ('tx1', tx1_ref) and not is_placeholder:
                    return None
                resolved = _resolve_scheme_color(color_name, theme_colors, color_mapping)
                if resolved:
                    return resolved
            if theme_colors and run.font.color.theme_color in theme_colors:
                return theme_colors[run.font.color.theme_color]
            return "#000000"
        elif run.font.color is None or run.font.color.type is None:
            if is_placeholder:
                return None
            if color_mapping:
                tx1_mapped = color_mapping.get('tx1', 'dk1')
                if theme_colors and tx1_mapped in theme_colors:
                    return theme_colors[tx1_mapped]
            return None
    except Exception:
        pass
    return None

def extract_theme_colors_and_mapping(pptx_path, slide_master_idx):
    """Extract actual RGB values from theme file and color mapping."""
    theme_colors = {}
    color_mapping = {}
    theme_styles = {"fill": [], "line": []}
    
    try:
        with zipfile.ZipFile(pptx_path, 'r') as zip_ref:
            # Read appropriate theme file for this master
            theme_file = f'ppt/theme/theme{slide_master_idx + 1}.xml'
            theme_xml = zip_ref.read(theme_file)
            root = ET.fromstring(theme_xml)
            
            # Extract color scheme
            clr_scheme = root.find('.//a:clrScheme', _NS)
            if clr_scheme is not None:
                color_map = {
                    'dk1': 2,      # TEXT_1
                    'lt1': 1,      # BACKGROUND_1
                    'dk2': 4,      # TEXT_2
                    'lt2': 3,      # BACKGROUND_2
                    'accent1': 5,
                    'accent2': 6,
                    'accent3': 7,
                    'accent4': 8,
                    'accent5': 9,
                    'accent6': 10,
                }
                
                for color_name, theme_id in color_map.items():
                    color_elem = clr_scheme.find(f'.//a:{color_name}', _NS)
                    if color_elem is not None:
                        srgb = color_elem.find('.//a:srgbClr', _NS)
                        sys_clr = color_elem.find('.//a:sysClr', _NS)
                        if srgb is not None:
                            rgb_val = srgb.get('val')
                            theme_colors[color_name] = f"#{rgb_val}"
                            theme_colors[theme_id] = f"#{rgb_val}"
                        elif sys_clr is not None:
                            last = sys_clr.get('lastClr')
                            if last:
                                theme_colors[color_name] = f"#{last}"
                                theme_colors[theme_id] = f"#{last}"
                
                # Add variant for BACKGROUND_1
                if 1 in theme_colors:
                    theme_colors[14] = theme_colors[1]
            
            # Extract fill styles as raw XML strings
            fill_style_lst = root.find('.//a:fillStyleLst', _NS)
            if fill_style_lst is not None:
                for fill_elem in fill_style_lst:
                    theme_styles["fill"].append(ET.tostring(fill_elem, encoding='unicode'))
            
            # Extract line styles as raw XML strings
            ln_style_lst = root.find('.//a:lnStyleLst', _NS)
            if ln_style_lst is not None:
                for ln_elem in ln_style_lst:
                    theme_styles["line"].append(ET.tostring(ln_elem, encoding='unicode'))
            
            # Read slide master color mapping
            master_file = f'ppt/slideMasters/slideMaster{slide_master_idx + 1}.xml'
            master_xml = zip_ref.read(master_file)
            master_root = ET.fromstring(master_xml)
            
            clr_map = master_root.find('.//p:clrMap', _NS)
            if clr_map is not None:
                # Extract mapping (e.g., bg1="dk1" means bg1 maps to dk1)
                for attr in ['bg1', 'tx1', 'bg2', 'tx2']:
                    mapped_to = clr_map.get(attr)
                    if mapped_to:
                        color_mapping[attr] = mapped_to
                        
    except Exception as e:
        print(f"Warning: Could not extract theme colors: {e}", file=sys.stderr)
    
    return theme_colors, color_mapping, theme_styles

def _resolve_scheme_color(val, theme_colors, color_mapping):
    """Resolve scheme color name (from XML schemeClr val) to RGB hex."""
    if color_mapping and val in color_mapping:
        mapped = color_mapping[val]
        if theme_colors and mapped in theme_colors:
            return theme_colors[mapped]
    if theme_colors and val in theme_colors:
        return theme_colors[val]
    name_to_id = {'lt1': 1, 'dk1': 2, 'lt2': 3, 'dk2': 4,
                  'accent1': 5, 'accent2': 6, 'accent3': 7, 'accent4': 8,
                  'accent5': 9, 'accent6': 10, 'tx1': 13, 'bg1': 14, 'tx2': 4, 'bg2': 3}
    tid = name_to_id.get(val)
    if tid and theme_colors and tid in theme_colors:
        return theme_colors[tid]
    fallback = {'lt1': "#FFFFFF", 'dk1': "#000000", 'lt2': "#F3F3F7", 'dk2': "#161D26",
                'accent1': "#41B3FF", 'accent2': "#AD5CFF", 'accent3': "#00E500",
                'accent4': "#FF5C85", 'accent5': "#FF693C", 'accent6': "#FBD332",
                'tx1': "#000000", 'bg1': "#FFFFFF", 'tx2': "#161D26", 'bg2': "#F3F3F7"}
    return fallback.get(val)


# ── Common XML-level extraction helpers ──────────────────────────────────

def _resolve_color_with_transforms(scheme_el, theme_colors, color_mapping, override_scheme=None):
    """Resolve a schemeClr element including lumMod/lumOff/tint/shade transforms."""
    scheme_val = override_scheme if override_scheme and scheme_el.get('val') == 'phClr' else scheme_el.get('val')
    resolved = _resolve_scheme_color(scheme_val, theme_colors, color_mapping)
    if not resolved:
        return None
    lum_mod = scheme_el.find('a:lumMod', _NS)
    lum_off = scheme_el.find('a:lumOff', _NS)
    shade = scheme_el.find('a:shade', _NS)
    tint = scheme_el.find('a:tint', _NS)
    if lum_mod is not None or lum_off is not None or shade is not None or tint is not None:
        hx = resolved.lstrip('#')
        r, g, b = int(hx[0:2], 16) / 255, int(hx[2:4], 16) / 255, int(hx[4:6], 16) / 255
        # shade: darken toward black (in linear space)
        if shade is not None:
            f = int(shade.get('val')) / 100000
            r, g, b = pow(r, 2.2) * f, pow(g, 2.2) * f, pow(b, 2.2) * f
            r, g, b = pow(max(0,r), 1/2.2), pow(max(0,g), 1/2.2), pow(max(0,b), 1/2.2)
        # tint: lighten toward white (in linear space)
        if tint is not None:
            f = int(tint.get('val')) / 100000
            rl, gl, bl = pow(r, 2.2), pow(g, 2.2), pow(b, 2.2)
            rl, gl, bl = rl + (1-rl)*(1-f), gl + (1-gl)*(1-f), bl + (1-bl)*(1-f)
            r, g, b = pow(max(0,rl), 1/2.2), pow(max(0,gl), 1/2.2), pow(max(0,bl), 1/2.2)
        # lumMod/lumOff
        if lum_mod is not None or lum_off is not None:
            h, lum, s = colorsys.rgb_to_hls(r, g, b)
            if lum_mod is not None:
                lum *= int(lum_mod.get('val')) / 100000
            if lum_off is not None:
                lum += int(lum_off.get('val')) / 100000
            lum = min(1.0, max(0.0, lum))
            r, g, b = colorsys.hls_to_rgb(h, lum, s)
        r, g, b = min(1.0, max(0.0, r)), min(1.0, max(0.0, g)), min(1.0, max(0.0, b))
        resolved = f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"
    return resolved

def apply_color_transforms(base_color_hex, transforms):
    """Apply color transforms (lumMod, tint) to a base color."""
    hex_color = base_color_hex.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    
    has_lum_mod = 'lumMod' in transforms
    has_tint = 'tint' in transforms
    
    if has_lum_mod and has_tint:
        lum_mod_val = int(transforms['lumMod']) / 100000.0
        tint_val = int(transforms['tint']) / 100000.0
        effective_tint = tint_val / lum_mod_val
        
        r = int(round(r + ((255 - r) * effective_tint)))
        g = int(round(g + ((255 - g) * effective_tint)))
        b = int(round(b + ((255 - b) * effective_tint)))
    
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    
    return f"#{r:02X}{g:02X}{b:02X}"

def _apply_tint(hex_color, tint_factor):
    """Apply tint (mix with white) to a hex color."""
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    r = int(r + (255 - r) * (1 - tint_factor))
    g = int(g + (255 - g) * (1 - tint_factor))
    b = int(b + (255 - b) * (1 - tint_factor))
    return f"#{r:02X}{g:02X}{b:02X}"

def _apply_shade(hex_color, shade_factor):
    """Apply shade (mix with black) to a hex color."""
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    r = int(r * shade_factor)
    g = int(g * shade_factor)
    b = int(b * shade_factor)
    return f"#{r:02X}{g:02X}{b:02X}"
