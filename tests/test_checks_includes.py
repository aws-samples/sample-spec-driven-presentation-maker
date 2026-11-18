# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for sdpm.engine.checks.includes."""

from __future__ import annotations

import json

from sdpm.engine.checks.includes import check_includes


def _slides(elements):
    return {"slides": [{"id": "s1", "elements": elements}]}


def test_no_includes_returns_empty(tmp_path):
    data = _slides([{"type": "text", "text": "hello"}])
    assert check_includes(data, tmp_path) == []


def test_valid_include_passes(tmp_path):
    inc = tmp_path / "diagram.json"
    inc.write_text(json.dumps([{"type": "text", "text": "x"}]), encoding="utf-8")
    data = _slides([{"type": "include", "src": "diagram.json"}])
    assert check_includes(data, tmp_path) == []


def test_valid_include_elements_dict_passes(tmp_path):
    inc = tmp_path / "diagram.json"
    inc.write_text(json.dumps({"elements": [{"type": "text"}]}), encoding="utf-8")
    data = _slides([{"type": "include", "src": "diagram.json"}])
    assert check_includes(data, tmp_path) == []


def test_missing_src_key_warns(tmp_path):
    data = _slides([{"type": "include"}])
    warnings = check_includes(data, tmp_path)
    assert warnings
    assert "no `src`" in "\n".join(warnings)


def test_missing_file_warns(tmp_path):
    data = _slides([{"type": "include", "src": "nope.json"}])
    warnings = check_includes(data, tmp_path)
    assert warnings
    joined = "\n".join(warnings)
    assert "not found" in joined
    assert "nope.json" in joined


def test_invalid_json_warns(tmp_path):
    inc = tmp_path / "broken.json"
    inc.write_text("{not json", encoding="utf-8")
    data = _slides([{"type": "include", "src": "broken.json"}])
    warnings = check_includes(data, tmp_path)
    assert "invalid JSON" in "\n".join(warnings)


def test_empty_elements_warns(tmp_path):
    inc = tmp_path / "empty.json"
    inc.write_text("[]", encoding="utf-8")
    data = _slides([{"type": "include", "src": "empty.json"}])
    warnings = check_includes(data, tmp_path)
    assert "0 " in "\n".join(warnings)


def test_absolute_src_resolves(tmp_path):
    inc = tmp_path / "abs.json"
    inc.write_text(json.dumps([{"type": "text"}]), encoding="utf-8")
    data = _slides([{"type": "include", "src": str(inc)}])
    # base_dir intentionally different from the file's directory
    assert check_includes(data, tmp_path / "elsewhere") == []


def test_warning_includes_page_location(tmp_path):
    data = _slides([{"type": "include", "src": "gone.json"}])
    warnings = check_includes(data, tmp_path)
    assert "page01(s1)" in "\n".join(warnings)


class TestTheIncludeFileIsReadOncePerVersion:
    """A build expands includes twice, so the file read is shared.

    `_resolve_config` expands them to lint a slide it must not alter, and
    `PPTXBuilder` expands them again to produce the shapes. Keeping one copy for
    both would put expanded elements into `BuildConfig.slides`, which the
    layout-balance check and the per-slide summary also read, so the second
    pass stays and the read is cached instead.
    """

    def test_a_second_expansion_does_not_reread_the_file(self, tmp_path):
        from sdpm.engine.builder import _include_elements, expand_includes

        inc = tmp_path / "panel.json"
        inc.write_text(json.dumps([{"id": "panel", "type": "shape"}]), encoding="utf-8")
        elements = [{"type": "include", "src": "panel.json"}]

        _include_elements.cache_clear()
        expand_includes(elements, tmp_path)
        after_first = _include_elements.cache_info()
        expand_includes(elements, tmp_path)
        after_second = _include_elements.cache_info()
        assert after_second.hits == after_first.hits + 1
        assert after_second.misses == after_first.misses

    def test_an_edited_file_is_read_again(self, tmp_path):
        """Keyed on mtime and size, so a cached copy cannot go stale."""
        import os

        from sdpm.engine.builder import expand_includes

        inc = tmp_path / "panel.json"
        inc.write_text(json.dumps([{"id": "before", "type": "shape"}]), encoding="utf-8")
        elements = [{"type": "include", "src": "panel.json"}]
        assert [e["id"] for e in expand_includes(elements, tmp_path)] == ["before"]

        inc.write_text(json.dumps([{"id": "after", "type": "shape"}]), encoding="utf-8")
        # A same-size rewrite within the filesystem's timestamp granularity
        # would otherwise be the same key.
        stamp = inc.stat().st_mtime_ns + 1_000_000_000
        os.utime(inc, ns=(stamp, stamp))
        assert [e["id"] for e in expand_includes(elements, tmp_path)] == ["after"]

    def test_the_caller_may_edit_what_it_gets_back(self, tmp_path):
        """Two readers hold the same cached entry, so each gets its own copy."""
        from sdpm.engine.builder import expand_includes

        inc = tmp_path / "panel.json"
        inc.write_text(json.dumps([{"id": "panel", "type": "shape"}]), encoding="utf-8")
        elements = [{"type": "include", "src": "panel.json"}]

        first = expand_includes(elements, tmp_path)
        first[0]["id"] = "mutated"
        assert [e["id"] for e in expand_includes(elements, tmp_path)] == ["panel"]
