# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.checks.font_size."""

from __future__ import annotations

from pathlib import Path

from sdpm.checks.font_size import (
    _walk_font_sizes,
    check_font_size_tokens,
    find_art_direction,
    parse_allowed_font_sizes,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_ART_DIRECTION_HTML = """<!doctype html>
<html><head><style>
:root {
    --fs-cover-title: 48pt;
    --fs-slide-title: 32pt;
    --fs-heading: 24pt;
    --fs-body: 16pt;
    --fs-caption: 12pt;
    --fs-alias: var(--fs-body);  /* var refs should be ignored */
}
</style></head><body></body></html>
"""

_SLIDES_WITH_VIOLATIONS = {
    "slides": [
        # Slide 1: valid
        {"elements": [{"type": "text", "fontSize": 24, "text": "OK"}]},
        # Slide 2: one violation (22 not allowed)
        {"elements": [{"type": "text", "fontSize": 22, "text": "BAD"}]},
        # Slide 3: two violations (18 twice) at different paths
        {
            "title": {"fontSize": 18, "text": "bad-title"},
            "elements": [
                {"type": "text", "fontSize": 18, "text": "also-bad"},
                {"type": "text", "fontSize": 16, "text": "good"},
            ],
        },
    ]
}

_SLIDES_ALL_VALID = {
    "slides": [
        {"elements": [{"type": "text", "fontSize": 48}]},
        {"elements": [{"type": "text", "fontSize": 16}]},
    ]
}


# ---------------------------------------------------------------------------
# parse_allowed_font_sizes
# ---------------------------------------------------------------------------

class TestParseAllowedFontSizes:
    def test_extracts_all_tokens(self, tmp_path):
        p = tmp_path / "art-direction.html"
        p.write_text(_ART_DIRECTION_HTML, encoding="utf-8")
        assert parse_allowed_font_sizes(p) == {48, 32, 24, 16, 12}

    def test_missing_file_returns_empty_set(self, tmp_path):
        assert parse_allowed_font_sizes(tmp_path / "nope.html") == set()

    def test_no_fs_tokens_returns_empty(self, tmp_path):
        p = tmp_path / "plain.html"
        p.write_text(":root { --color-primary: #000; }", encoding="utf-8")
        assert parse_allowed_font_sizes(p) == set()

    def test_var_references_not_captured(self, tmp_path):
        """`--fs-x: var(--fs-y);` must not be captured as a pt value."""
        p = tmp_path / "art.html"
        p.write_text(":root { --fs-base: 16pt; --fs-alias: var(--fs-base); }", encoding="utf-8")
        assert parse_allowed_font_sizes(p) == {16}

    def test_whitespace_tolerant(self, tmp_path):
        p = tmp_path / "art.html"
        p.write_text(":root {\n  --fs-body :   18pt  ;\n}", encoding="utf-8")
        assert parse_allowed_font_sizes(p) == {18}


# ---------------------------------------------------------------------------
# _walk_font_sizes
# ---------------------------------------------------------------------------

class TestWalkFontSizes:
    def test_flat_dict(self):
        result = list(_walk_font_sizes({"fontSize": 24}))
        assert result == [([], 24)]

    def test_nested_dict(self):
        node = {"title": {"fontSize": 32, "text": "hi"}}
        result = list(_walk_font_sizes(node))
        assert result == [(["title"], 32)]

    def test_list_indexed(self):
        node = {"elements": [{"fontSize": 16}, {"fontSize": 20}]}
        result = list(_walk_font_sizes(node))
        assert ([("elements"), "[0]"], 16) in [(p, fs) for p, fs in result]
        paths = [".".join(p) for p, _ in result]
        assert "elements.[0]" in paths
        assert "elements.[1]" in paths

    def test_ignores_non_numeric_font_size(self):
        node = {"fontSize": "large"}
        assert list(_walk_font_sizes(node)) == []

    def test_float_is_truncated_to_int(self):
        # Floats are cast to int for comparison (22.9 → 22).
        result = list(_walk_font_sizes({"fontSize": 22.9}))
        assert result == [([], 22)]


# ---------------------------------------------------------------------------
# find_art_direction  (regression coverage for directory-input path)
# ---------------------------------------------------------------------------

class TestFindArtDirection:
    def _setup_project(self, root: Path) -> Path:
        """Create a project with specs/art-direction.html. Returns the art path."""
        specs = root / "specs"
        specs.mkdir(parents=True)
        art = specs / "art-direction.html"
        art.write_text(_ART_DIRECTION_HTML, encoding="utf-8")
        return art

    def test_file_input_finds_sibling_specs(self, tmp_path):
        """Legacy file input: presentation.json → project/specs/art-direction.html."""
        project = tmp_path / "proj"
        project.mkdir()
        art = self._setup_project(project)
        pres = project / "presentation.json"
        pres.write_text("{}", encoding="utf-8")

        assert find_art_direction(pres) == art

    def test_directory_input_finds_child_specs(self, tmp_path):
        """Directory input: deck/ → deck/specs/art-direction.html.

        This is the primary MCP agent path and was silently skipping before
        the fix — this test guards against regression.
        """
        project = tmp_path / "proj"
        project.mkdir()
        art = self._setup_project(project)
        (project / "deck.json").write_text("{}", encoding="utf-8")
        (project / "slides").mkdir()

        assert find_art_direction(project) == art

    def test_file_input_finds_parent_specs(self, tmp_path):
        """File input where JSON lives in a sub-directory of the project."""
        project = tmp_path / "proj"
        project.mkdir()
        art = self._setup_project(project)
        sub = project / "build"
        sub.mkdir()
        pres = sub / "presentation.json"
        pres.write_text("{}", encoding="utf-8")

        assert find_art_direction(pres) == art

    def test_directory_input_finds_parent_specs(self, tmp_path):
        """Directory input where deck lives under the style's parent."""
        project = tmp_path / "proj"
        project.mkdir()
        art = self._setup_project(project)
        sub = project / "deck"
        sub.mkdir()

        assert find_art_direction(sub) == art

    def test_returns_none_when_not_found(self, tmp_path):
        stray = tmp_path / "stray"
        stray.mkdir()
        assert find_art_direction(stray) is None


# ---------------------------------------------------------------------------
# check_font_size_tokens — end-to-end
# ---------------------------------------------------------------------------

class TestCheckFontSizeTokens:
    def _make_project(self, root: Path, *, layout: str) -> Path:
        """Create project layout with art-direction.html.

        layout="file": returns path to presentation.json
        layout="dir":  returns path to project directory
        """
        project = root / "proj"
        project.mkdir()
        specs = project / "specs"
        specs.mkdir()
        (specs / "art-direction.html").write_text(_ART_DIRECTION_HTML, encoding="utf-8")

        if layout == "file":
            pres = project / "presentation.json"
            pres.write_text("{}", encoding="utf-8")
            return pres
        else:
            (project / "deck.json").write_text("{}", encoding="utf-8")
            (project / "slides").mkdir()
            return project

    def test_file_input_detects_violations(self, tmp_path):
        path = self._make_project(tmp_path, layout="file")
        warnings = check_font_size_tokens(_SLIDES_WITH_VIOLATIONS, path)

        assert warnings, "expected violations to be reported"
        header = warnings[0]
        assert "fontSize token discipline" in header
        assert "12pt" in header and "48pt" in header  # allowed set
        # Two distinct bad sizes: 18 (×2) and 22 (×1)
        assert any("18pt" in w and "2 occurrence" in w for w in warnings[1:])
        assert any("22pt" in w and "1 occurrence" in w for w in warnings[1:])

    def test_directory_input_detects_violations(self, tmp_path):
        """Regression guard: directory input must trigger the check.

        Before the fix, this returned [] because find_art_direction only
        checked `json_path.parent` and `json_path.parent.parent`, missing
        the deck-dir/specs/ case.
        """
        path = self._make_project(tmp_path, layout="dir")
        warnings = check_font_size_tokens(_SLIDES_WITH_VIOLATIONS, path)

        assert warnings, "directory input must detect violations after fix"
        assert "fontSize token discipline" in warnings[0]

    def test_no_violations_returns_empty(self, tmp_path):
        path = self._make_project(tmp_path, layout="dir")
        assert check_font_size_tokens(_SLIDES_ALL_VALID, path) == []

    def test_missing_art_direction_skipped(self, tmp_path):
        # No specs/ at all.
        project = tmp_path / "proj"
        project.mkdir()
        (project / "deck.json").write_text("{}", encoding="utf-8")
        assert check_font_size_tokens(_SLIDES_WITH_VIOLATIONS, project) == []

    def test_no_fs_tokens_in_style_skipped(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        specs = project / "specs"
        specs.mkdir()
        (specs / "art-direction.html").write_text(
            ":root { --color-primary: #000; }", encoding="utf-8"
        )
        assert check_font_size_tokens(_SLIDES_WITH_VIOLATIONS, project) == []

    def test_location_format_includes_page_and_path(self, tmp_path):
        path = self._make_project(tmp_path, layout="dir")
        warnings = check_font_size_tokens(_SLIDES_WITH_VIOLATIONS, path)

        # Slide 3 has a violation at `title.fontSize` — verify the path appears.
        joined = "\n".join(warnings)
        assert "page02" in joined  # slide 2 (22pt)
        assert "page03" in joined  # slide 3 (18pt × 2)
        assert "title" in joined   # nested path from slide 3 title.fontSize
