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
    unchanged_cli_only = {"preview", "measure", "image-size", "list-asset-sources"}
    old_commands = {
        "generate", "examples", "workflows", "guides", "analyze-template",
        "search-assets", "list-templates", "init", "code-block", "diff",
        "layout", "search-patterns", "read_examples", "read_workflows",
        "list_workflows", "init_presentation",
    }
    assert contract_commands | unchanged_cli_only <= choices
    assert choices.isdisjoint(old_commands)
