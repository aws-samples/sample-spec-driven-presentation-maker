# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.engine.preview.compose — SVG composition for the live preview."""

import tempfile
from pathlib import Path

from sdpm.engine.preview.compose import (
    extract_optimized_defs,
    load_svg,
    mark_changed,
    source_hash,
    split_slide_components,
)


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

# Master-page background: the slide has no own background, so the fragment
# comes from the master referenced in ooo:meta_slides. Slide 0 is LibreOffice's
# leading group; real slides start at 1 (count_slides convention).
_MASTER_BG_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:ooo="http://xml.openoffice.org/svg/export"
     viewBox="0 0 28000 15750" fill-rule="evenodd">
  <defs/>
  <g id="ooo:meta_slides">
    <g id="ooo:meta_slide_0" ooo:master="master_1"/>
  </g>
  <g id="master_1">
    <g class="Background">
      <path fill="rgb(10,20,30)" d="M0,0 h28000 v15750 h-28000 z M10,10 h10 v10 h-10 z"/>
    </g>
  </g>
  <g class="Slide"><g class="Page"/></g>
  <g class="Slide">
    <g class="Page">
      <g class="Graphic">
        <rect class="BoundingBox" x="0" y="0" width="100" height="100"/>
      </g>
    </g>
  </g>
</svg>
"""

# LibreOffice writes textLength/lengthAdjust on text runs (in fragments and defs).
_TEXT_LENGTH_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28000 15750">
  <defs>
    <text id="t1" textLength="300" lengthAdjust="spacingAndGlyphs">Def</text>
  </defs>
  <g class="Slide">
    <g class="Page">
      <g class="TextShape">
        <rect class="BoundingBox" x="0" y="0" width="1000" height="200"/>
        <text><tspan x="0" y="100" textLength="900" lengthAdjust="spacingAndGlyphs">Hello</tspan></text>
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

    def test_evenodd_propagated_to_master_background(self):
        """The master-page background fragment also inherits the root fill-rule."""
        svg_path = _write_svg(_MASTER_BG_SVG)
        result = split_slide_components(svg_path, 1)

        assert result["bgFill"] == "rgb(10,20,30)"
        assert result["bgSvg"] is not None
        assert 'fill-rule="evenodd"' in result["bgSvg"]

    def test_shared_tree_serves_every_extraction(self):
        """One load_svg tree gives the same fragments as parsing the path."""
        svg_path = _write_svg(_EVENODD_SVG)
        tree = load_svg(svg_path)
        extract_optimized_defs(tree)
        assert split_slide_components(tree, 0) == split_slide_components(svg_path, 0)


class TestTextLengthStripped:
    """textLength / lengthAdjust are removed so WebKit does not squash glyphs."""

    def test_stripped_from_component(self):
        svg_path = _write_svg(_TEXT_LENGTH_SVG)
        result = split_slide_components(svg_path, 0)

        comp = result["components"][0]
        assert comp["text"] == "Hello"
        assert "Hello" in comp["svg"]
        assert "textLength" not in comp["svg"]
        assert "lengthAdjust" not in comp["svg"]

    def test_stripped_from_defs(self):
        svg_path = _write_svg(_TEXT_LENGTH_SVG)
        defs = extract_optimized_defs(svg_path)["defs"]

        assert "Def" in defs
        assert "textLength" not in defs
        assert "lengthAdjust" not in defs


def _comp(cls: str, x: float, text: str) -> dict:
    return {"class": cls, "bbox": {"x": x, "y": 0.0, "w": 10.0, "h": 10.0}, "text": text}


class TestMarkChanged:
    """Component diff against the previous compose of the same slide."""

    def test_no_previous_marks_all_changed(self):
        comps = [_comp("TextShape", 0, "a")]
        mark_changed(comps, None)
        assert [c["changed"] for c in comps] == [True]

    def test_same_source_hash_marks_none_changed(self):
        comps = [_comp("TextShape", 0, "new text")]
        mark_changed(comps, [_comp("TextShape", 0, "old")], "h1", "h1")
        assert [c["changed"] for c in comps] == [False]

    def test_match_by_class_and_bbox_compare_text(self):
        prev = [_comp("TextShape", 0, "same"), _comp("TextShape", 50, "old")]
        comps = [_comp("TextShape", 0, "same"), _comp("TextShape", 50, "new"), _comp("Graphic", 99, "")]
        mark_changed(comps, prev, "h2", "h1")
        assert [c["changed"] for c in comps] == [False, True, True]

    def test_empty_source_hash_never_short_circuits(self):
        comps = [_comp("TextShape", 0, "new")]
        mark_changed(comps, [_comp("TextShape", 0, "old")], "", "")
        assert [c["changed"] for c in comps] == [True]

    def test_source_hash_ignores_key_order(self):
        assert source_hash({"a": 1, "b": "é"}) == source_hash({"b": "é", "a": 1})
