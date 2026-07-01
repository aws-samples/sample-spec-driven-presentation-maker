"""Build-time checks for slide JSON (token discipline, etc.)."""

from sdpm.checks.font_size import check_font_size_tokens
from sdpm.checks.overlay_textbox import check_overlay_textbox

__all__ = ["check_font_size_tokens", "check_overlay_textbox"]
