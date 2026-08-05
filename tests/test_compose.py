# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for servers/remote/tools/compose.py — SVG composition."""

import tempfile
from pathlib import Path

from tools.compose import split_slide_components


# Minimal LibreOffice-style SVG with fill-rule="evenodd" on root <svg>.
# The icon path uses 2 subpaths (outer + inner cutout) that only render
# correctly under evenodd; under the default nonzero, the cutout fills solid.
_EVENODD_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 28000 15750"
     fill-rule="evenodd" stroke-width="28.222" stroke-linejoin="round">
  <defs/>
  <g class="Slide">
    <g class="Page">
      <g class="Graphic">
        <rect class="BoundingBox" x="100" y="100" width="500" height="500"/>
        <path fill="rgb(237,113,0)"
              d="M100,100 h500 v500 h-500 z M200,200 h300 v300 h-300 z"/>
      </g>
    </g>
  </g>
</svg>
"""

# SVG where a component already has fill-rule — should not be overwritten.
_EXISTING_ATTR_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 28000 15750"
     fill-rule="evenodd" stroke-width="28.222" stroke-linejoin="round">
  <defs/>
  <g class="Slide">
    <g class="Page">
      <g class="Graphic" fill-rule="nonzero">
        <rect class="BoundingBox" x="0" y="0" width="100" height="100"/>
        <path fill="red" d="M0,0 h100 v100 h-100 z"/>
      </g>
    </g>
  </g>
</svg>
"""

# SVG with no inheritable attrs on root — nothing should be added.
_NO_ROOT_ATTRS_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28000 15750">
  <defs/>
  <g class="Slide">
    <g class="Page">
      <g class="Graphic">
        <rect class="BoundingBox" x="0" y="0" width="100" height="100"/>
        <path fill="blue" d="M0,0 h100 v100 h-100 z"/>
      </g>
    </g>
  </g>
</svg>
"""


def _write_svg(content: str) -> Path:
    """Write SVG to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(suffix=".svg", mode="w", delete=False)
    f.write(content)
    f.close()
    return Path(f.name)


class TestSplitSlideComponentsRootAttrs:
    """Root <svg> presentation attributes are propagated to fragments."""

    def test_evenodd_propagated_to_component(self):
        """fill-rule, stroke-width, stroke-linejoin from root appear on fragment <g>."""
        svg_path = _write_svg(_EVENODD_SVG)
        result = split_slide_components(svg_path, 0)

        assert len(result["components"]) == 1
        svg_str = result["components"][0]["svg"]
        assert 'fill-rule="evenodd"' in svg_str
        assert 'stroke-width="28.222"' in svg_str
        assert 'stroke-linejoin="round"' in svg_str

    def test_existing_attr_not_overwritten(self):
        """If a fragment already has fill-rule, the root value is not applied."""
        svg_path = _write_svg(_EXISTING_ATTR_SVG)
        result = split_slide_components(svg_path, 0)

        assert len(result["components"]) == 1
        svg_str = result["components"][0]["svg"]
        # The existing nonzero must be preserved, not replaced by evenodd
        assert 'fill-rule="nonzero"' in svg_str
        assert 'fill-rule="evenodd"' not in svg_str
        # Other attrs still propagated
        assert 'stroke-width="28.222"' in svg_str

    def test_no_root_attrs_no_injection(self):
        """When root <svg> has no inheritable attrs, nothing is injected."""
        svg_path = _write_svg(_NO_ROOT_ATTRS_SVG)
        result = split_slide_components(svg_path, 0)

        assert len(result["components"]) == 1
        svg_str = result["components"][0]["svg"]
        assert "fill-rule" not in svg_str
        assert "stroke-width" not in svg_str
        assert "stroke-linejoin" not in svg_str
