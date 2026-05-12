# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Template listing and analysis via Storage ABC.

Templates are stored in S3 with server-side encryption (SSE-S3).
Public access is blocked at the bucket level. See infra/ CDK stacks for bucket policies.
"""

import json
from typing import Any

from storage import Storage


def list_templates(storage: Storage, user_id: str = "") -> dict[str, Any]:
    """List all available templates (builtin + user).

    Args:
        storage: Storage backend instance.
        user_id: User identifier (for user templates).

    Returns:
        Dict with list of templates (name, source, description, fonts, layout_count).
    """
    templates = []

    # Builtin templates
    for t in storage.list_templates():
        analysis = {}
        raw = t.get("analysisJson", "")
        if raw and raw != "{}":
            analysis = json.loads(raw) if isinstance(raw, str) else raw
        templates.append({
            "name": t.get("name", ""),
            "source": "builtin",
            "description": t.get("description", ""),
            "fonts": t.get("fonts", {}),
            "layout_count": len(analysis.get("layouts", [])),
        })

    # User templates
    if user_id:
        for t in storage.list_user_templates(user_id):
            analysis = {}
            raw = t.get("analysisJson", "")
            if raw and raw != "{}":
                analysis = json.loads(raw) if isinstance(raw, str) else raw
            templates.append({
                "name": t.get("name", ""),
                "source": "user",
                "description": t.get("description", ""),
                "fonts": t.get("fonts", {}),
                "layout_count": len(analysis.get("layouts", [])),
            })

    return {"templates": templates}


def analyze_template(template_name: str, storage: Storage, user_id: str = "") -> dict[str, Any]:
    """Return pre-analyzed template information from DDB.

    Searches user templates first, then builtin.

    Args:
        template_name: Template name from list_templates.
        storage: Storage backend instance.
        user_id: User identifier (for user template lookup).

    Returns:
        Dict with layouts, theme_colors, fonts from pre-analysis.

    Raises:
        ValueError: If template not found or analysis not available.
    """
    normalized = template_name.removesuffix(".pptx")

    # Check user templates first
    if user_id:
        user_meta = storage.get_user_template_metadata(user_id, normalized)
        if user_meta:
            analysis_raw = user_meta.get("analysisJson", "")
            if analysis_raw and analysis_raw != "{}":
                analysis = json.loads(analysis_raw) if isinstance(analysis_raw, str) else analysis_raw
            else:
                # Analyze on the fly
                import tempfile
                from pathlib import Path
                from sdpm.analyzer import analyze_template as _analyze
                data = storage.download_user_template(user_id, normalized)
                tmp = Path(tempfile.mkdtemp())
                tpl_path = tmp / "template.pptx"
                tpl_path.write_bytes(data)
                analysis = _analyze(tpl_path)
            analysis["fonts"] = user_meta.get("fonts", {})
            analysis["templateName"] = template_name
            return analysis

    # Builtin templates
    templates = storage.list_templates()
    tmpl = None
    for t in templates:
        if t.get("name") == normalized:
            tmpl = t
            break
    if not tmpl:
        available = [t.get("name", "") for t in templates]
        if user_id:
            user_names = [t.get("name", "") for t in storage.list_user_templates(user_id)]
            available.extend(user_names)
        raise ValueError(
            f"Template '{template_name}' not found. Available: {', '.join(available)}"
        )

    analysis_raw = tmpl.get("analysisJson", "")
    if not analysis_raw or analysis_raw == "{}":
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
