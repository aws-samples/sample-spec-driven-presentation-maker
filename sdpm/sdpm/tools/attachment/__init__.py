# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""sdpm.tools.attachment — Stateless attachment pipeline (Phase 1 foundation).

Architecture (ports-and-adapters):
    Core pipeline (this package) defines conversion, paging, validation, and
    commit logic. Adapters (Local/Remote) handle source materialization and
    storage specifics.

Modules:
    pipeline    — Main orchestrator: read/import dispatch
    paging      — UTF-8 byte paging with line numbering
    source      — Source validation and type detection
    fetcher     — Secure URL fetcher with DNS/IP pinning
    limits      — Resource limit constants and checks
    cache       — Stage cache identity and atomic publish
    bundle      — Import bundle commit contract
    errors      — Structured error types
"""

# Pipeline revision — bump when converter output, stage schema, or option
# normalization semantics change.
ATTACHMENT_PIPELINE_REVISION = 1


PPTX_GUIDE_INSTRUCTION = (
    "This PPTX can either be converted into an editable deck, or used as "
    "reference material for a new deck. "
    "If the user's intent is to edit this PPTX, call read_guides(['import-pptx']) "
    "and follow it exactly. "
    "If the intent is to use as reference, proceed with the normal briefing flow "
    "and call read_attachment with the marker source to access content. "
    "If the user's intent is ambiguous, use the `hearing` tool once to clarify "
    "before choosing."
)
