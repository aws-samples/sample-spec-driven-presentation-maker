# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared package — DDB schema, authorization, preview, and file ingestion logic.

Used by api/, mcp-server/, and mcp-local/ to avoid duplication.
- schema: DynamoDB key conventions
- authz: deck access authorization
- preview: slide preview key resolution
- ingest: upload file conversion pipeline (PDF/DOCX/XLSX/PPTX → Markdown/JSON)
"""
