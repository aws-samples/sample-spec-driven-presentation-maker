# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Media extraction: video, pictures, SVG, image fills, referenced images."""
import sys
from pathlib import Path

from ..constants import _NS, _base_element, _add_flip, _hex
from ..xml_helpers import _extract_visual_effects

def extract_video_element(shape, output_dir=None, slide_idx=0, img_idx=0):
    """Extract video as element dict, saving video file and poster image."""
    from pptx.oxml.ns import qn as _qn
    elem = _base_element(shape, "video")
    try:
        r_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        nvPr = shape._element.find(f'{_qn("p:nvPicPr")}/{_qn("p:nvPr")}')
        if nvPr is None:
            return None
        videoFile = nvPr.find(_qn('a:videoFile'))
        if videoFile is None:
            return None

        # Save video file
        r_link = videoFile.get(f'{{{r_ns}}}link')
        if r_link and output_dir:
            slide_part = shape.part
            rel = slide_part.rels[r_link]
            ext = rel.target_ref.split('.')[-1] or 'mp4'
            video_name = f"slide{slide_idx+1}_video{img_idx+1}.{ext}"
            media_dir = Path(output_dir) / "media"
            media_dir.mkdir(exist_ok=True)
            # Get blob via p14:media embed (more reliable)
            p14_ns = 'http://schemas.microsoft.com/office/powerpoint/2010/main'
            media_el = nvPr.find(f'.//{{{p14_ns}}}media')
            if media_el is not None:
                r_embed = media_el.get(f'{{{r_ns}}}embed')
                if r_embed:
                    (media_dir / video_name).write_bytes(slide_part.rels[r_embed].target_part.blob)
            elem["src"] = f"media/{video_name}"

        # Save poster image
        blip = shape._element.find(f'{_qn("p:blipFill")}/{_qn("a:blip")}')
        if blip is not None and output_dir:
            r_embed = blip.get(f'{{{r_ns}}}embed')
            if r_embed:
                poster_part = shape.part.rels[r_embed].target_part
                poster_ext = poster_part.content_type.split('/')[-1].replace('jpeg', 'jpg')
                poster_name = f"slide{slide_idx+1}_poster{img_idx+1}.{poster_ext}"
                images_dir = Path(output_dir) / "images"
                images_dir.mkdir(exist_ok=True)
                (images_dir / poster_name).write_bytes(poster_part.blob)
                elem["poster"] = f"images/{poster_name}"
    except Exception as e:
        print(f"Warning: Failed to extract video: {e}", file=sys.stderr)
    return elem


def _image_ext(part):
    """File extension for an image part, derived from its content type."""
    return part.content_type.split('/')[-1].replace('jpeg', 'jpg').replace('svg+xml', 'svg')


def _save_image_part(part, output_dir, filename):
    """Write an image part's blob under {output_dir}/images/. Returns deck-relative path."""
    images_dir = Path(output_dir) / "images"
    images_dir.mkdir(exist_ok=True)
    (images_dir / filename).write_bytes(part.blob)
    return f"images/{filename}"


def _save_referenced_images(shape, output_dir, slide_idx, img_counter, prefix):
    """Save every image part referenced (r:embed / r:link) inside a shape's XML.

    Used when raw XML is re-injected on rebuild (rawShape _shapeXml / group
    _groupXml): without the returned rId → deck-relative-path mapping the
    injected XML carries dangling r:embed ids and its pictures vanish.

    Returns (rid_map, img_counter).
    """
    rid_map = {}
    if output_dir is None:
        return rid_map, img_counter
    for el_ref in shape._element.iter():
        rid = el_ref.get(f'{{{_NS["r"]}}}embed') or el_ref.get(f'{{{_NS["r"]}}}link')
        if not rid or rid in rid_map:
            continue
        try:
            part = shape.part.rels[rid].target_part
            fname = f"slide{slide_idx + 1}_{prefix}{img_counter + 1}_{rid}.{_image_ext(part)}"
            rid_map[rid] = _save_image_part(part, output_dir, fname)
            img_counter += 1
        except Exception:
            continue
    return rid_map, img_counter


def _extract_svg_blob(shape):
    """Extract SVG bytes from asvg:svgBlip if present. Returns bytes or None."""
    ASVG_NS = 'http://schemas.microsoft.com/office/drawing/2016/SVG/main'
    svg_blip = shape._element.find(f'.//{{{ASVG_NS}}}svgBlip')
    if svg_blip is None:
        return None
    r_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    r_embed = svg_blip.get(f'{{{r_ns}}}embed')
    if not r_embed:
        return None
    try:
        part = shape.part.rels[r_embed].target_part
        return part.blob
    except (KeyError, Exception):
        return None


