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
_DESC_MAX = {"run_python": 700, "read_guides": 700}
_DESC_MAX_DEFAULT = 560
_TOTAL_MAX = 14_000  # description + schema, all tools, characters (~3.5K tokens)


def _list_local_tools():
    # Load servers/local/server.py under a private name: other tests leave a
    # module called ``server`` (the remote one) in sys.modules.
    import importlib.util

    sys.path.insert(0, str(_LOCAL))
    sys.path.insert(0, str(_ROOT / "sdpm"))
    try:
        spec = importlib.util.spec_from_file_location("sdpm_local_server_under_test", _LOCAL / "server.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return asyncio.run(module.mcp.list_tools())
    finally:
        sys.path.remove(str(_LOCAL))
        sys.path.remove(str(_ROOT / "sdpm"))


@pytest.fixture(scope="module")
def local_tools():
    return {t.name: t for t in _list_local_tools()}


def test_every_argument_carries_a_description(local_tools):
    missing = []
    for name, tool in local_tools.items():
        for prop, schema in tool.inputSchema.get("properties", {}).items():
            if not schema.get("description"):
                missing.append(f"{name}.{prop}")
    assert not missing, missing


def test_descriptions_do_not_restate_arguments_or_returns(local_tools):
    offenders = [n for n, t in local_tools.items() if re.search(r"^\s*(Args|Returns):", t.description or "", re.M)]
    assert not offenders, offenders


def test_description_budget(local_tools):
    over = {
        n: len(t.description or "")
        for n, t in local_tools.items()
        if len(t.description or "") > _DESC_MAX.get(n, _DESC_MAX_DEFAULT)
    }
    assert not over, over
    total = sum(len(t.description or "") + len(json.dumps(t.inputSchema)) for t in local_tools.values())
    assert total <= _TOTAL_MAX, total


def test_guide_pointers_name_existing_guides(local_tools):
    guides = {p.stem for p in (_ROOT / "sdpm" / "references" / "guides").glob("*.md")}
    for name, tool in local_tools.items():
        for ref in re.findall(r'read_guides\(\[([^\]]*)\]\)', tool.description or ""):
            for g in re.findall(r'"([a-z-]+)"', ref):
                assert g in guides, f"{name} points at unknown guide {g}"


def test_read_guides_description_lists_the_catalogue(local_tools):
    doc = local_tools["read_guides"].description
    for g in (p.stem for p in (_ROOT / "sdpm" / "references" / "guides").glob("*.md")):
        assert g in doc, g


def test_entry_tools_are_the_only_ones_that_start_a_request(local_tools):
    starters = [n for n, t in local_tools.items() if re.search(r"\b[Cc]all (it|this) (first|before)|[Cc]all first|Start here", t.description or "")]
    assert set(starters) == {"start_presentation", "start_composing", "start_style", "start_translation"}


def test_contract_functions_are_annotated_not_docstring_args():
    from sdpm import tools

    for name, fn in inspect.getmembers(tools, inspect.isfunction):
        if fn.__module__ != tools.__name__ or name.startswith("_"):
            continue
        for p in inspect.signature(fn).parameters.values():
            assert "Field(" in str(p.annotation) or "Annotated" in str(p.annotation), f"{name}.{p.name}"
