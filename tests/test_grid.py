# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for CSS Grid layout calculator (Issue #282)."""

from __future__ import annotations

import json

import pytest

from sdpm.engine.layout.grid import _expand_repeat, _resolve_tracks, compute_grid
from sdpm.tools import grid


# ---------------------------------------------------------------------------
# _resolve_tracks: existing fr/px behaviour (must remain unchanged)
# ---------------------------------------------------------------------------

class TestResolveTracksFrPx:
    """Existing fr and px behaviour — regression guard."""

    def test_single_fr(self):
        assert _resolve_tracks("1fr", 1000, 0) == [1000]

    def test_equal_fr(self):
        assert _resolve_tracks("1fr 1fr 1fr", 1000, 0) == [333, 333, 334]

    def test_ratio_fr(self):
        sizes = _resolve_tracks("2fr 3fr", 1000, 0)
        assert sizes == [400, 600]

    def test_px_fixed(self):
        sizes = _resolve_tracks("300px 1fr 200px", 1000, 20)
        # remaining = 1000 - 300 - 200 - 40 (2 gaps) = 460
        assert sizes == [300, 460, 200]

    def test_shorthand_integer(self):
        sizes = _resolve_tracks("3", 900, 0)
        assert sizes == [300, 300, 300]

    def test_gap_subtracted(self):
        sizes = _resolve_tracks("1fr 1fr", 1000, 20)
        # remaining = 1000 - 20 = 980 → 490 each
        assert sizes == [490, 490]


# ---------------------------------------------------------------------------
# _resolve_tracks: % support (new)
# ---------------------------------------------------------------------------

class TestResolveTracksPercent:
    """Percentage tracks — fraction of available space."""

    def test_fifty_fifty(self):
        sizes = _resolve_tracks("50% 50%", 1000, 0)
        assert sizes == [500, 500]

    def test_thirty_seventy(self):
        sizes = _resolve_tracks("30% 70%", 1000, 0)
        assert sizes == [300, 700]

    def test_percent_with_fr(self):
        # 25% = 250px fixed, remainder = 1000-250-0 = 750 → 1fr gets 750
        sizes = _resolve_tracks("25% 1fr", 1000, 0)
        assert sizes == [250, 750]

    def test_percent_with_gap(self):
        # 50% of 1000 = 500 each; gap eats into fr, not %
        sizes = _resolve_tracks("50% 50%", 1000, 20)
        assert sizes == [500, 500]

    def test_percent_with_px(self):
        sizes = _resolve_tracks("200px 50%", 1000, 0)
        # 200px fixed, 50% of 1000 = 500 fixed
        assert sizes == [200, 500]


# ---------------------------------------------------------------------------
# _expand_repeat / _resolve_tracks: repeat() support (new)
# ---------------------------------------------------------------------------

class TestRepeat:
    """repeat(n, X) expansion."""

    def test_expand_simple(self):
        assert _expand_repeat("repeat(3, 1fr)") == "1fr 1fr 1fr"

    def test_expand_px(self):
        assert _expand_repeat("repeat(2, 200px)") == "200px 200px"

    def test_expand_with_other_tokens(self):
        result = _expand_repeat("100px repeat(2, 1fr) 100px")
        assert result == "100px 1fr 1fr 100px"

    def test_resolve_repeat_fr(self):
        sizes = _resolve_tracks("repeat(3, 1fr)", 900, 0)
        assert sizes == [300, 300, 300]

    def test_resolve_repeat_px(self):
        sizes = _resolve_tracks("repeat(2, 200px)", 1000, 0)
        assert sizes == [200, 200]

    def test_resolve_repeat_mixed(self):
        # "200px repeat(2, 1fr) 200px" → 200 + 1fr + 1fr + 200
        # remaining = 1000 - 200 - 200 - 60 (3 gaps) = 540 → 270 each
        sizes = _resolve_tracks("200px repeat(2, 1fr) 200px", 1000, 20)
        assert sizes == [200, 270, 270, 200]

    def test_resolve_repeat_percent(self):
        sizes = _resolve_tracks("repeat(4, 25%)", 1000, 0)
        assert sizes == [250, 250, 250, 250]


# ---------------------------------------------------------------------------
# _resolve_tracks: error on unsupported syntax
# ---------------------------------------------------------------------------

