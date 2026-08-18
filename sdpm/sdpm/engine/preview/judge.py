# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layout quality judgments from LibreOffice SVG export.

Detects rendered-layout defects that declared values cannot reveal
(see the scope note in sdpm.engine.schema.lint — lint checks declarations,
this module checks rendering results):

- J1 collision: two text elements overlap on screen
- J2 overflow:  text extends beyond its host shape's fill
- J3 contrast:  text is unreadable against its resolved background

All thresholds are calibrated against the official reference decks
(components.pptx / patterns.pptx) rendered with LibreOffice — zero
false positives there is a hard requirement. When uncertain
(gradients, images), judgments are skipped rather than guessed.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"

_EXCLUDE_CLASSES = {"DateTime", "Footer", "PageNumber", "Header"}
_NUM_RE = re.compile(r"[-+]?\d*\.?\d+")

# Text bbox coefficients (fraction of font-size above/below the baseline).
# Loose covers the full glyph area (overflow/contrast); tight approximates
# cap-height so standard title/subtitle line spacing does not register as
# a collision.
_LOOSE_ASC, _LOOSE_DESC = 0.80, 0.25
_TIGHT_ASC, _TIGHT_DESC = 0.70, 0.05

# J1: flag when intersection exceeds this fraction of the smaller text bbox
_COLLISION_MIN_COVERAGE = 0.10
# J1: same text within this distance (viewBox units) = double-draw highlight
_DUPLICATE_POS_TOL = 10.0
# J2: em-box estimates overshoot real glyph extents (digits have no
# descenders), so require overflow beyond this fraction of font-size
_OVERFLOW_TOL_EM = 0.20
# J3: below this WCAG ratio text is genuinely unreadable. Intentionally under
# WCAG AA (3.0): the official reference uses white-on-AWS-orange (2.1) as a
# brand standard; real accidents (dark-on-dark, white-on-white) are < 1.5.
_CONTRAST_MIN_RATIO = 1.8
# J3: a fill must cover this fraction of the text bbox to count as background
_BG_MIN_COVERAGE = 0.50


@dataclass
class JudgeIssue:
    """One rendered-layout defect on a slide."""

    kind: str  # "collision" | "overflow" | "contrast"
    message: str


@dataclass
class _Text:
    loose: tuple  # (x0, y0, x1, y1) full glyph bbox
    tight: tuple  # cap-height bbox for collision checks
    rgb: tuple | None
    preview: str
    shape_extent: tuple | None  # host shape's fill extent, if any
    font_size: float