def extract_picture_element(shape, output_dir=None, slide_idx=0, img_idx=0, theme_colors=None, color_mapping=None):
    """Extract picture as element dict and save image file."""
    elem = _base_element(shape, "image")
    
    # Check for SVG (asvg:svgBlip)
    svg_bytes = _extract_svg_blob(shape)
    if svg_bytes is not None:
        # PowerPoint crops via blipFill srcRect; SVG frames lose it in the
        # builder path, so bake the crop into the viewBox instead.
        src_rect = shape._element.find(
            f'{{{_NS["p"]}}}blipFill/{{{_NS["a"]}}}srcRect')
        if src_rect is not None:
            try:
                from lxml import etree as _et
                root = _et.fromstring(svg_bytes)
                vb = root.get('viewBox')
                if vb:
                    mx, my, vw, vh = [float(v) for v in vb.replace(',', ' ').split()]
                    pct = {k: int(src_rect.get(k, '0')) / 100000 for k in ('l', 't', 'r', 'b')}
                    if any(pct.values()) and vw > 0 and vh > 0:
                        nx = mx + pct['l'] * vw
                        ny = my + pct['t'] * vh
                        nw = vw * (1 - pct['l'] - pct['r'])
                        nh = vh * (1 - pct['t'] - pct['b'])
                        if nw > 0 and nh > 0:
                            root.set('viewBox', f'{nx:g} {ny:g} {nw:g} {nh:g}')
                            svg_bytes = _et.tostring(root)
            except Exception:
                pass
        if output_dir:
            images_dir = Path(output_dir) / "images"
            images_dir.mkdir(exist_ok=True)
            filename = f"slide{slide_idx + 1}_image{img_idx + 1}.svg"
            (images_dir / filename).write_bytes(svg_bytes)
            elem["src"] = f"images/{filename}"
        # Imported artwork keeps its own colors — opt out of the builder's
        # theme-icon recolor (which repainted e.g. green wave shapes black).
        elem["iconColor"] = "none"
        _add_flip(elem, shape)
        elem["fit"] = "stretch"
        return elem
    
    # Save image to file
    if output_dir:
        try:
            image = shape.image
            image_bytes = image.blob
            
            # Determine format
            ext = shape.image.ext or "png"
            
            # Create images directory
            images_dir = Path(output_dir) / "images"
            images_dir.mkdir(exist_ok=True)
            
            # Save image
            image_filename = f"slide{slide_idx + 1}_image{img_idx + 1}.{ext}"
            image_path = images_dir / image_filename
            
            with open(image_path, 'wb') as f:
                f.write(image_bytes)
            
            # Store relative path
            elem["src"] = f"images/{image_filename}"
        except Exception as e:
            print(f"Warning: Failed to save image: {e}", file=sys.stderr)
    
    # Extract hyperlink
    if hasattr(shape, 'click_action') and shape.click_action.hyperlink:
        elem["link"] = shape.click_action.hyperlink.address

    # Mirrored pictures (flipH/flipV) — without this a cutout photo shows
    # its subject on the wrong side of the frame.
    _add_flip(elem, shape)

    # PowerPoint's <a:stretch><a:fillRect/> fills the frame exactly,
    # distorting aspect if needed. The builder default (contain) would
    # shrink e.g. a full-width wave band into a left-anchored blob.
    elem["fit"] = "stretch"
    
    # Extract image effects into _originalEffects (underscore-prefixed so builder
    # ignores them by default).  When reusing images in new slides, agents should
    # NOT copy _originalEffects — this prevents unintended mask/crop/color changes.
    # To faithfully reproduce the original slide, spread _originalEffects into the
    # element: { ...elem, ...elem._originalEffects }.
    try:
        effects: dict = {}
        pic_el = shape._element
        sp_pr = pic_el.find(f'{{{_NS["p"]}}}spPr')
        if sp_pr is not None:
            # Mask (prstGeom != rect)
            prst_geom = sp_pr.find(f'{{{_NS["a"]}}}prstGeom')
            if prst_geom is not None:
                prst = prst_geom.get('prst')
                mask_rmap = {"ellipse": "circle", "roundRect": "rounded_rectangle", "hexagon": "hexagon", "diamond": "diamond", "triangle": "triangle", "pentagon": "pentagon", "star5": "star_5_point", "heart": "heart", "trapezoid": "trapezoid"}
                if prst and prst != 'rect':
                    # Friendly name when we have one; otherwise pass the raw
                    # OOXML preset through (builder replays unknown presets
                    # verbatim — e.g. round1Rect, snip2SameRect).
                    effects["mask"] = mask_rmap.get(prst, prst)
                    av_lst = prst_geom.find(f'{{{_NS["a"]}}}avLst')
                    if av_lst is not None:
                        adjs = []
                        for gd in av_lst.findall(f'{{{_NS["a"]}}}gd'):
                            fmla = gd.get('fmla', '')
                            if fmla.startswith('val '):
                                raw = int(fmla.split()[1])
                                # roundRect JSON semantics are 0–1 of full
                                # rounding (builder writes *50000); other
                                # presets carry the raw fraction (*100000).
                                adjs.append(raw / 50000 if prst == 'roundRect' else raw / 100000)
                        if adjs:
                            effects["maskAdjustments"] = adjs
            # Visual effects
            effects.update(_extract_visual_effects(sp_pr, theme_colors, color_mapping))

        blip_fill = pic_el.find(f'{{{_NS["p"]}}}blipFill')
        if blip_fill is not None:
            # Crop
            src_rect = blip_fill.find(f'{{{_NS["a"]}}}srcRect')
            if src_rect is not None:
                crop = {}
                for side in ('l', 't', 'r', 'b'):
                    v = src_rect.get(side)
                    if v and int(v) != 0:
                        key = {"l": "left", "t": "top", "r": "right", "b": "bottom"}[side]
                        crop[key] = int(v) / 1000
                if crop:
                    effects["crop"] = crop
            # Brightness/Contrast/Saturation
            blip = blip_fill.find(f'{{{_NS["a"]}}}blip')
            if blip is not None:
                lum = blip.find(f'{{{_NS["a"]}}}lum')
                if lum is not None:
                    b = lum.get('bright')
                    c = lum.get('contrast')
                    if b:
                        effects["brightness"] = round(int(b) / 1000)
                    if c:
                        effects["contrast"] = round(int(c) / 1000)
                sat = blip.find(f'{{{_NS["a"]}}}hsl')
                if sat is not None:
                    v = sat.get('sat')
                    if v:
                        effects["saturation"] = round(int(v) / 1000)
                duo = blip.find(f'{{{_NS["a"]}}}duotone')
                if duo is not None:
                    colors = []
                    for srgb in duo.findall(f'{{{_NS["a"]}}}srgbClr'):
                        colors.append(_hex(srgb))
                    if len(colors) >= 2:
                        effects["duotone"] = colors[:2]
                # Preserve blip effects XML for lossless roundtrip (biLevel, etc.)
                from lxml import etree as _et
                blip_effects = []
                for child in blip:
                    tag = child.tag.split('}')[-1]
                    if tag in ('biLevel', 'grayscl', 'clrChange', 'clrRepl'):
                        blip_effects.append(_et.tostring(child, encoding='unicode'))
                if blip_effects:
                    effects["_blipEffects"] = blip_effects
        if effects:
            elem["_originalEffects"] = effects
    except Exception:
        pass
    
    return elem

