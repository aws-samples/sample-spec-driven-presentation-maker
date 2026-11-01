# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared package — DDB schema, authorization, preview, and review logic.

Used by api/ and servers/remote/ to avoid duplication.
- schema: DynamoDB key conventions
- authz: deck access authorization
- preview: slide preview key resolution
- html_artifacts: S3 key layout of HTML deck artifacts
- review: change request contract of the Web UI comment tool

Upload file conversion (PDF/DOCX/XLSX/PPTX → Markdown/JSON) lives in the core,
``sdpm.tools.attachment.ingest``.
"""
