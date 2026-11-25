"""Build-time checks for slide JSON (token discipline, etc.)."""

from sdpm.engine.checks.correspondence import (
    correspondence_facts,
    count_visible_characters,
    count_visible_words,
    density_limit,
    density_sample_characters,
)
from sdpm.engine.checks.font_size import check_font_size_tokens
from sdpm.engine.checks.includes import check_includes
from sdpm.engine.checks.overlay_textbox import check_overlay_textbox

__all__ = [
    "check_font_size_tokens",
    "check_includes",
    "check_overlay_textbox",
    "correspondence_facts",
    "count_visible_characters",
    "count_visible_words",
    "density_limit",
    "density_sample_characters",
]