def _path_extent(d: str) -> tuple | None:
    """Min/max x,y over all coordinates in a path d attribute."""
    nums = [float(n) for n in _NUM_RE.findall(d)]
    if len(nums) < 4:
        return None
    xs, ys = nums[0::2], nums[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def _text_lines(text_el) -> list[tuple]:
    """Per-line render metrics: (x, y_baseline, width, font_size, fill)."""
    lines = []
    for tp in text_el.findall(f".//{{{SVG_NS}}}tspan[@class='TextPosition']"):
        x = float(tp.get("x", "0"))
        y = float(tp.get("y", "0"))
        w = 0.0
        fs = 0.0
        fill = None
        for row in tp.findall(f"{{{SVG_NS}}}tspan"):
            tl = row.get("textLength")
            if tl:
                w += float(tl)
            m = _NUM_RE.search(row.get("font-size", ""))
            if m:
                fs = max(fs, float(m.group()))
            if fill is None:
                fill = row.get("fill")
        if w > 0:
            lines.append((x, y, w, fs, fill))
    return lines


def _text_bbox(lines: list[tuple], asc: float, desc: float) -> tuple | None:
    if not lines:
        return None
    x0 = min(ln[0] for ln in lines)
    x1 = max(ln[0] + ln[2] for ln in lines)
    y0 = min(ln[1] - asc * ln[3] for ln in lines)
    y1 = max(ln[1] + desc * ln[3] for ln in lines)
    return x0, y0, x1, y1


def _parse_rgb(s: str | None) -> tuple | None:
    if not s:
        return None
    m = re.match(r"rgb\((\d+),(\d+),(\d+)\)", s)
    if m:
        return tuple(int(v) for v in m.groups())
    m = re.match(r"#([0-9a-fA-F]{6})", s)
    if m:
        h = m.group(1)
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    return None


def _composite(fg: tuple, alpha: float, bg: tuple | None) -> tuple:
    """Alpha-composite a translucent fill over the slide background."""
    if bg is None:
        return fg
    return tuple(round(f * alpha + b * (1 - alpha)) for f, b in zip(fg, bg))


def _rel_lum(rgb: tuple) -> float:
    def ch(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple, b: tuple) -> float:
    la, lb = _rel_lum(a), _rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _overlap(a: tuple, b: tuple) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def _area(b: tuple) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _in_shadow_group(el, stop) -> bool:
    """True if el sits under a reduced-opacity group (LibreOffice shadows)."""
    anc = el.getparent()
    while anc is not None and anc is not stop:
        style = anc.get("style", "")
        if "opacity" in style and "opacity: 1" not in style:
            return True
        anc = anc.getparent()
    return False


def _collect(page_g, slide_bg):
    """Extract text elements and background-fill candidates from a Page group."""
    texts: list[_Text] = []
    fills: list[tuple] = []  # (extent, rgb_or_None); None rgb = gradient/unknown

    for shape_g in page_g:
        if shape_g.tag != f"{{{SVG_NS}}}g":
            continue
        if shape_g.get("class", "") in _EXCLUDE_CLASSES:
            continue

        shape_extent = None
        fill_rgb = None
        fill_known = True
        for p in shape_g.iter(f"{{{SVG_NS}}}path"):
            f = p.get("fill")
            # Gradient fills appear as style="fill:url(#…)" or fill="url(#…)"
            # depending on the LibreOffice version — treat both as unknown-
            # color background (never fall through to the slide background,
            # which fabricates white-on-white false positives).
            is_gradient = "fill:url(" in p.get("style", "") or (f or "").startswith("url(")
            if (not f or f == "none") and not is_gradient:
                continue  # stroke-only path (borders)
            if _in_shadow_group(p, shape_g):
                continue
            ext = _path_extent(p.get("d", ""))
            if ext is None:
                continue
            if shape_extent is None:
                shape_extent = ext
            else:
                shape_extent = (
                    min(shape_extent[0], ext[0]),
                    min(shape_extent[1], ext[1]),
                    max(shape_extent[2], ext[2]),
                    max(shape_extent[3], ext[3]),
                )
            if is_gradient:
                fill_known = False
                fill_rgb = None
            else:
                rgb = _parse_rgb(f)
                if rgb:
                    fo = p.get("fill-opacity")
                    if fo is not None:
                        rgb = _composite(rgb, float(fo), slide_bg)
                    fill_rgb = rgb
        if shape_extent and (fill_rgb or not fill_known):
            fills.append((shape_extent, fill_rgb if fill_known else None))

        text_el = shape_g.find(f".//{{{SVG_NS}}}text[@class='SVGTextShape']")
        if text_el is None:
            continue
        lines = _text_lines(text_el)
        loose = _text_bbox(lines, _LOOSE_ASC, _LOOSE_DESC)
        if loose is None:
            continue
        texts.append(
            _Text(
                loose=loose,
                tight=_text_bbox(lines, _TIGHT_ASC, _TIGHT_DESC),
                rgb=_parse_rgb(lines[0][4]),
                preview="".join(text_el.itertext()).strip()[:25],
                shape_extent=shape_extent,
                font_size=max(ln[3] for ln in lines),
            )
        )
    return texts, fills


def _judge_collisions(texts: list[_Text]) -> list[JudgeIssue]:
    issues = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            ti, tj = texts[i], texts[j]
            # Single-glyph decorations (❝, arrows) overlay text intentionally
            if len(ti.preview) <= 1 or len(tj.preview) <= 1:
                continue
            a, b = ti.tight, tj.tight
            # Same string drawn twice at the same position is the
            # highlight/emphasis double-draw pattern, rendered as one
            if ti.preview == tj.preview and all(
                abs(a[k] - b[k]) < _DUPLICATE_POS_TOL for k in range(4)
            ):
                continue
            ov = _overlap(a, b)
            if ov <= 0:
                continue
            cov = ov / min(_area(a), _area(b))
            if cov > _COLLISION_MIN_COVERAGE:
                issues.append(
                    JudgeIssue(
                        "collision",
                        f'text "{ti.preview}" overlaps "{tj.preview}" '
                        f"({cov:.0%} of the smaller text)",
                    )
                )
    return issues


def _judge_overflow(texts: list[_Text]) -> list[JudgeIssue]:
    issues = []
    for t in texts:
        ext = t.shape_extent
        if ext is None or t.font_size <= 0:
            continue
        tb = t.loose
        tol = _OVERFLOW_TOL_EM * t.font_size
        if (
            tb[0] < ext[0] - tol
            or tb[2] > ext[2] + tol
            or tb[1] < ext[1] - tol
            or tb[3] > ext[3] + tol
        ):
            issues.append(
                JudgeIssue("overflow", f'text "{t.preview}" extends beyond its shape')
            )
    return issues


def _judge_contrast(
    texts: list[_Text], fills: list[tuple], slide_bg: tuple | None
) -> list[JudgeIssue]:
    issues = []
    for t in texts:
        if t.rgb is None:
            continue
        tb = t.loose
        tb_area = _area(tb)
        if tb_area <= 0:
            continue
        best_cov, best_rgb = 0.0, None
        for fext, frgb in fills:
            cov = _overlap(tb, fext) / tb_area
            if cov > best_cov:
                best_cov, best_rgb = cov, frgb
        if best_cov > _BG_MIN_COVERAGE:
            if best_rgb is None:
                continue  # gradient/image underlay — contrast unknowable
            bg = best_rgb
        else:
            bg = slide_bg
        if bg is None:
            continue
        cr = contrast_ratio(t.rgb, bg)
        if cr < _CONTRAST_MIN_RATIO:
            issues.append(
                JudgeIssue(
                    "contrast",
                    f'text "{t.preview}" is unreadable: contrast {cr:.1f} '
                    f"(text rgb{t.rgb} on rgb{bg})",
                )
            )
    return issues


def _slide_background(root) -> tuple | None:
    """Resolve the master Background fill color, if a solid one exists."""
    for bg_g in root.iter(f"{{{SVG_NS}}}g"):
        if bg_g.get("class") == "Background":
            for el in bg_g.iter():
                rgb = _parse_rgb(el.get("fill"))
                if rgb:
                    return rgb
    return None


def judge_from_svg(
    svg_path: Path,
    slide_indices: list[int] | None = None,
) -> dict[int, list[JudgeIssue]]:
    """Run layout judgments on a LibreOffice SVG export.

    Args:
        svg_path: Path to LibreOffice SVG export.
        slide_indices: 1-based slide numbers to judge. None for all.

    Returns:
        Dict mapping slide number (1-based) to issues. Slides with no
        issues are omitted.
    """
    tree = etree.parse(str(svg_path))  # noqa: S320
    root = tree.getroot()
    slide_bg = _slide_background(root)

    slides_g = root.findall(f".//{{{SVG_NS}}}g[@class='Slide']")
    results: dict[int, list[JudgeIssue]] = {}

    for slide_num, slide_g in enumerate(slides_g):
        if slide_num == 0:  # Slide 0 is a dummy
            continue
        if slide_indices and slide_num not in slide_indices:
            continue
        page_g = slide_g.find(f"{{{SVG_NS}}}g[@class='Page']")
        if page_g is None:
            continue

        texts, fills = _collect(page_g, slide_bg)
        issues = (
            _judge_collisions(texts)
            + _judge_overflow(texts)
            + _judge_contrast(texts, fills, slide_bg)
        )
        if issues:
            results[slide_num] = issues

    return results
