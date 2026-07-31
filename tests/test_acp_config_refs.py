# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Guard against dangling file:// references in ACP agent configs.

These JSON configs live in servers/local/.kiro/acp-agents/ and their file://
prompt/resource paths are resolved relative to the config file location
(the ACP process copies them as-is — see web-ui/src/lib/local/acp-process.ts).
A directory rename that misses these files ships broken agents, so every
reference must resolve to an existing file.

Only the git-tracked acp-agents/ directory is checked; .kiro/agents/ is a
gitignored runtime copy and would make collection environment-dependent.
"""

import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _ROOT / "servers" / "local" / ".kiro" / "acp-agents"
_CONFIG_FILES = sorted(_CONFIG_DIR.glob("*.json"))

_FILE_REF = re.compile(r"file://([^\"'\s]+)")


def test_expected_config_set():
    """Collection is deterministic: exactly the tracked ACP agent configs."""
    names = [p.name for p in _CONFIG_FILES]
    assert names == [
        "sdpm-composer.json",
        "sdpm-single.json",
        "sdpm-spec.json",
        "sdpm-style.json",
        "sdpm-vibe.json",
    ], f"acp-agents/ contents changed — update this list intentionally: {names}"


@pytest.mark.parametrize("config_path", _CONFIG_FILES, ids=lambda p: p.name)
def test_file_references_resolve(config_path: Path):
    text = config_path.read_text(encoding="utf-8")
    json.loads(text)  # config must be valid JSON at all
    refs = _FILE_REF.findall(text)
    assert refs, f"{config_path} has no file:// references — update this test if that is intentional"
    missing = []
    for ref in refs:
        resolved = (config_path.parent / ref).resolve()
        if not resolved.is_file():
            missing.append(f"{ref} -> {resolved}")
    assert not missing, f"{config_path} has dangling file:// references:\n" + "\n".join(missing)
