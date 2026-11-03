# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared package — DDB schema, authorization, preview, and review logic.

Used by api/ and servers/remote/ to avoid duplication.
- schema: DynamoDB key conventions
- authz: deck access authorization
- artifact_keys: key layout of deck artifacts (previews, compose, HTML) and the latest-epoch selector
- review: change request contract of the Web UI comment tool
- user_library: the user's style / template library (S3 layout, pins, template lists)

Upload file conversion (PDF/DOCX/XLSX/PPTX → Markdown/JSON) lives in the core,
``sdpm.tools.attachment.ingest``.
"""
