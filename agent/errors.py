# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Error classification for agent stream errors.

Error events carry a stable ``code`` so the UI can map to a user-facing
message without string-matching raw exception text (which breaks whenever
an SDK rewords an exception).
"""

# Stable error codes shared with the web UI (web-ui/src/lib/agentErrors.ts).
CONVERSATION_TOO_LONG = "conversation_too_long"
THROTTLED = "throttled"
TIMEOUT = "timeout"
MODEL_NOT_READY = "model_not_ready"
SERVICE_UNAVAILABLE = "service_unavailable"
AUTH = "auth"
BAD_INPUT = "bad_input"
MAX_OUTPUT = "max_output"
INTERNAL = "internal"

_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("Too much media", "too long"), CONVERSATION_TOO_LONG),
    (("ThrottlingException", "throttl"), THROTTLED),
    (("ModelTimeoutException", "timed out", "timeout"), TIMEOUT),
    (("ModelNotReadyException", "not ready"), MODEL_NOT_READY),
    (("ServiceUnavailable",), SERVICE_UNAVAILABLE),
    (("ExpiredToken", "AccessDenied", "UnrecognizedClient", "invalid_token"), AUTH),
    (("ValidationException",), BAD_INPUT),
    (("MaxTokensReachedException", "maximum token limit"), MAX_OUTPUT),
]


def classify_error(exc: BaseException | str) -> str:
    """Map an exception (or its message) to a stable error code."""
    msg = str(exc)
    for needles, code in _PATTERNS:
        if any(n in msg for n in needles):
            return code
    return INTERNAL


def error_event(exc: BaseException | str, code: str | None = None) -> dict:
    """Build a stream error event: {status, code, error}."""
    return {
        "status": "error",
        "code": code or classify_error(exc),
        "error": str(exc),
    }
