# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Template listing and analysis via Storage ABC.

Templates are stored in S3 with server-side encryption (SSE-S3).
Public access is blocked at the bucket level. See infra/ CDK stacks for bucket policies.
"""

import json
from typing import Any

from storage import Storage


def list_templates(storage: Storage) -> dict[str, Any]:
    """List all available templates.

    Args:
        storage: Storage backend instance.

    Returns:
        Dict with list of templates (name, description, isDefault).
    """
    templates = storage.list_templates()
    return {
        "templates": [
            {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "isDefault": t.get("isDefault", False),
            }
            for t in templates
        ]
    }


def analyze_template(template_name: str, storage: Storage) -> dict[str, Any]:
    """Return pre-analyzed template information from DDB.

    Args:
        template_name: Template name from list_templates.
        storage: Storage backend instance.

    Returns:
        Dict with layouts, theme_colors, fonts from pre-analysis.

    Raises:
        ValueError: If template not found or analysis not available.
    """
    templates = storage.list_templates()
    normalized = template_name.removesuffix(".pptx")
    tmpl = None
    for t in templates:
        if t.get("name") == normalized:
            tmpl = t
            break
    if not tmpl:
        available = [t.get("name", "") for t in templates]
        raise ValueError(
            f"Template '{template_name}' not found. Available: {', '.join(available)}"
        )

    analysis_raw = tmpl.get("analysisJson", "")
    if not analysis_raw or analysis_raw == "{}":
        # No pre-analysis — run analysis on the fly
        import tempfile
        from pathlib import Path

        from sdpm.analyzer import analyze_template as _analyze

        s3_key = tmpl.get("s3Key", "")
        if not s3_key:
            raise ValueError(f"Template '{template_name}' has no s3Key.")
        data = storage.download_file(key=s3_key)
        tmp = Path(tempfile.mkdtemp())
        tpl_path = tmp / "template.pptx"
        tpl_path.write_bytes(data)
        analysis = _analyze(tpl_path)
    else:
        analysis = json.loads(analysis_raw) if isinstance(analysis_raw, str) else analysis_raw
    analysis["fonts"] = tmpl.get("fonts", {})
    analysis["templateName"] = template_name
    return analysis
