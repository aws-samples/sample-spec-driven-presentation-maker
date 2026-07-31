# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Guard against dangling file:// references in Kiro agent / ACP agent configs.

These JSON configs live in servers/local/.kiro/{agents,acp-agents}/ and their
file:// prompt/resource paths are resolved relative to the config file location
(the ACP process copies them as-is — see web-ui/src/lib/local/acp-process.ts).
A directory rename that misses these files ships broken agents, so every
reference must resolve to an existing file.
"""

import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIRS = [
    _ROOT / "servers" / "local" / ".kiro" / "agents",
    _ROOT / "servers" / "local" / ".kiro" / "acp-agents",
]

_FILE_REF = re.compile(r"file://([^\"'\s]+)")


def _config_files():
    for d in _CONFIG_DIRS:
        yield from sorted(d.glob("*.json"))


def _file_refs(config_path: Path):
    text = config_path.read_text(encoding="utf-8")
    json.loads(text)  # config must be valid JSON at all
    return _FILE_REF.findall(text)


@pytest.mark.parametrize("config_path", _config_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_file_references_resolve(config_path: Path):
    refs = _file_refs(config_path)
    assert refs, f"{config_path} has no file:// references — update this test if that is intentional"
    missing = []
    for ref in refs:
        resolved = (config_path.parent / ref).resolve()
        if not resolved.is_file():
            missing.append(f"{ref} -> {resolved}")
    assert not missing, f"{config_path} has dangling file:// references:\n" + "\n".join(missing)
