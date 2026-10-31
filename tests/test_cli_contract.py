# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""CLI subcommands mirror public contract names without legacy aliases."""

import re
import subprocess
import sys
from pathlib import Path


def test_cli_subcommands_match_contract_vocabulary() -> None:
    root = Path(__file__).resolve().parents[1]
    cli = root / "sdpm" / "scripts" / "pptx_builder.py"
    result = subprocess.run(
        [sys.executable, str(cli), "--help"],
        capture_output=True,
        check=True,
        text=True,
    )
    choices_match = re.search(r"\{([^}]+)\}", result.stdout)
    assert choices_match is not None
    choices = set(choices_match.group(1).split(","))

    contract_commands = {
        "generate_pptx", "list_styles", "start", "read_guides",
        "analyze_template", "search_assets", "list_templates",
        "init_deck_workspace", "code_to_slide", "grid", "diff_pptx",
        "arch_diagram",
    }
    unchanged_cli_only = {"preview", "measure", "image-size", "list-asset-sources", "generate_html"}
    old_commands = {
        "generate", "examples", "workflows", "guides", "analyze-template",
        "search-assets", "list-templates", "init", "code-block", "diff",
        "layout", "search-patterns", "read_examples", "read_workflows",
        "list_workflows", "init_presentation",
    }
    assert contract_commands | unchanged_cli_only <= choices
    assert choices.isdisjoint(old_commands)


def _cli_init(tmp_path: Path, *extra: str) -> str:
    root = Path(__file__).resolve().parents[1]
    cli = root / "sdpm" / "scripts" / "pptx_builder.py"
    result = subprocess.run(
        [sys.executable, str(cli), "init_deck_workspace", "d", "-o", str(tmp_path / "d"), *extra],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout


def test_cli_init_prints_html_format_notes(tmp_path: Path) -> None:
    """L1 agents get the same format_notes the init_deck_workspace tool returns."""
    from sdpm.entry import format_notes

    out = _cli_init(tmp_path, "--output-format", "html")
    notes = format_notes("html")
    assert notes and "format_notes:" in out and notes.strip() in out


def test_cli_init_pptx_prints_no_format_notes(tmp_path: Path) -> None:
    out = _cli_init(tmp_path)
    assert "format_notes" not in out
    assert out.startswith("output_dir:")


def test_cli_generate_stops_on_invalid_output_format(tmp_path: Path) -> None:
    """An explicit invalid outputFormat exits 1 instead of falling through to a PPTX build."""
    import json

    _cli_init(tmp_path)
    deck = tmp_path / "d"
    deck_json = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    deck_json["outputFormat"] = "htlm"
    (deck / "deck.json").write_text(json.dumps(deck_json), encoding="utf-8")
    cli = Path(__file__).resolve().parents[1] / "sdpm" / "scripts" / "pptx_builder.py"
    result = subprocess.run(
        [sys.executable, str(cli), "generate_pptx", str(deck), "-o", str(deck / "output.pptx")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "outputFormat" in result.stderr
    assert not (deck / "output.pptx").exists()
