# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""sdpm.engine — pure json <-> pptx conversion.

Subpackages:
- builder:   JSON spec -> PPTX construction
- converter: PPTX -> JSON spec extraction
- layout:    placement / routing / refinement for diagram layouts
- schema:    slide spec validation and lint
- preview:   PDF/PNG rendering, measurement, layout judging
- checks:    post-build quality checks
- diff:      deck diffing (roundtrip based)
- analyzer:  template analysis
"""

# ── Canvas derivation helpers ──
# Width is always 1920 px (design invariant D1). Height and EMU scale
# are derived from the template's physical slide dimensions.

_CANVAS_WIDTH_PX = 1920


def emu_per_px(slide_width_emu: int) -> float:
    """Derive EMU-per-px scale from the slide width in EMU.

    The canvas is always 1920 px wide; this function returns the
    EMU-per-pixel ratio for that basis.

    Examples:
        16:9 (12192000 EMU) → 6350.0
        4:3  (9144000 EMU)  → 4762.5
    """
    return slide_width_emu / _CANVAS_WIDTH_PX


def slide_size_px(slide_width_emu: int, slide_height_emu: int) -> tuple[int, int]:
    """Derive canvas size in px from physical slide dimensions in EMU.

    Width is always 1920 (design invariant). Height is proportional
    to the aspect ratio.

    Examples:
        16:9 (12192000, 6858000) → (1920, 1080)
        4:3  (9144000, 6858000)  → (1920, 1440)
    """
    scale = emu_per_px(slide_width_emu)
    return (_CANVAS_WIDTH_PX, round(slide_height_emu / scale))
