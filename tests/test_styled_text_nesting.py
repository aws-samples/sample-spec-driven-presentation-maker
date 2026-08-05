# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Nested styled-text notation support (issue #123).

Agents sometimes nest styled-text tags ({{bold:{{#FF0000:X}}}}) instead of
using the canonical comma form ({{bold,#FF0000:X}}). The regex parser cannot
see through nesting, which leaked raw tag text onto slides. A flatten
pre-pass (_flatten_nested_styles) rewrites nesting into the canonical form.
"""

from sdpm.utils.text import (
    _expand_styled_newlines,
    _flatten_nested_styles,
    parse_styled_text,
)


def _all_text(segments):
    return "".join(s["text"] for s in segments)


class TestFlattenNestedStyles:
    def test_full_nest(self):
        assert _flatten_nested_styles("{{bold:{{#FF0000:重要}}}}") == "{{bold,#FF0000:重要}}"

    def test_partial_nest_distributes_outer_attrs(self):
        assert (
            _flatten_nested_styles("{{bold:a{{#FF0000:b}}c}}")
            == "{{bold:a}}{{bold,#FF0000:b}}{{bold:c}}"
        )

    def test_depth_three(self):
        assert (
            _flatten_nested_styles("{{bold:{{italic:{{#FF0000:x}}}}}}")
            == "{{bold,italic,#FF0000:x}}"
        )

    def test_value_attrs_nest(self):
        assert (
            _flatten_nested_styles("{{baseline=-25000:{{#FF0000:x}}}}")
            == "{{baseline=-25000,#FF0000:x}}"
        )

    def test_non_nested_input_is_byte_identical(self):
        cases = [
            "plain text",
            "{{bold,#FF0000:x}}",
            "{{bold:a\\}b}}",  # escaped brace
            "a {{12pt:x}} b {{font=Menlo:code}}",
            "{{link:https://example.com:text}}",
            "{{14pt,link:https://example.com:text}}",
            "{{bold:}}",  # empty body (parser treats as literal today)
            "{{bold:通常}}\n{{italic:斜体}}",
        ]
        for s in cases:
            assert _flatten_nested_styles(s) == s

    def test_bare_braces_pass_through(self):
        # highlight_code emits bare { } between tags; a single-char brace
        # must never be mistaken for a tag boundary.
        cases = [
            "{{#d6deeb:dict}}{",
            "{{#d6deeb:foo}}{{{#c792ea:bar}}",  # bare { adjacent to tag start
            "{ }",
            "{{#c792ea:f}}({{#d6deeb:x}})",
            "{{#d6deeb:func}}({{#c792ea:{}}})",  # bare brace inside tag body
        ]
        for s in cases:
            assert _flatten_nested_styles(s) == s

    def test_pathological_depth_falls_back_without_crash(self):
        deep = "{{bold:" * 2000 + "x" + "}}" * 2000
        assert _flatten_nested_styles(deep) == deep  # RecursionError guard

    def test_unbalanced_falls_back_to_original(self):
        cases = [
            "{{bold:{{#FF0000:x}}",  # outer never closed
            "{{bold:a}b}}",  # unescaped single }
            "{{bold:unclosed",
        ]
        for s in cases:
            assert _flatten_nested_styles(s) == s

    def test_idempotent(self):
        once = _flatten_nested_styles("{{bold:a{{#FF0000:b}}c}}")
        assert _flatten_nested_styles(once) == once

    def test_nested_link_stays_verbatim(self):
        # Nested links are out of scope: kept as body text, not merged.
        s = "{{bold:{{link:https://example.com:t}}}}"
        assert _flatten_nested_styles(s) == s

    def test_newline_in_plain_part_emits_complete_tags_per_line(self):
        # Trailing newline must not produce an empty {{attrs:}} (would leak).
        assert (
            _flatten_nested_styles("{{bold:a\n{{#FF0000:b}}}}")
            == "{{bold:a}}\n{{bold,#FF0000:b}}"
        )


class TestParseStyledTextNested:
    def test_full_nest_segments(self):
        segments = parse_styled_text("{{bold:{{#FF0000:重要}}}}")
        assert segments == [{"text": "重要", "bold": True, "color": "#FF0000"}]

    def test_partial_nest_segments(self):
        segments = parse_styled_text("{{bold:通常と{{#FF0000:赤}}の混在}}")
        assert [s["text"] for s in segments] == ["通常と", "赤", "の混在"]
        assert all(s.get("bold") for s in segments)
        assert [s.get("color") for s in segments] == [None, "#FF0000", None]

    def test_inner_color_wins(self):
        segments = parse_styled_text("{{#00FF00:{{#FF0000:x}}}}")
        assert segments == [{"text": "x", "color": "#FF0000"}]

    def test_no_tag_leakage(self):
        for s in [
            "{{bold:{{#FF0000:重要}}}}",
            "{{bold:通常と{{#FF0000:赤}}の混在}}",
            "{{bold:{{italic:{{#FF0000:x}}}}}}",
        ]:
            assert "{{" not in _all_text(parse_styled_text(s))

    def test_auto_spacing_false_preserves_text(self):
        segments = parse_styled_text("{{bold:漢字{{#FF0000:abc}}}}", auto_spacing=False)
        assert _all_text(segments) == "漢字abc"  # no space inserted

    def test_auto_spacing_true_inserts_boundary_space(self):
        segments = parse_styled_text("{{bold:漢字{{#FF0000:abc}}}}")
        assert _all_text(segments) == "漢字 abc"

    def test_unbalanced_does_not_crash(self):
        # Fallback: same (broken) output as before the flatten pre-pass.
        segments = parse_styled_text("{{bold:{{#FF0000:x}}")
        assert isinstance(segments, list)

    def test_link_before_and_after_nest(self):
        segments = parse_styled_text(
            "{{link:https://example.com:site}} {{bold:{{#FF0000:x}}}}"
        )
        assert segments[0] == {"text": "site", "link": "https://example.com"}
        assert {"text": "x", "bold": True, "color": "#FF0000"} in segments


class TestExpandStyledNewlinesNested:
    def test_nest_with_newline_expands_per_line(self):
        # Builders split on \n after expand; without flatten-first the split
        # would cut the nested tag in half.
        assert (
            _expand_styled_newlines("{{bold:a\n{{#FF0000:b}}}}")
            == "{{bold:a}}\n{{bold,#FF0000:b}}"
        )

    def test_plain_expand_unchanged(self):
        assert (
            _expand_styled_newlines("{{bold:line1\nline2}}")
            == "{{bold:line1}}\n{{bold:line2}}"
        )
