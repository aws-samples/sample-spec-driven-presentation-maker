# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.engine.preview.compose — SVG composition for the live preview."""

import tempfile
from pathlib import Path

from sdpm.engine.preview.compose import (
    extract_optimized_defs,
    load_svg,
    mark_changed,
    referenced_defs,
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


# LibreOffice writes a bitmap once as <image> and later copies as <use href="#bitmap(N)">
# without giving the <image> that id (seen with LibreOffice 26.2): here the same logo on two
# master pages, and the same picture on two slides (second one moved right by 2778).
_IMG = "data:image/jpeg;base64,/9j/4AAQ"
_BITMAP_USE_SVG = f"""\
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     xmlns:ooo="http://xml.openoffice.org/svg/export" viewBox="0 0 28000 15750">
  <defs>
    <g id="ooo:meta_slides">
      <g id="ooo:meta_slide_0" ooo:master="m1"/>
      <g id="ooo:meta_slide_1" ooo:master="m2"/>
    </g>
  </defs>
  <defs>
    <g id="m1" class="Master_Slide">
      <g class="Background"><path fill="rgb(255,255,255)" d="M0,0 h28000 v15750 h-28000 z"/></g>
      <g class="BackgroundObjects"><g class="Graphic"><g>
        <rect class="BoundingBox" x="0" y="0" width="8467" height="4763"/>
        <image x="0" y="0" width="8467" height="4763" preserveAspectRatio="none" xlink:href="{_IMG}"/>
      </g></g></g>
    </g>
    <g id="m2" class="Master_Slide">
      <g class="Background"><path fill="rgb(255,255,255)" d="M0,0 h28000 v15750 h-28000 z"/></g>
      <g class="BackgroundObjects"><g class="Graphic"><g>
        <rect class="BoundingBox" x="0" y="0" width="8467" height="4763"/>
        <use xlink:href="#bitmap(3415900103)"/>
      </g></g></g>
    </g>
  </defs>
  <g class="Slide"><g class="Page"/></g>
  <g class="Slide"><g class="Page">
    <g class="Graphic"><g>
      <rect class="BoundingBox" x="2778" y="2778" width="5556" height="3125"/>
      <image x="2778" y="2778" width="5556" height="3125" preserveAspectRatio="none" xlink:href="{_IMG}"/>
    </g></g>
  </g></g>
  <g class="Slide"><g class="Page">
    <g class="Graphic"><g>
      <rect class="BoundingBox" x="5556" y="2778" width="5556" height="3125"/>
      <use transform="translate(-2778, 0)" xlink:href="#bitmap(767664673)"/>
    </g></g>
  </g></g>
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


class TestDanglingBitmapUse:
    """A repeated bitmap LibreOffice wrote as a <use> with no target is drawn again."""

    def test_master_background_logo_on_second_master(self):
        result = split_slide_components(_write_svg(_BITMAP_USE_SVG), 2)

        assert "<use" not in result["bgSvg"]
        assert 'x="0" y="0" width="8467" height="4763"' in result["bgSvg"]
        assert "data:image/" in result["bgSvg"]

    def test_repeated_picture_on_slide(self):
        svg = split_slide_components(_write_svg(_BITMAP_USE_SVG), 2)["components"][0]["svg"]

        assert "<use" not in svg
        assert 'x="5556" y="2778" width="5556" height="3125"' in svg

    def test_ambiguous_source_left_alone(self):
        """Two different earlier images fit the geometry: no guess is made."""
        first = f'<image x="0" y="0" width="8467" height="4763" preserveAspectRatio="none" xlink:href="{_IMG}"/>'
        other = _BITMAP_USE_SVG.replace(first, first + first.replace(_IMG, "data:image/jpeg;base64,AAAA"), 1)
        tree = load_svg(_write_svg(other))
        uses = tree.getroot().findall(".//{http://www.w3.org/2000/svg}use")

        assert [u.get("{http://www.w3.org/1999/xlink}href") for u in uses] == ["#bitmap(3415900103)"]


class TestLayoutPlaceholderPrompt:
    """A layout placeholder's prompt text never reaches the slide background."""

    # LibreOffice keeps the Title Slide layout's subtitle placeholder (with its prompt text)
    # in the master page's BackgroundObjects; footer chrome there is real slide content.
    _SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" xmlns:ooo="http://xml.openoffice.org/svg/export"
     viewBox="0 0 28000 15750">
  <defs>
    <g id="ooo:meta_slides">
      <g id="ooo:meta_slide_0" ooo:master="m1"/>
      <g id="ooo:meta_slide_1" ooo:master="m1"/>
    </g>
  </defs>
  <defs>
    <g id="m1" class="Master_Slide">
      <g class="Background"><path fill="rgb(0,0,0)" d="M0,0 h28000 v15750 h-28000 z"/></g>
      <g class="BackgroundObjects">
        <g class="Graphic"><g><rect class="BoundingBox" x="0" y="0" width="10" height="10"/>
          <path fill="red" d="M0,0 h10 v10 h-10 z"/></g></g>
        <g class="com.sun.star.presentation.SubtitleShape"><g id="id13">
          <rect class="BoundingBox" x="1905" y="10795" width="27112" height="2153"/>
          <text><tspan>Subtitle</tspan></text></g></g>
        <g class="DateTime"><g><text><tspan>11/12/26</tspan></text></g></g>
        <g class="Footer"><g><text><tspan>Confidential</tspan></text></g></g>
        <g class="PageNumber"><g><text><tspan>7</tspan></text></g></g>
      </g>
    </g>
  </defs>
  <g class="Slide"><g class="Page"/></g>
  <g class="Slide"><g class="Page"/></g>
  <g class="Slide"><g class="Page">
    <g class="com.sun.star.presentation.SubtitleShape"><g>
      <rect class="BoundingBox" x="1905" y="10795" width="27112" height="2153"/>
      <text><tspan>Real subtitle</tspan></text></g></g>
  </g></g>
</svg>
"""

    def test_empty_subtitle_prompt_not_in_background(self):
        result = split_slide_components(_write_svg(self._SVG), 1)

        assert "Subtitle" not in result["bgSvg"]
        assert 'fill="red"' in result["bgSvg"]

    def test_filled_subtitle_prompt_not_under_slide_text(self):
        result = split_slide_components(_write_svg(self._SVG), 2)

        assert "Subtitle" not in result["bgSvg"]
        assert [c["text"] for c in result["components"]] == ["Real subtitle"]

    def test_footer_chrome_kept(self):
        bg = split_slide_components(_write_svg(self._SVG), 1)["bgSvg"]

        assert "11/12/26" in bg and "Confidential" in bg and ">7<" in bg


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


_DEFS = (
    '<defs xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
    '<g id="bullet-a"><path d="M0,0"/></g><g id="bullet-b"><path d="M1,1"/></g>'
    '<linearGradient id="base"><stop offset="0"/></linearGradient>'
    '<linearGradient id="derived" xlink:href="#base"/>'
    '<g id="outer"><clipPath id="inner"><rect/></clipPath></g>'
    '<g id="master" class="Master_Slide"><image xlink:href="data:image/webp;base64,AAAA"/></g>'
    "</defs>"
)


class TestReferencedDefs:
    """The part of the deck's defs one slide draws from."""

    def test_only_referenced_elements_in_document_order(self):
        got = referenced_defs(_DEFS, ['<use xlink:href="#bullet-b"/>', '<path fill="url(#derived)"/>'])
        assert got.startswith("<defs") and got.endswith("</defs>")
        assert got.index('id="bullet-b"') < got.index('id="base"') < got.index('id="derived"')
        assert "bullet-a" not in got and "master" not in got and "image" not in got

    def test_a_nested_reference_comes_with_its_parent_once(self):
        got = referenced_defs(_DEFS, ['<g clip-path="url(\'#inner\')"/>', '<use href="#outer"/>'])
        assert got.count('id="inner"') == 1 and 'id="outer"' in got

    def test_nothing_referenced_or_unknown(self):
        assert referenced_defs(_DEFS, ['<path fill="url(#elsewhere)"/>', "<rect/>"]) == ""
        assert referenced_defs(_DEFS, []) == ""
        assert referenced_defs("", ['<use href="#bullet-a"/>']) == ""

    def test_unparseable_defs_are_kept_whole(self):
        assert referenced_defs("<defs><g id='a'>", ['<use href="#a"/>']) == "<defs><g id='a'>"