def _extract_blipfill_image(shape, output_dir, slide_idx, img_counter):
    """Picture-filled shape/textbox (spPr>blipFill) → image element.

    PowerPoint allows any shape to be filled with a picture. The builder has
    no image-fill support, so a text-less picture-filled shape is best
    reproduced as a plain image element with the same geometry. Returns the
    element or None (has text / no blipFill / extraction failed).
    """
    try:
        if shape.has_text_frame and shape.text_frame.text.strip():
            return None
        sp_pr = shape._element.spPr
        blip_fill = sp_pr.find(f'{{{_NS["a"]}}}blipFill') if sp_pr is not None else None
        if blip_fill is None:
            return None
        blip = blip_fill.find(f'{{{_NS["a"]}}}blip')
        if blip is None:
            return None
        r_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        rid = blip.get(f'{{{r_ns}}}embed')
        is_svg = False
        if rid is None:
            svg_blip = blip.find(
                './/{http://schemas.microsoft.com/office/drawing/2016/SVG/main}svgBlip')
            if svg_blip is not None:
                rid = svg_blip.get(f'{{{r_ns}}}embed')
                is_svg = True
        if rid is None or output_dir is None:
            return None
        part = shape.part.rels[rid].target_part
        ext = 'svg' if is_svg else _image_ext(part)
        filename = f"slide{slide_idx + 1}_image{img_counter + 1}.{ext}"
        elem = _base_element(shape, "image")
        elem["src"] = _save_image_part(part, output_dir, filename)
        elem["fit"] = "cover"
        if ext == 'svg':
            elem["iconColor"] = "none"
        elem.pop("fill", None)
        elem.pop("line", None)
        return elem
    except Exception:
        return None


