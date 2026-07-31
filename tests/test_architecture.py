# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Architecture guard: the dependency rule of the Ports & Adapters design.

Dependencies point inward only (servers -> tools -> engine/knowledge).
The core (engine, knowledge) must never import from the facade (api),
the port (tools), or any outer layer. engine.diff once lazily imported
sdpm.api (fixed in v0.5.x) — this test keeps it fixed.
"""

import re
from pathlib import Path

import pytest

_SDPM_PKG = Path(__file__).resolve().parents[1] / "sdpm" / "sdpm"

# Core subpackages that must not depend on outer layers
_CORE_DIRS = ("engine", "knowledge")
# Outer-layer modules the core must never import
_FORBIDDEN = re.compile(
    r"^\s*(?:from|import)\s+sdpm\.(api|tools)\b", re.MULTILINE
)


def _core_files():
    for core in _CORE_DIRS:
        yield from sorted((_SDPM_PKG / core).rglob("*.py"))


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: str(p.relative_to(_SDPM_PKG)))
def test_core_does_not_import_outer_layers(path: Path):
    """engine/ and knowledge/ must not import sdpm.api or sdpm.tools."""
    source = path.read_text(encoding="utf-8")
    match = _FORBIDDEN.search(source)
    assert match is None, (
        f"{path.relative_to(_SDPM_PKG)} imports an outer layer: {match.group(0).strip()!r}. "
        "Core logic must not depend on the facade/port — move the orchestration "
        "into sdpm.api or pass data in (see steering principles, dependency rule)."
    )
