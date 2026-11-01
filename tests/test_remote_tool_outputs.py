# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Remote MCP tools: the declared return type matches what the tool returns.

FastMCP builds each tool's output schema from its return annotation and validates
the result against it, so a tool declared ``-> str`` that returns a dict fails on
every call (read_attachment did, 2026-10-08 → 2026-11). The first test drives
read_attachment through a real MCP client session; the second checks every
``@offloaded_tool`` body statically, comparing the declared return type with what
each ``return`` statement produces.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
import json
import os
import typing
from pathlib import Path
from unittest.mock import patch

from mcp.shared.memory import create_connected_server_and_client_session

_ROOT = Path(__file__).resolve().parents[1]
_SERVER = _ROOT / "servers" / "remote" / "server.py"

os.environ.setdefault("DECKS_TABLE", "test-table")
os.environ.setdefault("PPTX_BUCKET", "test-pptx")
os.environ.setdefault("RESOURCE_BUCKET", "test-resource")

_spec = importlib.util.spec_from_file_location("remote_server_outputs_under_test", _SERVER)
remote_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote_server)


class _ReadStorage:
    """Owned S3 upload plus the attachment-cache writes read_attachment makes."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.objects: dict[str, bytes] = {}

    def head_object(self, key: str) -> dict:
        if key in self.objects:
            return {"ContentLength": len(self.objects[key])}
        return {"ContentLength": len(self.data), "ContentType": "text/plain", "ETag": '"etag"'}

    def download_file_from_pptx_bucket(self, key: str) -> bytes:
        if key.startswith("attachment-cache/"):
            return self.objects[key]
        return self.data

    def upload_file_if_absent(self, key, data, _content_type, _checksum, _tagging) -> bool:
        if key in self.objects:
            return False
        self.objects[key] = data
        return True

    def upload_file(self, key, data, _content_type="", _tagging="") -> None:
        self.objects[key] = data


def test_read_attachment_over_mcp_returns_structured_result() -> None:
    source = "uploads/user-1/123e4567-e89b-12d3-a456-426614174000/report.txt"

    async def call():
        async with create_connected_server_and_client_session(remote_server.mcp) as session:
            return await session.call_tool("read_attachment", {"source": source})

    with (
        patch.object(remote_server, "_storage", _ReadStorage(b"hello\nworld\n")),
        patch.object(remote_server, "_get_user_id", return_value="user-1"),
    ):
        result = asyncio.run(call())

    assert not result.isError, result.content[0].text
    assert result.structuredContent["header"]["fileName"] == "report.txt"
    assert "hello" in result.structuredContent["body"]
    assert json.loads(result.content[0].text)["header"]["source"] == source


# --- Static check over every @offloaded_tool ---


def _base(tp) -> type | None:
    """``dict[str, Any]`` → dict, ``list`` → list, ``str`` → str; anything else as is."""
    return typing.get_origin(tp) or tp


def _tool_defs(tree: ast.Module) -> list[ast.FunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(isinstance(d, ast.Name) and d.id == "offloaded_tool" for d in node.decorator_list)
    ]


def _returns(fn: ast.FunctionDef):
    """``return <value>`` statements of ``fn`` itself (not of nested functions)."""
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _local_imports(fn: ast.FunctionDef) -> dict[str, object]:
    names: dict[str, object] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            module = importlib.import_module(node.module)
            for alias in node.names:
                if hasattr(module, alias.name):
                    names[alias.asname or alias.name] = getattr(module, alias.name)
    return names


def _returned_type(value: ast.expr, scope: dict[str, object]):
    """Type the expression produces, or None when it cannot be told statically."""
    if isinstance(value, ast.Constant) and isinstance(value.value, str) or isinstance(value, ast.JoinedStr):
        return str
    if isinstance(value, (ast.Dict, ast.DictComp)):
        return dict
    if isinstance(value, (ast.List, ast.ListComp)):
        return list
    if not isinstance(value, ast.Call):
        return None
    func = value.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if (func.value.id, func.attr) == ("json", "dumps"):
            return str
        target = getattr(scope.get(func.value.id), func.attr, None)
    elif isinstance(func, ast.Name):
        target = scope.get(func.id)
    else:
        return None
    if not callable(target):
        return None
    return typing.get_type_hints(target).get("return")


def test_every_remote_tool_returns_its_declared_type() -> None:
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    registered = {t.name: t for t in remote_server.mcp._tool_manager.list_tools()}
    module_scope = vars(remote_server)
    mismatches: list[str] = []
    checked: set[str] = set()

    for fn in _tool_defs(tree):
        tool = registered.get(fn.name)
        if tool is None:  # registered only when its backend is configured (search_slides)
            continue
        declared = typing.get_type_hints(tool.fn)["return"]
        scope = {**module_scope, **_local_imports(fn)}
        for ret in _returns(fn):
            produced = _returned_type(ret.value, scope)
            if produced is None:
                continue
            checked.add(fn.name)
            if _base(produced) is not _base(declared):
                mismatches.append(f"{fn.name} (line {ret.lineno}): declared {declared}, returns {produced}")

    assert not mismatches, "\n".join(mismatches)
    # The check is not vacuous: it saw the delegating tools this class of bug hides in.
    assert {"read_attachment", "import_attachment", "get_preview", "start_presentation"} <= checked
