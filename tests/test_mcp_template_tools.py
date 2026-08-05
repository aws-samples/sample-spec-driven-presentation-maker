# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for MCP template listing behavior."""

from tools.template import list_templates


class TemplateStorage:
    """Minimal storage double for list_templates tests."""

    def __init__(self, notes: dict[str, str] | None = None) -> None:
        self.notes = notes or {}
        self.notes_user_id = ""

    def get_builtin_template_notes(self, user_id: str) -> dict[str, str]:
        self.notes_user_id = user_id
        return self.notes

    def list_templates(self) -> list[dict]:
        return [
            {
                "name": "blank-dark",
                "description": "Shared description",
                "fonts": {},
                "analysisJson": "{}",
            },
            {
                "name": "blank-light",
                "description": "Light shared description",
                "fonts": {},
                "analysisJson": "{}",
            },
        ]

    def list_user_templates(self, user_id: str) -> list[dict]:
        return []


def test_list_templates_overlays_builtin_description_with_user_note() -> None:
    storage = TemplateStorage({"blank-dark": "Use for internal reviews"})

    result = list_templates(storage, user_id="user-123")

    descriptions = {item["name"]: item["description"] for item in result["templates"]}
    assert descriptions == {
        "blank-dark": "Use for internal reviews",
        "blank-light": "Light shared description",
    }
    assert storage.notes_user_id == "user-123"


def test_list_templates_without_user_keeps_shared_descriptions() -> None:
    storage = TemplateStorage({"blank-dark": "Should not be read"})

    result = list_templates(storage)

    descriptions = {item["name"]: item["description"] for item in result["templates"]}
    assert descriptions["blank-dark"] == "Shared description"
    assert storage.notes_user_id == ""


class QueryTable:
    """DynamoDB table double that records query parameters."""

    def __init__(self) -> None:
        self.query_kwargs: dict = {}

    def query(self, **kwargs: object) -> dict:
        self.query_kwargs = kwargs
        return {
            "Items": [
                {
                    "PK": "USER#user-123",
                    "SK": "BUILTIN_NOTE#blank-dark",
                    "description": "Use for internal reviews",
                },
            ],
        }


def test_aws_storage_get_builtin_template_notes_maps_ddb_items() -> None:
    from storage.aws import AwsStorage

    table = QueryTable()
    storage = AwsStorage(table, object(), "pptx-bucket", "resource-bucket")

    notes = storage.get_builtin_template_notes("user-123")

    assert notes == {"blank-dark": "Use for internal reviews"}
    assert table.query_kwargs["ExpressionAttributeValues"] == {
        ":pk": "USER#user-123",
        ":prefix": "BUILTIN_NOTE#",
    }


class AnalyzeTemplateStorage:
    """Storage double for analyze_template tests with configurable analysisJson."""

    def __init__(self, analysis_json: str, template_bytes: bytes | None = None) -> None:
        self._analysis_json = analysis_json
        self._template_bytes = template_bytes

    def get_user_template_metadata(self, user_id: str, name: str) -> dict | None:
        return None

    def list_templates(self) -> list[dict]:
        return [
            {
                "name": "blank-dark",
                "description": "Dark template",
                "fonts": {"fullwidth": "Noto Sans JP", "halfwidth": "Noto Sans"},
                "analysisJson": self._analysis_json,
                "s3Key": "templates/blank-dark.pptx",
            },
        ]

    def list_user_templates(self, user_id: str) -> list[dict]:
        return []

    def download_file(self, key: str) -> bytes:
        if self._template_bytes is None:
            raise RuntimeError("download_file called but no template bytes configured")
        return self._template_bytes


def test_analyze_template_cache_hit_with_slide_size() -> None:
    """When cached analysisJson contains slide_size, it is returned directly."""
    import json
    from tools.template import analyze_template

    cached = json.dumps({
        "slide_size": {"width": 1280, "height": 720},
        "layouts": [{"name": "Blank"}],
        "theme_colors": {"accent1": "#FF0000"},
    })
    storage = AnalyzeTemplateStorage(cached)
    result = analyze_template("blank-dark", storage)

    assert result["slide_size"] == {"width": 1280, "height": 720}
    assert result["templateName"] == "blank-dark"


def test_analyze_template_fallback_when_slide_size_missing() -> None:
    """When cached analysisJson lacks slide_size, re-analyze from S3."""
    import json
    from pathlib import Path
    from tools.template import analyze_template

    # Cached data without slide_size (old format)
    cached = json.dumps({
        "layouts": [{"name": "Blank"}],
        "theme_colors": {"accent1": "#FF0000"},
    })

    # Use a real template for on-the-fly analysis
    template_path = Path(__file__).parent.parent / "sdpm" / "templates" / "blank-dark.pptx"
    if not template_path.exists():
        import pytest
        pytest.skip("blank-dark.pptx not available")

    template_bytes = template_path.read_bytes()
    storage = AnalyzeTemplateStorage(cached, template_bytes)
    result = analyze_template("blank-dark", storage)

    # Should have slide_size from on-the-fly analysis
    assert "slide_size" in result
    assert result["slide_size"]["width"] > 0
    assert result["slide_size"]["height"] > 0
    assert result["templateName"] == "blank-dark"