class TestResolveTracksErrors:
    """Unsupported tokens raise ValueError with self-repair message."""

    def test_auto_raises(self):
        with pytest.raises(ValueError, match="Unsupported track syntax: 'auto'"):
            _resolve_tracks("auto 1fr", 1000, 0)

    def test_minmax_raises(self):
        with pytest.raises(ValueError, match="Unsupported track syntax"):
            _resolve_tracks("minmax(200px,1fr) 1fr", 1000, 0)

    def test_error_message_suggests_alternatives(self):
        with pytest.raises(ValueError, match=r"Use fr, px, %, repeat\(n, X\), or an integer"):
            _resolve_tracks("auto", 1000, 0)

    def test_random_word_raises(self):
        with pytest.raises(ValueError, match="Unsupported track syntax: 'foo'"):
            _resolve_tracks("foo bar", 1000, 0)


# ---------------------------------------------------------------------------
# grid tool: error handling (returns {"error": ...} instead of raising)
# ---------------------------------------------------------------------------

class TestGridToolErrorHandling:
    """The grid MCP tool catches errors and returns structured messages."""

    def test_invalid_json(self):
        result = grid("test", "not json")
        assert "error" in result
        assert "Invalid grid spec JSON" in result["error"]

    def test_unsupported_track_returns_error(self):
        spec = json.dumps({
            "area": {"x": 0, "y": 0, "w": 1000, "h": 100},
            "columns": "auto 1fr",
            "rows": "1fr",
        })
        result = grid("test", spec)
        assert "error" in result
        assert "Unsupported track syntax" in result["error"]

    def test_missing_area_returns_error(self):
        spec = json.dumps({"columns": "1fr 1fr"})
        result = grid("test", spec)
        assert "error" in result

    def test_valid_spec_returns_coordinates(self):
        spec = json.dumps({
            "area": {"x": 0, "y": 0, "w": 1000, "h": 100},
            "columns": "1fr 1fr",
            "rows": "1fr",
        })
        result = grid("test", spec)
        assert "error" not in result
        assert "r0c0" in result
        assert "r0c1" in result

    def test_percent_spec_works(self):
        spec = json.dumps({
            "area": {"x": 0, "y": 0, "w": 1000, "h": 100},
            "columns": "50% 50%",
            "rows": "1fr",
        })
        result = grid("test", spec)
        assert "error" not in result
        assert result["r0c0"]["w"] == 500
        assert result["r0c1"]["w"] == 500

    def test_repeat_spec_works(self):
        spec = json.dumps({
            "area": {"x": 0, "y": 0, "w": 900, "h": 100},
            "columns": "repeat(3, 1fr)",
            "rows": "1fr",
        })
        result = grid("test", spec)
        assert "error" not in result
        assert result["r0c0"]["w"] == 300
        assert result["r0c1"]["w"] == 300
        assert result["r0c2"]["w"] == 300


# ---------------------------------------------------------------------------
# compute_grid: integration tests for new syntax
# ---------------------------------------------------------------------------

class TestComputeGridIntegration:
    """End-to-end compute_grid with new syntax."""

    def test_percent_columns(self):
        result = compute_grid({
            "area": {"x": 0, "y": 0, "w": 1000, "h": 100},
            "columns": "50% 50%",
            "rows": "1fr",
            "gap": 0,
        })
        assert result["r0c0"]["w"] == 500
        assert result["r0c1"]["x"] == 500

    def test_repeat_with_areas(self):
        result = compute_grid({
            "area": {"x": 0, "y": 0, "w": 900, "h": 300},
            "columns": "repeat(3, 1fr)",
            "rows": "repeat(2, 1fr)",
            "gap": 0,
            "areas": [
                ["a", "b", "c"],
                ["d", "e", "f"],
            ],
        })
        assert result["a"]["w"] == 300
        assert result["b"]["x"] == 300
        assert result["d"]["y"] == 150

    def test_issue_282_reproduction(self):
        """Exact reproduction from the issue — must not raise."""
        result = compute_grid({
            "area": {"x": 0, "y": 0, "w": 1000, "h": 100},
            "columns": "50% 50%",
            "rows": "1fr",
            "gap": 0,
        })
        assert result["r0c0"]["w"] == 500
        assert result["r0c1"]["w"] == 500
