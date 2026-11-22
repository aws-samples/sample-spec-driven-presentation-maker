# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""scripts/context_size.py: bundle assembly, measurement and the real collection."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("context_size", ROOT / "scripts" / "context_size.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

ORCH = cs.payload_id("start_presentation", {}, "static.workflow")
SPEC_PPTX = cs.payload_id("start_composing", {"mode": "pptx"}, "static.slide_spec")
SPEC_TRANSLATE = cs.payload_id("start_translation", {"language": "ja"}, "static.slide_spec")


def _collected() -> dict:
    tool = cs.tool_text("run_python", "Run code.", {"type": "object"})
    other = cs.tool_text("start_style", "Style.", {"type": "object"})
    server = {"items": {"mcp/x/instructions": "hi", "mcp/x/tool/run_python": tool, "mcp/x/prompt/sdpm-vibe": "p"}}
    return {
        "local": server,
        "acp": {"items": {"mcp/acp/tool/run_python": tool}},
        "remote": {"items": {"mcp/remote/tool/run_python": tool, "mcp/remote/tool/start_style": other}},
        "payloads": {"items": {ORCH: "orchestrator doc", SPEC_PPTX: "spec", SPEC_TRANSLATE: "spec"}},
        "agent": {
            "items": {"agent/prompts/common/now.md": "now", ORCH: "orchestrator doc", "agent/tool/hearing": "h"},
            "modes": {
                "orchestrator": {
                    "parts": ["agent/prompts/common/now.md", ORCH],
                    "own_tools": ["agent/tool/hearing"],
                    "mcp_tools": ["run_python"],
                },
            },
        },
    }


def test_identical_texts_share_one_id_files_first():
    files = {"sdpm/references/workflows/orchestrator.md": "orchestrator doc"}
    items, bundles = cs.assemble(files, _collected())
    assert ORCH not in items and SPEC_TRANSLATE not in items
    assert "mcp/acp/tool/run_python" not in items  # same definition as the local server's
    assert bundles["Local MCP / orchestrator"] == [
        "mcp/x/instructions", "mcp/x/tool/run_python", "sdpm/references/workflows/orchestrator.md",
    ]
    assert bundles["Local MCP / translate"] == ["mcp/x/instructions", "mcp/x/tool/run_python", SPEC_PPTX]


def test_agent_bundle_takes_only_allowed_remote_tools():
    _, bundles = cs.assemble({}, _collected())
    assert bundles["Agent (AWS) / orchestrator"] == [
        "agent/prompts/common/now.md", ORCH, "agent/tool/hearing", "mcp/x/tool/run_python",
    ]


def test_missing_payload_is_left_out_of_the_bundle():
    collected = _collected()
    del collected["payloads"]["items"][ORCH]
    del collected["agent"]["items"][ORCH]
    _, bundles = cs.assemble({}, collected)
    assert bundles["Local MCP / orchestrator"] == ["mcp/x/instructions", "mcp/x/tool/run_python"]


def test_bundle_sizes_are_item_sums_and_markdown_shows_deltas():
    items = {"a": "abc", "b": "日本"}
    report = cs.measure(items, {"both": ["a", "b"]})
    assert report["items"]["b"] == {"chars": 2, "bytes": 6, "tokens": None}
    assert report["bundles"]["both"]["chars"] == 5 and report["bundles"]["both"]["bytes"] == 9
    base = cs.measure({"a": "a"}, {"both": ["a"]})
    text = cs.markdown(report, base)
    assert "| `both` | 5 | 9 | n/a | +4 (+400.0%) |" in text
    assert "| `b` | 2 | 6 | n/a | new |" in text


def test_real_checkout_collects_every_surface(tmp_path):
    collected = {s: cs._run_collect(ROOT, s, str(tmp_path)) for s in cs.SURFACES}
    items, bundles = cs.assemble(cs.read_files(ROOT), collected)
    assert "sdpm/references/workflows/orchestrator.md" in bundles["Local MCP / orchestrator"]
    assert "mcp/local/tool/start_presentation" in items and "mcp/local/instructions" in items
    for surface in ("Local MCP", "Local Web UI (ACP)", "Remote MCP"):
        for role in cs.ROLES:
            assert len(bundles[f"{surface} / {role}"]) > len(bundles[f"{surface} / tools only"]), (surface, role)
    assert any(i.startswith("agent/prompts/") for i in bundles["Agent (AWS) / orchestrator"])
    for name in ("sdpm-vibe", "sdpm-spec", "sdpm-style", "sdpm-translate"):
        assert items[f"mcp/local/prompt/{name}/body"].startswith(("Interaction mode", "Call `start_"))
    assert "<deck_id>" in items["mcp/local/prompt/sdpm-translate/body"]
    for item in ("agent/inject/composer_message_prefix", "agent/tool/report_to_orchestrator",
                 "client/kiro/agent-description", "servers/local/.kiro/acp-agents/sdpm-composer.json#description"):
        assert items[item], item
    styles = [i for i in items if i.startswith("sdpm/references/examples/styles/")]
    assert len(styles) == len(list((ROOT / "sdpm/references/examples/styles").glob("*.html")))
    assert "sdpm/references/guides/slide-json-elements.md" in bundles["Local MCP / composer-pptx + guides it names"]
    assert "AGENTS.md" in cs.read_dev_files(ROOT)


def test_named_guides_needs_a_guide_cue_and_reads_a_colon_list():
    guides = {"table", "grid", "writing-ja", "slide-json-media"}
    texts = [
        "Regions: `table`, `chart`.\n\nFor Japanese, `read_guides([\"writing-ja\"])`.",
        "Each field is in a guide:\n\n- `slide-json-media` and `grid`\n- `table`",
    ]
    assert cs.named_guides(texts, guides) == ["writing-ja", "slide-json-media", "grid", "table"]
    assert cs.named_guides(["Regions: `table`."], guides) == []


def test_guide_bundle_adds_named_guides_once_and_prompts_stay_out():
    files = {
        "sdpm/references/workflows/orchestrator.md": "orchestrator doc: the `writing-ja` guide",
        "sdpm/references/guides/writing-ja.md": "ja",
        "sdpm/references/guides/table.md": "t",
    }
    collected = _collected()
    collected["payloads"]["items"][ORCH] = collected["agent"]["items"][ORCH] = files[
        "sdpm/references/workflows/orchestrator.md"]
    _, bundles = cs.assemble(files, collected)
    assert "mcp/x/prompt/sdpm-vibe" not in bundles["Local MCP / tools only"]
    start = bundles["Local MCP / orchestrator"]
    assert bundles["Local MCP / orchestrator + guides it names"] == start + ["sdpm/references/guides/writing-ja.md"]


def test_developer_files_are_reported_apart_with_not_measured():
    report = cs.measure({"a": "abc"}, {"one": ["a"]}, developer={"AGENTS.md": "hello"})
    assert "AGENTS.md" not in report["items"]
    assert report["developer"]["total"]["chars"] == 5
    text = cs.markdown(report)
    assert "### Developer-facing" in text and "| `AGENTS.md` | 5 | 5 | n/a |" in text
    assert "### Not measured" in text and "Per-call tool results" in text
