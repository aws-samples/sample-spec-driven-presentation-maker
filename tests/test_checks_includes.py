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
