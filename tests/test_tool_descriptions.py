# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tool descriptions are the one text every MCP client sends the model on every turn.

Contract: a description says when to call the tool (and names the guide that has the
details); the meaning of each argument lives on the argument itself (schema property
description); formats, examples and internal structures live in guides or role documents.
"""

import asyncio
import inspect
import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_LOCAL = _ROOT / "servers" / "local"

# Per-tool ceiling on the description text. run_python carries its helper list because
# a composer calls it on nearly every turn and must not pay a round trip to learn it.
_DESC_MAX = {"run_python": 700, "read_guides": 700, "hearing": 600}
_DESC_MAX_DEFAULT = 560
_TOTAL_MAX = 16_000  # description + schema, all tools, characters (~4K tokens); ACP adds hearing


_REMOTE = _ROOT / "servers" / "remote"


def _load(name: str, path: Path, extra_paths: list[Path]):
    # Load under a private module name: servers/local/server.py and
    # servers/remote/server.py share the name ``server``.
    import importlib.util

    added = [str(p) for p in extra_paths if str(p) not in sys.path]
    for p in reversed(added):
        sys.path.insert(0, p)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for p in added:
            sys.path.remove(p)


def _tools(module) -> dict:
    return {t.name: t for t in asyncio.run(module.mcp.list_tools())}


@pytest.fixture(scope="module")
def local_tools():
    return _tools(_load("sdpm_local_server_desc_test", _LOCAL / "server.py", [_LOCAL, _ROOT / "sdpm"]))


@pytest.fixture(scope="module")
def acp_tools():
    return _tools(_load("sdpm_acp_server_desc_test", _LOCAL / "server_acp.py", [_LOCAL, _ROOT / "sdpm"]))


@pytest.fixture(scope="module")
def remote_tools():
    from unittest.mock import MagicMock, patch

    pytest.importorskip("boto3")
    env = {
        "DECKS_TABLE": "decks-test", "PPTX_BUCKET": "pptx-test", "RESOURCE_BUCKET": "resource-test",
        "KB_SSM_PARAM": "/sdpm/kb-id", "VECTOR_BUCKET_NAME": "vectors-test",
        "VECTOR_INDEX_NAME": "index-test", "AWS_DEFAULT_REGION": "ap-northeast-1",
    }
    with patch.dict("os.environ", env), patch("boto3.client", lambda *a, **k: MagicMock()):
        try:
            module = _load("sdpm_remote_server_desc_test", _REMOTE / "server.py", [_ROOT, _REMOTE, _ROOT / "sdpm"])
        except Exception as e:  # pragma: no cover - environment-dependent
            pytest.skip(f"servers/remote/server.py not importable here: {e}")
    return _tools(module)


@pytest.fixture(scope="module", params=["local", "acp", "remote"])
def any_server_tools(request, local_tools, acp_tools, remote_tools):
    return {"local": local_tools, "acp": acp_tools, "remote": remote_tools}[request.param]


def test_every_argument_carries_a_description(any_server_tools):
    missing = []
    for name, tool in any_server_tools.items():
        for prop, schema in tool.inputSchema.get("properties", {}).items():
            if not schema.get("description"):
                missing.append(f"{name}.{prop}")
    assert not missing, missing


def test_descriptions_do_not_restate_arguments_or_returns(any_server_tools):
    offenders = [n for n, t in any_server_tools.items() if re.search(r"^\s*(Args|Returns):", t.description or "", re.M)]
    assert not offenders, offenders


def test_description_budget(any_server_tools):
    over = {
        n: len(t.description or "")
        for n, t in any_server_tools.items()
        if len(t.description or "") > _DESC_MAX.get(n, _DESC_MAX_DEFAULT)
    }
    assert not over, over
    sizes = {n: len(t.description or "") + len(json.dumps(t.inputSchema, ensure_ascii=False)) for n, t in any_server_tools.items()}
    assert sum(sizes.values()) <= _TOTAL_MAX, (sum(sizes.values()), sorted(sizes.items(), key=lambda kv: -kv[1]))


def test_guide_pointers_name_existing_guides(any_server_tools):
    guides = {p.stem for p in (_ROOT / "sdpm" / "references" / "guides").glob("*.md")}
    for name, tool in any_server_tools.items():
        for ref in re.findall(r'read_guides\(\[([^\]]*)\]\)', tool.description or ""):
            for g in re.findall(r'"([a-z-]+)"', ref):
                assert g in guides, f"{name} points at unknown guide {g}"


def test_read_guides_description_lists_the_catalogue(local_tools):
    doc = local_tools["read_guides"].description
    for g in (p.stem for p in (_ROOT / "sdpm" / "references" / "guides").glob("*.md")):
        assert g in doc, g


def test_entry_tools_are_the_only_ones_that_start_a_request(any_server_tools):
    starters = {n for n, t in any_server_tools.items() if re.search(r"\b[Cc]all (it|this) (first|before)|[Cc]all first|Start here", t.description or "")}
    entries = {"start_presentation", "start_composing", "start_style", "start_translation"}
    assert starters <= entries and "start_presentation" in starters, starters


def test_contract_functions_are_annotated_not_docstring_args():
    from sdpm import tools

    for name, fn in inspect.getmembers(tools, inspect.isfunction):
        if fn.__module__ != tools.__name__ or name.startswith("_"):
            continue
        for p in inspect.signature(fn).parameters.values():
            assert "Field(" in str(p.annotation) or "Annotated" in str(p.annotation), f"{name}.{p.name}"
