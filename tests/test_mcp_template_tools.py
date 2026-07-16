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
