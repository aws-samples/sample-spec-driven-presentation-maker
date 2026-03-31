# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""PPTX to JSON Converter - Extract PowerPoint content to JSON format

Known Limitations:
- Connectors (LINE shapes): Extracted as simple lines with start/end points
  - Elbow connectors are converted to straight lines
  - Arrow head types (begin/end) are not preserved
  - This is a python-pptx library limitation
- Complex gradients: Non-linear gradients may not preserve exact appearance
- Text effects: Some advanced text effects may not be captured
"""

# Re-export public API
from .pipeline import pptx_to_json as pptx_to_json, main as main
from .slide import extract_slide as extract_slide, detect_layout as detect_layout
from .color import (extract_text_color as extract_text_color,
                    extract_theme_colors_and_mapping as extract_theme_colors_and_mapping,
                    apply_color_transforms as apply_color_transforms,
                    _resolve_scheme_color as _resolve_scheme_color)
from .elements import (extract_shape_element as extract_shape_element,
                       extract_textbox_element as extract_textbox_element,
                       extract_line_element as extract_line_element,
                       extract_freeform_element as extract_freeform_element,
                       extract_picture_element as extract_picture_element,
                       extract_group_element as extract_group_element)
from .table import extract_table_element as extract_table_element
from .chart import extract_chart_element as extract_chart_element
from .constants import _NS as _NS, EMU_PER_PX as EMU_PER_PX
