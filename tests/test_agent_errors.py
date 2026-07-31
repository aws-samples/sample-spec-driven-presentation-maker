# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for agent error classification, including parity with the TS mirror.

agent/errors.py and web-ui/src/lib/agentErrors.ts are intentional mirror
implementations. The parity test parses the TS source so a code added or
renamed on one side fails CI until the other side matches.
"""

import importlib.util
import re
from pathlib import Path

_root = Path(__file__).resolve().parent.parent

# Load agent/errors.py without adding agent/ to sys.path — agent/tools/
# would shadow the mcp-server tools package other test modules import.
_spec = importlib.util.spec_from_file_location("agent_errors", _root / "agent" / "errors.py")
_errors = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_errors)

AUTH = _errors.AUTH
BAD_INPUT = _errors.BAD_INPUT
CONVERSATION_TOO_LONG = _errors.CONVERSATION_TOO_LONG
INTERNAL = _errors.INTERNAL
MAX_OUTPUT = _errors.MAX_OUTPUT
MODEL_NOT_READY = _errors.MODEL_NOT_READY
SERVICE_UNAVAILABLE = _errors.SERVICE_UNAVAILABLE
THROTTLED = _errors.THROTTLED
TIMEOUT = _errors.TIMEOUT
_PATTERNS = _errors._PATTERNS
classify_error = _errors.classify_error
error_event = _errors.error_event

_TS_SOURCE = _root / "web-ui" / "src" / "lib" / "agentErrors.ts"


class TestClassifyError:
    def test_throttling(self):
        assert classify_error("ThrottlingException: rate exceeded") == THROTTLED

    def test_conversation_too_long(self):
        assert classify_error("Too much media in conversation") == CONVERSATION_TOO_LONG

    def test_timeout(self):
        assert classify_error("ModelTimeoutException after 60s") == TIMEOUT

    def test_auth_from_exception(self):
        assert classify_error(Exception("ExpiredToken")) == AUTH

    def test_max_output_tokens(self):
        assert classify_error(
            "MaxTokensReachedException: Model stopped generating due to maximum token limit."
        ) == MAX_OUTPUT

    def test_unknown_is_internal(self):
        assert classify_error("mystery failure") == INTERNAL


class TestErrorEvent:
    def test_shape(self):
        ev = error_event(Exception("ThrottlingException: x"))
        assert ev == {"status": "error", "code": THROTTLED, "error": "ThrottlingException: x"}

    def test_explicit_code_wins(self):
        ev = error_event("No JWT token", code=AUTH)
        assert ev["code"] == AUTH


class TestTypeScriptParity:
    """Guard against drift between agent/errors.py and lib/agentErrors.ts."""

    def test_all_python_codes_exist_in_ts(self):
        ts = _TS_SOURCE.read_text()
        py_codes = {
            CONVERSATION_TOO_LONG, THROTTLED, TIMEOUT, MODEL_NOT_READY,
            SERVICE_UNAVAILABLE, AUTH, BAD_INPUT, MAX_OUTPUT, INTERNAL,
        }
        for code in py_codes:
            assert f'"{code}"' in ts, f"code {code!r} missing from agentErrors.ts"

    def test_ts_has_no_extra_codes(self):
        ts = _TS_SOURCE.read_text()
        # AgentErrorCode union: | "code" lines
        union = re.search(r"export type AgentErrorCode =\s*((?:\s*\|\s*\"[a-z_]+\")+)", ts)
        assert union, "AgentErrorCode union not found in agentErrors.ts"
        ts_codes = set(re.findall(r'"([a-z_]+)"', union.group(1)))
        py_codes = {
            CONVERSATION_TOO_LONG, THROTTLED, TIMEOUT, MODEL_NOT_READY,
            SERVICE_UNAVAILABLE, AUTH, BAD_INPUT, MAX_OUTPUT, INTERNAL,
        }
        assert ts_codes == py_codes, (
            f"code sets differ — TS only: {ts_codes - py_codes}, Python only: {py_codes - ts_codes}"
        )

    def test_pattern_needles_match(self):
        """Each Python pattern needle must appear in the TS PATTERNS table."""
        ts = _TS_SOURCE.read_text()
        for needles, _code in _PATTERNS:
            for needle in needles:
                assert f'"{needle}"' in ts, f"pattern needle {needle!r} missing from agentErrors.ts"
