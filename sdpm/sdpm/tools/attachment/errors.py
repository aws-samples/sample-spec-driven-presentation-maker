# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Structured error types for the attachment pipeline."""

from __future__ import annotations

from typing import Any


class AttachmentError(Exception):
    """Base structured error raised by attachment tools."""

    def __init__(self, code: str, message: str, *, retryable: bool = False, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.details:
            d["details"] = self.details
        return d


class ImportIncomplete(AttachmentError):
    """Deadline reached before import completed — retryable with progress."""

    next_action: str = "Call import_attachment again with exactly the same source, deck_id, and filename."

    def __init__(self, message: str = "Import did not complete within deadline.", completed_stages: list[str] | None = None) -> None:
        super().__init__(code="IMPORT_INCOMPLETE", message=message, retryable=True)
        self.completed_stages = completed_stages or []

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["completedStages"] = self.completed_stages
        d["nextAction"] = self.next_action
        return d


# Terminal errors — not retryable

class SourceNotFound(AttachmentError):
    """Source does not exist or has expired."""

    def __init__(self, source: str) -> None:
        super().__init__(code="SOURCE_NOT_FOUND", message=f"Source not found: {source}")


class SourceAccessDenied(AttachmentError):
    """Caller does not own the source."""

    def __init__(self, source: str) -> None:
        super().__init__(code="SOURCE_ACCESS_DENIED", message=f"Access denied: {source}")


class SourceTypeMismatch(AttachmentError):
    """Content-Type and magic bytes disagree."""

    def __init__(self, detail: str) -> None:
        super().__init__(code="SOURCE_TYPE_MISMATCH", message=detail)


class SourceLimitExceeded(AttachmentError):
    """Source exceeds resource limits (size, pages, etc.)."""

    def __init__(self, detail: str) -> None:
        super().__init__(code="SOURCE_LIMIT_EXCEEDED", message=detail)


class ImportLimitExceeded(AttachmentError):
    """Import processing exceeds resource limits."""

    def __init__(self, detail: str) -> None:
        super().__init__(code="IMPORT_LIMIT_EXCEEDED", message=detail)


class ImportConversionFailed(AttachmentError):
    """Conversion failed with a terminal error."""

    def __init__(self, detail: str) -> None:
        super().__init__(code="IMPORT_CONVERSION_FAILED", message=detail)


class ImportConflict(AttachmentError):
    """Manifest mismatch on existing importKey."""

    def __init__(self, import_key: str) -> None:
        super().__init__(code="IMPORT_CONFLICT", message=f"Conflict on importKey: {import_key}")


class SourceValidationError(AttachmentError):
    """Source fails validation (path traversal, invalid scheme, etc.)."""

    def __init__(self, detail: str) -> None:
        super().__init__(code="SOURCE_VALIDATION_ERROR", message=detail)


class SSRFBlocked(AttachmentError):
    """URL targets private/reserved network address."""

    def __init__(self, detail: str) -> None:
        super().__init__(code="SSRF_BLOCKED", message=detail)
