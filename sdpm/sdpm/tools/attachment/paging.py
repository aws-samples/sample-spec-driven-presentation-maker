# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""UTF-8 byte paging with line numbering (Phase 0-11).

Contract:
- offset: 0-based UTF-8 byte offset into the canonical projection
- limit: max total UTF-8 bytes for all TextContent parts (header + body)
- Prefers newline boundaries; splits only at code-point boundary for huge lines
- Absolute 1-based line numbers are stable across pages
- nextOffset > offset guaranteed when not at EOF (prevents infinite loops)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sdpm.tools.attachment.limits import PAGING_MAX_LIMIT, PAGING_MIN_LIMIT


@dataclass
class PageResult:
    """Result of paging a text projection."""

    header: dict[str, Any]
    body: str  # line-numbered text
    raw_body_bytes: int  # UTF-8 bytes of body (for budget accounting)


class PagingError(Exception):
    """Invalid paging parameters."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_paging_params(offset: int, limit: int) -> int:
    """Validate and normalize paging parameters. Returns effective limit."""
    if offset < 0:
        raise PagingError("INVALID_OFFSET", f"offset must be >= 0, got {offset}")
    if limit < PAGING_MIN_LIMIT:
        raise PagingError("INVALID_LIMIT", f"limit must be >= {PAGING_MIN_LIMIT}, got {limit}")
    return min(limit, PAGING_MAX_LIMIT)


def _is_continuation_byte(b: int) -> bool:
    """Check if a byte is a UTF-8 continuation byte (10xxxxxx)."""
    return (b & 0xC0) == 0x80


def _find_code_point_boundary(data: bytes, pos: int) -> int:
    """Find the nearest code-point boundary at or before pos."""
    while 0 < pos < len(data) and _is_continuation_byte(data[pos]):
        pos -= 1
    return pos


def page_text(
    data: bytes,
    offset: int,
    limit: int,
    *,
    source: str = "",
    file_name: str = "",
    media_type: str = "",
    kind: str = "text",
    extra_header_fields: dict[str, Any] | None = None,
) -> PageResult:
    """Page a UTF-8 text blob with line numbering.

    Args:
        data: Full canonical projection as UTF-8 bytes.
        offset: 0-based byte offset to start reading.
        limit: Max bytes for header + body combined.
        source: Source identifier for header.
        file_name: File name for header.
        media_type: Media type for header.
        kind: Kind field for header (text/pptx/image).
        extra_header_fields: Additional fields to include in header JSON.

    Returns:
        PageResult with header dict, numbered body text, and byte count.

    Raises:
        PagingError: On invalid offset (continuation byte, negative, etc).
    """
    effective_limit = validate_paging_params(offset, limit)
    total_bytes = len(data)

    # Validate offset is not a continuation byte
    if offset < total_bytes and _is_continuation_byte(data[offset]):
        raise PagingError(
            "INVALID_OFFSET",
            f"offset {offset} falls on a UTF-8 continuation byte"
        )

    # EOF case
    if offset >= total_bytes:
        header = _build_header(
            source=source, file_name=file_name, media_type=media_type, kind=kind,
            offset=offset, next_offset=offset, total_bytes=total_bytes,
            start_line=0, end_line=0,
            starts_mid_line=False, ends_mid_line=False, truncated=False,
            extra=extra_header_fields,
        )
        header_json = json.dumps(header, ensure_ascii=False, separators=(",", ":"))
        return PageResult(header=header, body="", raw_body_bytes=0)

    # Count lines before offset to determine starting line number
    start_line = data[:offset].count(b"\n") + 1
    starts_mid_line = offset > 0 and data[offset - 1:offset] != b"\n"

    # Budget against a worst-case final header so header + body never exceeds limit.
    total_lines = data.count(b"\n") + 1
    preliminary_header = _build_header(
        source=source, file_name=file_name, media_type=media_type, kind=kind,
        offset=offset, next_offset=total_bytes, total_bytes=total_bytes,
        start_line=start_line, end_line=total_lines,
        starts_mid_line=starts_mid_line, ends_mid_line=False, truncated=False,
        extra=extra_header_fields,
    )
    header_json = json.dumps(preliminary_header, ensure_ascii=False, separators=(",", ":"))
    header_bytes = len(header_json.encode("utf-8"))

    # Budget remaining for body (including line-number prefixes)
    body_budget = effective_limit - header_bytes
    if body_budget < 1:
        # Header alone exceeds budget — return header only with empty body
        header = _build_header(
            source=source, file_name=file_name, media_type=media_type, kind=kind,
            offset=offset, next_offset=offset, total_bytes=total_bytes,
            start_line=start_line, end_line=start_line,
            starts_mid_line=starts_mid_line, ends_mid_line=False, truncated=True,
            extra=extra_header_fields,
        )
        return PageResult(header=header, body="", raw_body_bytes=0)

    # Extract body respecting budget and boundaries
    body_lines: list[str] = []
    current_line = start_line
    pos = offset
    body_bytes_used = 0
    ends_mid_line = False
    last_pos = pos

    while pos < total_bytes and body_bytes_used < body_budget:
        # Find end of current line
        newline_idx = data.find(b"\n", pos)
        if newline_idx == -1:
            # Last line without newline
            line_end = total_bytes
        else:
            line_end = newline_idx + 1  # include the newline

        # Decode the line
        line_bytes = data[pos:line_end]
        line_text = line_bytes.decode("utf-8", errors="replace")

        # Format with line number
        if starts_mid_line and pos == offset:
            # Continuation of a line split from previous page
            numbered = f"{current_line}→ {line_text}"
        else:
            numbered = f"{current_line}: {line_text}"

        numbered_bytes = len(numbered.encode("utf-8"))

        if body_bytes_used + numbered_bytes <= body_budget:
            body_lines.append(numbered)
            body_bytes_used += numbered_bytes
            last_pos = line_end
            if newline_idx != -1:
                current_line += 1
            pos = line_end
        else:
            # Line doesn't fit entirely — try to fit partial (code-point boundary)
            remaining_budget = body_budget - body_bytes_used
            # Account for line-number prefix
            if starts_mid_line and pos == offset:
                prefix = f"{current_line}→ "
            else:
                prefix = f"{current_line}: "
            prefix_bytes = len(prefix.encode("utf-8"))

            if remaining_budget <= prefix_bytes:
                # Can't even fit the prefix
                break

            available_for_content = remaining_budget - prefix_bytes
            # Take as many bytes as we can at code-point boundary
            partial_end = pos + available_for_content
            if partial_end > line_end:
                partial_end = line_end
            # Back up to code-point boundary
            partial_end = _find_code_point_boundary(data, partial_end)
            if partial_end <= pos:
                # Can't fit even one code point — must return at least one
                # Find next code-point start
                cp_end = pos + 1
                while cp_end < total_bytes and _is_continuation_byte(data[cp_end]):
                    cp_end += 1
                partial_end = cp_end

            partial_text = data[pos:partial_end].decode("utf-8", errors="replace")
            numbered = f"{prefix}{partial_text}"
            body_lines.append(numbered)
            body_bytes_used += len(numbered.encode("utf-8"))
            last_pos = partial_end
            ends_mid_line = partial_end < line_end
            pos = partial_end
            break

    # Determine end state
    if last_pos >= total_bytes:
        truncated = False
        next_offset = total_bytes
        end_line = current_line
    else:
        truncated = True
        next_offset = last_pos
        end_line = current_line
        # Check if we ended mid-line
        if last_pos < total_bytes and data[last_pos - 1:last_pos] != b"\n":
            ends_mid_line = True

    # Guarantee: nextOffset > offset when not at EOF (prevent infinite loops)
    if truncated and next_offset <= offset:
        # Force at least one code point forward
        cp_end = offset + 1
        while cp_end < total_bytes and _is_continuation_byte(data[cp_end]):
            cp_end += 1
        next_offset = min(cp_end, total_bytes)

    # Build final header
    header = _build_header(
        source=source, file_name=file_name, media_type=media_type, kind=kind,
        offset=offset, next_offset=next_offset, total_bytes=total_bytes,
        start_line=start_line, end_line=end_line,
        starts_mid_line=starts_mid_line, ends_mid_line=ends_mid_line,
        truncated=truncated, extra=extra_header_fields,
    )

    body_text = "".join(body_lines)
    return PageResult(header=header, body=body_text, raw_body_bytes=body_bytes_used)


def _build_header(
    *,
    source: str,
    file_name: str,
    media_type: str,
    kind: str,
    offset: int,
    next_offset: int,
    total_bytes: int,
    start_line: int,
    end_line: int,
    starts_mid_line: bool,
    ends_mid_line: bool,
    truncated: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the compact JSON header per Phase 0-11 contract."""
    header: dict[str, Any] = {
        "version": 1,
        "source": source,
        "fileName": file_name,
        "mediaType": media_type,
        "kind": kind,
        "page": {
            "offset": offset,
            "nextOffset": next_offset,
            "totalBytes": total_bytes,
            "startLine": start_line,
            "endLine": end_line,
            "startsMidLine": starts_mid_line,
            "endsMidLine": ends_mid_line,
            "truncated": truncated,
        },
    }
    if extra:
        header.update(extra)
    return header
