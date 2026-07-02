# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Lightweight per-tool timing for measuring parallel MCP tool performance.

OPT-IN and side-effect free: does nothing unless the environment variable
``SDPM_PERF_LOG`` points at a writable path. When set, each wrapped tool call
appends one JSON line recording the process PID, tool name, wall-clock duration,
and a timestamp — enough to answer:

  * Are parallel composer sub-agents really running in separate processes?
    (group lines by ``pid`` — distinct PIDs overlapping in time = true parallel)
  * Which tool actually dominates wall-clock? (compare ``t_total_ms`` by ``tool``)

This module is intentionally isolated so it can be dropped in a measurement
branch and removed cleanly afterwards.
"""

from __future__ import annotations

import functools
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable


def _perf_path() -> str | None:
    """Return the perf log path if measurement is enabled, else None."""
    return os.environ.get("SDPM_PERF_LOG") or None


def record(event: dict[str, Any]) -> None:
    """Append one JSON line to the perf log. No-op when disabled or on error."""
    path = _perf_path()
    if not path:
        return
    event.setdefault("pid", os.getpid())
    event.setdefault("ts", datetime.now(timezone.utc).isoformat())
    try:
        # append mode + newline: concurrent processes each write whole lines;
        # POSIX append writes are atomic for small payloads, so lines don't tear.
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass  # measurement must never break the tool


def timed(tool_name: str) -> Callable:
    """Decorator: record {tool, pid, t_total_ms, ts, deck_id?, slug?} per call.

    When SDPM_PERF_LOG is unset the wrapper adds only a perf_counter pair and an
    env lookup (sub-microsecond) — negligible relative to any real tool body.
    """

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _perf_path():
                return fn(*args, **kwargs)
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                dt = (time.perf_counter() - t0) * 1000.0
                event: dict[str, Any] = {
                    "tool": tool_name,
                    "t_total_ms": round(dt, 1),
                }
                # Best-effort context from common kwargs (never raises).
                for key in ("deck_id", "slug"):
                    if key in kwargs:
                        event[key] = kwargs[key]
                record(event)

        return wrapper

    return deco
