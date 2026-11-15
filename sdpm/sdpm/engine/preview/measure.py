# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Measure text bounding boxes from LibreOffice SVG export."""

from dataclasses import dataclass
from pathlib import Path

from sdpm.utils import xml_safe

# Placeholder classes to exclude from measurement
_EXCLUDE_CLASSES = {"DateTime", "Footer", "PageNumber", "Header"}

SVG_NS = "http://www.w3.org/2000/svg"


@dataclass
class ElementBBox:
    """Bounding box measurement for a single element."""

    x_px: float = 0.0
    y_px: float = 0.0
    w_px: float = 0.0
    h_px: float = 0.0
    lines: int = 0
    text_preview: str = ""


def measure_from_svg(
    svg_path: Path,
    slide_indices: list[int] | None = None,
) -> dict[int, list[ElementBBox]]:
    """Parse SVG and extract text bboxes per slide.

    Args:
        svg_path: Path to LibreOffice SVG export.
        slide_indices: 1-based slide numbers to measure. None for all.

    Returns:
        Dict mapping slide number (1-based) to list of ElementBBox.
    """
    tree = xml_safe.parse(svg_path, allow_doctype=True)
    root = tree.getroot()

    # Read viewBox for coordinate conversion
    vb = root.get("viewBox", "").split()
    if len(vb) == 4:
        vb_w = float(vb[2])
    else:
        vb_w = 25400.0

    # Equal-aspect scale: SVG viewBox preserves the template's aspect ratio,
    # so a single width-based scale is correct for all aspect ratios.
    scale_x = scale_y = 1920.0 / vb_w

    # Find all Slide groups (skip index 0 = dummy)
    slides_g = root.findall(f".//{{{SVG_NS}}}g[@class='Slide']")
    results: dict[int, list[ElementBBox]] = {}

    for slide_idx_0, slide_g in enumerate(slides_g):
        slide_num = slide_idx_0  # Slide 0 is dummy, Slide 1 = real slide 1
        if slide_num == 0:
            continue
        if slide_indices and slide_num not in slide_indices:
            continue

        page_g = slide_g.find(f"{{{SVG_NS}}}g[@class='Page']")
        if page_g is None:
            continue

        bboxes: list[ElementBBox] = []

        for shape_g in page_g:
            if shape_g.tag != f"{{{SVG_NS}}}g":
                continue

            cls = shape_g.get("class", "")

            # Skip placeholders
            if cls in _EXCLUDE_CLASSES:
                continue

            # Must have text content
            text_el = shape_g.find(f".//{{{SVG_NS}}}text[@class='SVGTextShape']")
            if text_el is None:
                continue

            # Get BoundingBox rect (may be nested in sub-g)
            bbox_rect = shape_g.find(f".//{{{SVG_NS}}}rect[@class='BoundingBox']")
            if bbox_rect is None:
                continue

            bb_x = float(bbox_rect.get("x", "0"))
            bb_y = float(bbox_rect.get("y", "0"))
            bb_w = float(bbox_rect.get("width", "0"))
            bb_h = float(bbox_rect.get("height", "0"))

            # Count lines via TextPosition tspans
            text_positions = text_el.findall(
                f".//{{{SVG_NS}}}tspan[@class='TextPosition']"
            )
            line_count = len(text_positions)

            # Extract text preview
            text_preview = "".join(text_el.itertext()).replace("\n", " ").strip()[:20]

            bbox = ElementBBox(
                x_px=round(bb_x * scale_x, 1),
                y_px=round(bb_y * scale_y, 1),
                w_px=round(bb_w * scale_x, 1),
                h_px=round(bb_h * scale_y, 1),
                lines=line_count,
                text_preview=text_preview,
            )
            bboxes.append(bbox)

        if bboxes:
            results[slide_num] = bboxes

    return results


def format_measure_report(
    results: dict[int, list[ElementBBox]],
    page_to_slug: dict[int, str] | None = None,
    judgments: dict[int, list] | None = None,
) -> str:
    """Format measurement results as human-readable text.

    Args:
        results: Mapping of 1-based page number to element bboxes.
        page_to_slug: Optional mapping of page number to slug for slug-based labels.
        judgments: Optional mapping of page number to JudgeIssue lists
            (from sdpm.engine.preview.judge). Appended only when issues exist.
    """
    lines: list[str] = []
    lines.append("📐 Text measurement (actual rendered size):")
    for slide_num in sorted(results.keys()):
        label = page_to_slug.get(slide_num, str(slide_num)) if page_to_slug else str(slide_num)
        lines.append(f"Slide {label}:")
        for bbox in results[slide_num]:
            lines.append(f'  at ({bbox.x_px}, {bbox.y_px}) w={bbox.w_px} h={bbox.h_px} lines={bbox.lines} | "{bbox.text_preview}"')
    lines.append("Compare each h with your declared height. Large difference means text doesn't fit — adjust text content or width first.")
    lines.append("fontSize is a last resort — it carries semantic weight and affects readability.")
    lines.append("Use actual sizes to calibrate subsequent layout.")
    if judgments:
        lines.append("")
        lines.append("⚠ Layout issues (detected in actual rendering — fix these):")
        for slide_num in sorted(judgments.keys()):
            label = page_to_slug.get(slide_num, str(slide_num)) if page_to_slug else str(slide_num)
            for issue in judgments[slide_num]:
                lines.append(f"  Slide {label} [{issue.kind}]: {issue.message}")
    return "\n".join(lines)
