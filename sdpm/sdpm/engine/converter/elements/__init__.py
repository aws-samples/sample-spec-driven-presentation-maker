# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Element extraction (shape, textbox, line, freeform, picture, group).

Compatibility facade over the elements package. Import surface is frozen:
the seven public extractors plus ``_dispatch_shape`` (used by
``converter.slide``) — see tests/test_converter_elements.py.
"""

from .shapes import (extract_line_element as extract_line_element,
                     extract_freeform_element as extract_freeform_element,
                     extract_shape_element as extract_shape_element)
from .textbox import extract_textbox_element as extract_textbox_element
from .media import (extract_video_element as extract_video_element,
                    extract_picture_element as extract_picture_element)
from .dispatch import (extract_group_element as extract_group_element,
                       _dispatch_shape as _dispatch_shape)

__all__ = [
    "extract_line_element",
    "extract_freeform_element",
    "extract_shape_element",
    "extract_textbox_element",
    "extract_video_element",
    "extract_picture_element",
    "extract_group_element",
]
