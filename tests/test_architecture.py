# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Architecture guard: the dependency rule of the Ports & Adapters design.

Dependencies point inward only (servers -> tools -> engine/knowledge).
The core (engine, knowledge) must never import from the facade (api) or
the port (tools). engine.diff once lazily imported sdpm.api (fixed in
v0.5.x) — this test keeps it fixed.

Detection is AST-based (not regex) so every import form is caught:
``import sdpm.api``, ``from sdpm import api``, ``from sdpm.api import x``,
and relative forms like ``from ..api import x`` / ``from .. import tools``.
"""

import ast
from pathlib import Path

import pytest

_SDPM_PKG = Path(__file__).resolve().parents[1] / "sdpm" / "sdpm"

# Core subpackages that must not depend on outer layers
_CORE_DIRS = ("engine", "knowledge")
# Outer-layer submodules of the sdpm package that the core must never import
_FORBIDDEN = {"api", "tools"}

# Materialized list — pytest 10 rejects passing a generator to parametrize
_CORE_FILES = sorted(
    path for core in _CORE_DIRS for path in (_SDPM_PKG / core).rglob("*.py")
)


def _module_parts(path: Path) -> list[str]:
    """Dotted module parts relative to the package root.

    e.g. engine/diff/__init__.py -> ["sdpm", "engine", "diff"]
    """
    rel = path.relative_to(_SDPM_PKG).with_suffix("")
    parts = ["sdpm", *rel.parts]
    if parts[-1] == "__init__":
        parts.pop()
    return parts


def _forbidden_imports(source: str, module_parts: list[str]) -> list[str]:
    """Return descriptions of forbidden imports found in *source*."""
    hits: list[str] = []

    def check(dotted: str, names: list[str], lineno: int) -> None:
        segs = dotted.split(".") if dotted else []
        # import sdpm.api / from sdpm.api import x / from ..api import x
        if len(segs) >= 2 and segs[0] == "sdpm" and segs[1] in _FORBIDDEN:
            hits.append(f"line {lineno}: {dotted}")
        # from sdpm import api / from .. import tools (at package root)
        elif segs == ["sdpm"]:
            bad = sorted(set(names) & _FORBIDDEN)
            if bad:
                hits.append(f"line {lineno}: from sdpm import {', '.join(bad)}")

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                check(alias.name, [], node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: resolve against this module's package
                base = module_parts[: len(module_parts) - node.level]
                dotted = ".".join(base + (node.module.split(".") if node.module else []))
            else:
                dotted = node.module or ""
            check(dotted, [a.name for a in node.names], node.lineno)
    return hits


def test_core_files_discovered():
    """Sanity: the scan actually covers the core (guards against path drift)."""
    assert len(_CORE_FILES) > 20, f"only {len(_CORE_FILES)} core files found — path broken?"


@pytest.mark.parametrize("path", _CORE_FILES, ids=lambda p: str(p.relative_to(_SDPM_PKG)))
def test_core_does_not_import_outer_layers(path: Path):
    """engine/ and knowledge/ must not import sdpm.api or sdpm.tools."""
    hits = _forbidden_imports(path.read_text(encoding="utf-8"), _module_parts(path))
    assert not hits, (
        f"{path.relative_to(_SDPM_PKG)} imports outer layers: {hits}. "
        "Core logic must not depend on the facade/port — move the orchestration "
        "into sdpm.api or pass data in (see steering principles, dependency rule)."
    )


@pytest.mark.parametrize("code,should_hit", [
    # forms the old regex version missed
    ("from sdpm import api", True),
    ("from sdpm import api, config", True),
    ("from sdpm import tools", True),
    ("from ..api import generate", True),
    ("from .. import tools", True),
    ("import sdpm.api", True),
    ("import sdpm.api.generate", True),
    ("from sdpm.tools import instructions", True),
    ("from sdpm.api import generate", True),
    # allowed
    ("from sdpm.config import SCRIPTS_DIR", False),
    ("from sdpm import config", False),
    ("from ..config import SCRIPTS_DIR", False),
    ("from . import color", False),
    ("from sdpm.engine.builder import PPTXBuilder", False),
    ("import json", False),
])
def test_detector_catches_all_import_forms(code: str, should_hit: bool):
    """Self-test of the detector, simulating a module at sdpm/engine/x.py."""
    hits = _forbidden_imports(code, ["sdpm", "engine", "x"])
    assert bool(hits) == should_hit, f"{code!r}: expected hit={should_hit}, got {hits}"
