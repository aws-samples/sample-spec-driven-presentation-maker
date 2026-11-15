# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""compose_slides and message_composer of the Local Web UI's async compose (servers/local/compose_dispatch.py).

They exist only on server_acp.py with SDPM_LOCAL_COMPOSE=1, validate and answer at once,
keep no state between calls, and share Cloud's wording where the behaviour is the same.
"""

import asyncio
import json
import os
import re

import pytest
from mcp.client import Client

from agent_modules import load
from test_tool_descriptions import _LOCAL, _ROOT, _load, _tools

_NAMES = {"compose_slides", "message_composer"}
_SLUGS = ["cover", "agenda", "detail", "summary"]
_GROUPS = [
    {"slugs": ["cover", "agenda"], "instruction": "Compose these slides following specs/"},
    {"slugs": ["detail", "summary"], "instruction": "Compose these slides following specs/"},
]
_DECK = {
    "template": "blank-dark",
    "fonts": {"fullwidth": "Noto Sans JP", "halfwidth": "Amazon Ember"},
    "defaultTextColor": "#A1B2C3",
    "slideSize": {"width": 1920, "height": 1080, "ptPerPx": 0.5},
}
_CANNOT = "Cannot compose: fix the listed spec problems, then call compose_slides again."
_DESC_MAX = {"compose_slides": 2400, "message_composer": 560}


def _server(monkeypatch, label: str, value: str | None, path=_LOCAL / "server_acp.py"):
    if value is None:
        monkeypatch.delenv("SDPM_LOCAL_COMPOSE", raising=False)
    else:
        monkeypatch.setenv("SDPM_LOCAL_COMPOSE", value)
    return _load(f"sdpm_acp_compose_test_{label}", path, [_LOCAL, _ROOT / "sdpm"])


@pytest.fixture(scope="module")
def acp():
    mp = pytest.MonkeyPatch()
    try:
        yield _server(mp, "on", "1")
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def acp_tools(acp):
    return _tools(acp)


def _outline(slugs: list[str], body: str = "State the main point.") -> str:
    lines = ["# Deck", "", "## Section"]
    for slug in slugs:
        lines += [f"- [{slug}] The {slug} claim", f"  - body: {body}", "  - visual: A diagram.", "  - evidence: Source 1."]
    return "\n".join(lines) + "\n"


def _write_deck(path, *, html: bool = False, body: str = "State the main point."):
    (path / "specs").mkdir(parents=True)
    deck = {**_DECK, "outputFormat": "html"} if html else _DECK
    (path / "deck.json").write_text(json.dumps(deck), encoding="utf-8")
    (path / "specs" / "outline.md").write_text(_outline(_SLUGS, body), encoding="utf-8")
    return path


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "decks"
    r.mkdir()
    monkeypatch.setenv("SDPM_DECK_ROOT", str(r))
    return r


@pytest.fixture
def deck(root):
    return _write_deck(root / "deck1")


def _call(module, name: str, args: dict):
    async def run():
        async with Client(module.mcp, mode="legacy") as session:
            return await session.call_tool(name, args)

    return asyncio.run(run())


def _cannot(errors: list[str], warnings: list[str] | None = None) -> dict:
    return {"status": "error", "errors": errors, "warnings": warnings or [], "instruction": _CANNOT}


# --- Registration (R5 (7), I12) ---------------------------------------------------------


@pytest.mark.parametrize("label,value", [("unset", None), ("zero", "0"), ("true", "true")])
def test_tools_are_absent_unless_the_env_var_is_exactly_1(monkeypatch, label, value):
    assert not _NAMES & set(_tools(_server(monkeypatch, label, value)))


def test_tools_are_registered_with_the_env_var(acp_tools):
    assert _NAMES <= set(acp_tools)


def test_kiro_clis_sdpm_server_never_gets_them(monkeypatch):
    module = _server(monkeypatch, "stdio_server", "1", _LOCAL / "server.py")
    assert not _NAMES & set(_tools(module))


# --- Dispatch ---------------------------------------------------------------------------


def test_dispatch_answers_the_groups_and_the_outline(acp, deck):
    result = acp.compose_dispatch.compose_slides(str(deck), _GROUPS)

    task_id = result["task_id"]
    assert result["status"] == "dispatched"
    assert re.fullmatch(r"[0-9a-f]{12}", task_id)
    assert result["deck_id"] == str(deck.resolve())
    assert result["output_format"] == "pptx"
    assert result["slide_groups"] == [{"group": n, **g} for n, g in enumerate(_GROUPS, 1)]
    assert result["outline_slugs"] == _SLUGS
    assert "spec_warnings" not in result
    assert f"Task ID: {task_id}\n" in result["notice"]
    assert f'<compose_result task="{task_id}"' in result["notice"]


def test_html_deck_answers_html(acp, root):
    deck = _write_deck(root / "html", html=True)
    assert acp.compose_dispatch.compose_slides(str(deck), _GROUPS)["output_format"] == "html"


def test_tbd_outline_dispatches_with_the_warning(acp, root):
    deck = _write_deck(root / "tbd", body="[TBD]")
    result = acp.compose_dispatch.compose_slides(str(deck), _GROUPS)
    assert result["status"] == "dispatched"
    assert result["spec_warnings"] == ["outline.md contains [TBD]"]


# --- Over MCP: MCPServer parses and validates first ---------------------------------------


def test_valid_call_over_mcp(acp, deck):
    result = _call(acp, "compose_slides", {"deck_id": str(deck), "slide_groups": _GROUPS})
    assert not result.is_error
    assert json.loads(result.content[0].text)["status"] == "dispatched"


def test_slide_groups_as_a_json_string_is_parsed(acp, deck):
    def strip(r):
        payload = json.loads(r.content[0].text)
        payload.pop("task_id"), payload.pop("notice")
        return payload

    as_list = _call(acp, "compose_slides", {"deck_id": str(deck), "slide_groups": _GROUPS})
    as_string = _call(acp, "compose_slides", {"deck_id": str(deck), "slide_groups": json.dumps(_GROUPS)})
    assert not as_string.is_error
    assert strip(as_string) == strip(as_list)


@pytest.mark.parametrize(
    "groups",
    [
        [{"slugs": ["cover"]}],
        [{"slugs": "cover", "instruction": "x"}],
        [{"slugs": [5], "instruction": "x"}],
    ],
    ids=["no-instruction", "slugs-string", "slug-not-string"],
)
def test_type_errors_are_mcpserver_validation_errors(acp, deck, groups):
    result = _call(acp, "compose_slides", {"deck_id": str(deck), "slide_groups": groups})
    assert result.is_error
    assert "validation error for compose_slidesArguments" in result.content[0].text


def test_message_composer_type_error_is_a_validation_error(acp):
    result = _call(acp, "message_composer", {"group": "x", "text": "hi"})
    assert result.is_error
    assert "validation error for message_composerArguments" in result.content[0].text


# --- The function's own rules -----------------------------------------------------------


def _group(slugs, instruction="Compose these slides following specs/"):
    return {"slugs": slugs, "instruction": instruction}


@pytest.mark.parametrize(
    "groups,error",
    [
        ([], "slide_groups must be a list of 1 to 20 groups"),
        ([_group([f"s{i}"]) for i in range(21)], "slide_groups must be a list of 1 to 20 groups"),
        ([_group([])], "group 1 must have 1 to 50 slugs"),
        ([_group([f"s{i}" for i in range(51)])], "group 1 must have 1 to 50 slugs"),
        ([_group(["a b"])], "slug 'a b' must match ^[A-Za-z0-9_-]{1,128}$"),
        ([_group([""])], "slug '' must match ^[A-Za-z0-9_-]{1,128}$"),
        ([_group(["x" * 129])], f"slug {'x' * 129!r} must match ^[A-Za-z0-9_-]{{1,128}}$"),
        ([_group(["cover"], "")], "group 1 instruction must be 1 to 10000 characters"),
        ([_group(["cover"], "x" * 10_001)], "group 1 instruction must be 1 to 10000 characters"),
        ([_group(["intro"]), _group(["intro"])], "slug 'intro' is in groups 1 and 2"),
    ],
    ids=["0-groups", "21-groups", "0-slugs", "51-slugs", "space", "empty", "129", "no-text", "long-text", "dup"],
)
def test_group_rules(acp, deck, groups, error):
    assert acp.compose_dispatch.compose_slides(str(deck), groups) == _cannot([error])


def _deck_error(deck_id: str, root) -> dict:
    return _cannot([f"deck_id {deck_id!r} is not a deck directory directly under {root.resolve()}"])


def test_deck_rules(acp, root, tmp_path):
    outside = _write_deck(tmp_path / "outside")
    nested = _write_deck(root / "sub" / "deck")
    link = root / "link"
    os.symlink(outside, link)
    for deck_id in (str(outside), str(nested), str(root / "missing"), str(link)):
        assert acp.compose_dispatch.compose_slides(deck_id, _GROUPS) == _deck_error(deck_id, root), deck_id


def test_deck_root_follows_the_shared_order(monkeypatch, tmp_path):
    r = tmp_path / "output"
    r.mkdir()
    monkeypatch.delenv("SDPM_DECK_ROOT", raising=False)
    monkeypatch.setenv("SDPM_OUTPUT_DIR", str(r))
    module = _server(monkeypatch, "output_dir", "1")
    assert module.compose_dispatch._deck_root() == module._DECK_ROOT == r.resolve()
    deck = _write_deck(r / "deck1")
    assert module.compose_dispatch.compose_slides(str(deck), _GROUPS)["status"] == "dispatched"


def test_check_specs_errors_are_returned(acp, deck):
    from sdpm import tools

    spec = tools.check_specs(str(deck), assigned_slugs=["missing"])
    assert not spec["ok"]
    result = acp.compose_dispatch.compose_slides(str(deck), [_group(["missing"])])
    assert result == _cannot(spec["errors"], spec["warnings"])


def test_group_rules_come_before_the_deck(acp, root):
    missing = str(root / "missing")
    assert acp.compose_dispatch.compose_slides(missing, []) == _cannot(["slide_groups must be a list of 1 to 20 groups"])


@pytest.mark.parametrize(
    "group,text,error",
    [
        (0, "hi", "group must be 1 or more"),
        (-1, "hi", "group must be 1 or more"),
        (1, "", "text must be 1 to 10000 characters"),
        (1, "x" * 10_001, "text must be 1 to 10000 characters"),
    ],
)
def test_message_composer_rules(acp, group, text, error):
    assert acp.compose_dispatch.message_composer(group, text) == {"status": "error", "content": [{"text": error}]}


def test_message_composer_sends(acp):
    assert acp.compose_dispatch.message_composer(3, "Add a subtitle") == (
        "Sent to composer 3; it reads the message at its next step. If no composer of group 3 "
        'is running, a <message_composer_error group="3"> in a later message says so.'
    )


# --- No state (I10) ---------------------------------------------------------------------


def test_calls_are_independent(acp, deck):
    first = acp.compose_dispatch.compose_slides(str(deck), _GROUPS)
    second = acp.compose_dispatch.compose_slides(str(deck), _GROUPS)
    assert first["task_id"] != second["task_id"]
    for r in (first, second):
        r.pop("task_id"), r.pop("notice")
    assert first == second
    assert acp.compose_dispatch.message_composer(2, "x") == acp.compose_dispatch.message_composer(2, "x")


# --- Cloud parity (R5 (8)) --------------------------------------------------------------


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "")).strip()


@pytest.fixture(scope="module")
def cloud():
    compose = load("modes.composer").make_compose_slides([], model=object()).tool_spec
    messaging = load("compose_messaging")
    message = messaging.make_message_composer(messaging.ComposeMessaging("s")).tool_spec
    return {"compose_slides": compose, "message_composer": message}


_PINNED_COMPOSE = [
    "Runs only what you pass: the layout pass and the content pass are separate calls.",
    "Use this once outline.md is finalized.",
    "It runs in the background: the call returns at once, and its report is delivered to you "
    "automatically when the composers finish.",
    "Until the report arrives the composers are still writing the slides, so after dispatching, tell the "
    "user in a sentence what is being composed and end your turn (or do other work the user asked for that "
    "does not need these slides).",
    "While it runs, message_composer reaches a running composer.",
    "The composer reads specs/ (brief, outline, art-direction) for all content and design decisions. The "
    "instruction only needs to specify which slides to compose. Add user requests or review feedback if "
    "applicable, but do NOT invent layout or design directives — the composer makes those decisions.",
]
_PINNED_MESSAGE = [
    "Send a message to a composer of the compose_slides call running now.",
    "It reaches the composer at its next step, and the composer applies it to the slides it is writing, "
    "including the ones it already wrote.",
]


@pytest.mark.parametrize("name,pinned", [("compose_slides", _PINNED_COMPOSE), ("message_composer", _PINNED_MESSAGE)])
def test_pinned_sentences_are_cloud_and_local(cloud, acp_tools, name, pinned):
    cloud_desc, local_desc = _norm(cloud[name]["description"]), _norm(acp_tools[name].description)
    for sentence in pinned:
        assert _norm(sentence) in cloud_desc, sentence
        assert _norm(sentence) in local_desc, sentence


def test_local_differences(acp_tools):
    compose = _norm(acp_tools["compose_slides"].description)
    assert "Up to 4 groups run concurrently." in compose
    assert "read the PNGs under <deck>/preview/" in compose
    assert "get_preview" not in compose and "<composer_note>" not in compose
    assert '<message_composer_error group="N">' in acp_tools["message_composer"].description


def test_parameter_descriptions(cloud, acp_tools):
    local = acp_tools["compose_slides"].input_schema
    cloud_props = cloud["compose_slides"]["inputSchema"]["json"]["properties"]
    assert local["properties"]["deck_id"]["description"] == "Deck directory path."
    assert local["properties"]["slide_groups"]["description"] == cloud_props["slide_groups"]["description"]
    ref = local["properties"]["slide_groups"]["items"]["$ref"].rsplit("/", 1)[-1]
    group = local["$defs"][ref]["properties"]
    for field in ("slugs", "instruction"):
        assert group[field]["description"] == cloud_props["slide_groups"]["items"]["properties"][field]["description"]

    local_msg = acp_tools["message_composer"].input_schema["properties"]
    cloud_msg = cloud["message_composer"]["inputSchema"]["json"]["properties"]
    for field in ("group", "text"):
        assert _norm(local_msg[field]["description"]) == _norm(cloud_msg[field]["description"])


# --- Description rules (tests/test_tool_descriptions.py does not see these tools) ---------


@pytest.mark.parametrize("name", sorted(_NAMES))
def test_description_rules(acp_tools, name):
    tool = acp_tools[name]
    desc = tool.description or ""
    assert all(p.get("description") for p in tool.input_schema["properties"].values())
    assert not re.search(r"^\s*(Args|Returns):", desc, re.M)
    assert len(desc) <= _DESC_MAX[name], len(desc)
    assert not re.search(r"\b[Cc]all (it|this) (first|before)|[Cc]all first|Start here", desc)


def test_the_group_limit_matches_the_local_compose_run(acp_tools):
    # The docstring's number is the one the Local Web UI's compose run starts at once.
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "web-ui" / "src" / "lib" / "local" / "compose-run.ts").read_text()
    (limit,) = re.findall(r"export const MAX_PARALLEL_COMPOSERS = (\d+)", source)
    assert f"Up to {limit} groups run concurrently." in _norm(acp_tools["compose_slides"].description)
