# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Image utilities: path resolution and image effects."""
from pathlib import Path

from sdpm.assets import resolve_asset_path


def resolve_image_path(src: str, theme: str = "light") -> Path:
    """Resolve image source to file path."""
    if src.startswith("icons:") or src.startswith("assets:"):
        return resolve_asset_path(src, theme)
    else:
        path = Path(src).expanduser().resolve()
        if ".." in Path(src).parts:
            raise ValueError(f"Path traversal not allowed: {src}")
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {src}")
        return path


def apply_image_effects(pic_element, elem_def):
    """Apply image-specific effects (crop, mask, brightness/contrast/saturation, duotone)."""
    from lxml import etree
    from pptx.oxml.ns import qn

    crop = elem_def.get("crop")
    mask = elem_def.get("mask")
    mask_adj = elem_def.get("maskAdjustments")
    brightness = elem_def.get("brightness")
    contrast = elem_def.get("contrast")
    saturation = elem_def.get("saturation")
    duotone = elem_def.get("duotone")
    blip_effects = elem_def.get("_blipEffects")

    if not any([crop, mask, brightness is not None, contrast is not None, saturation is not None, duotone, blip_effects]):
        return

    if crop:
        blip_fill = pic_element.find(qn('p:blipFill'))
        if blip_fill is None:
            blip_fill = pic_element.find(qn('pic:blipFill'))
        if blip_fill is not None:
            for sr in blip_fill.findall(qn('a:srcRect')):
                blip_fill.remove(sr)
            src_rect = etree.Element(qn('a:srcRect'))
            if crop.get("left"):
                src_rect.set('l', str(int(crop["left"] * 1000)))
            if crop.get("top"):
                src_rect.set('t', str(int(crop["top"] * 1000)))
            if crop.get("right"):
                src_rect.set('r', str(int(crop["right"] * 1000)))
            if crop.get("bottom"):
                src_rect.set('b', str(int(crop["bottom"] * 1000)))
            blip = blip_fill.find(qn('a:blip'))
            if blip is not None:
                blip.addnext(src_rect)
            else:
                blip_fill.insert(0, src_rect)

    if mask:
        sp_pr = pic_element.find(qn('p:spPr'))
        if sp_pr is None:
            sp_pr = pic_element.find(qn('pic:spPr'))
        if sp_pr is not None:
            for pg in sp_pr.findall(qn('a:prstGeom')):
                sp_pr.remove(pg)
            mask_map = {
                "circle": "ellipse", "oval": "ellipse", "ellipse": "ellipse",
                "rounded_rectangle": "roundRect", "roundRect": "roundRect",
                "hexagon": "hexagon", "triangle": "triangle",
                "diamond": "diamond", "pentagon": "pentagon",
                "star_5_point": "star5", "heart": "heart",
            }
            prst = mask_map.get(mask, mask)
            geom = etree.SubElement(sp_pr, qn('a:prstGeom'))
            geom.set('prst', prst)
            av_lst = etree.SubElement(geom, qn('a:avLst'))
            if mask_adj and prst == "roundRect":
                gd = etree.SubElement(av_lst, qn('a:gd'))
                gd.set('name', 'adj')
                gd.set('fmla', f'val {int(mask_adj[0] * 50000)}')

    if brightness is not None or contrast is not None:
        blip_fill = pic_element.find(qn('p:blipFill'))
        if blip_fill is None:
            blip_fill = pic_element.find(qn('pic:blipFill'))
        if blip_fill is not None:
            blip = blip_fill.find(qn('a:blip'))
            if blip is not None:
                for lum in blip.findall(qn('a:lum')):
                    blip.remove(lum)
                lum = etree.SubElement(blip, qn('a:lum'))
                if brightness is not None:
                    lum.set('bright', str(int(brightness * 1000)))
                if contrast is not None:
                    lum.set('contrast', str(int(contrast * 1000)))

    if saturation is not None:
        blip_fill = pic_element.find(qn('p:blipFill'))
        if blip_fill is None:
            blip_fill = pic_element.find(qn('pic:blipFill'))
        if blip_fill is not None:
            blip = blip_fill.find(qn('a:blip'))
            if blip is not None:
                for hsl in blip.findall(qn('a:hsl')):
                    blip.remove(hsl)
                hsl = etree.SubElement(blip, qn('a:hsl'))
                hsl.set('sat', str(int(saturation * 1000)))

    if duotone and isinstance(duotone, list) and len(duotone) >= 2:
        blip_fill = pic_element.find(qn('p:blipFill'))
        if blip_fill is None:
            blip_fill = pic_element.find(qn('pic:blipFill'))
        if blip_fill is not None:
            blip = blip_fill.find(qn('a:blip'))
            if blip is not None:
                for dt in blip.findall(qn('a:duotone')):
                    blip.remove(dt)
                duo = etree.SubElement(blip, qn('a:duotone'))
                for color in duotone[:2]:
                    srgb = etree.SubElement(duo, qn('a:srgbClr'))
                    srgb.set('val', color.lstrip("#"))

    if blip_effects:
        blip_fill = pic_element.find(qn('p:blipFill'))
        if blip_fill is None:
            blip_fill = pic_element.find(qn('pic:blipFill'))
        if blip_fill is not None:
            blip = blip_fill.find(qn('a:blip'))
            if blip is not None:
                for effect_xml in blip_effects:
                    effect_el = etree.fromstring(effect_xml)
                    blip.insert(0, effect_el)
