"""Build-time checks for slide JSON (token discipline, etc.)."""

from sdpm.engine.checks.font_size import check_font_size_tokens
from sdpm.engine.checks.includes import check_includes
from sdpm.engine.checks.morph_pairing import check_morph_pairing
from sdpm.engine.checks.overlay_textbox import check_overlay_textbox
from sdpm.engine.checks.text_build import check_text_build

__all__ = [
    "check_font_size_tokens",
    "check_includes",
    "check_morph_pairing",
    "check_overlay_textbox",
    "check_text_build",
]
