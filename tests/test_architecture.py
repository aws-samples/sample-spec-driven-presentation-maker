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
    """Dotted module parts relative to the package root, for relative-import
    resolution.

    ``__init__`` is deliberately KEPT as the last segment: for a package
    ``__init__.py``, ``from .. import x`` resolves against the package
    itself (level 1 = the package), so slicing must consume the
    ``__init__`` placeholder first. Stripping it would shift resolution
    one level too far up (review finding, PR #230 round 2).

    e.g. engine/diff/__init__.py -> ["sdpm", "engine", "diff", "__init__"]
         engine/x.py             -> ["sdpm", "engine", "x"]
    """
    rel = path.relative_to(_SDPM_PKG).with_suffix("")
    return ["sdpm", *rel.parts]


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


_MOD = ["sdpm", "engine", "x"]                       # regular module sdpm/engine/x.py
_PKG_INIT = ["sdpm", "engine", "__init__"]           # sdpm/engine/__init__.py
_NESTED_INIT = ["sdpm", "engine", "diff", "__init__"]  # sdpm/engine/diff/__init__.py


@pytest.mark.parametrize("module_parts,code,should_hit", [
    # forms the old regex version missed
    (_MOD, "from sdpm import api", True),
    (_MOD, "from sdpm import api, config", True),
    (_MOD, "from sdpm import tools", True),
    (_MOD, "from ..api import generate", True),
    (_MOD, "from .. import tools", True),
    (_MOD, "import sdpm.api", True),
    (_MOD, "import sdpm.api.generate", True),
    (_MOD, "from sdpm.tools import instructions", True),
    (_MOD, "from sdpm.api import generate", True),
    # package __init__ contexts (round-2 review: __init__ stripping shifted
    # relative resolution one level too far up and these were MISSED)
    (_PKG_INIT, "from .. import tools", True),
    (_PKG_INIT, "from ..api import generate", True),
    (_NESTED_INIT, "from ... import api", True),
    (_NESTED_INIT, "from ...api import generate", True),
    (_NESTED_INIT, "from ...tools import instructions", True),
    # allowed
    (_MOD, "from sdpm.config import SCRIPTS_DIR", False),
    (_MOD, "from sdpm import config", False),
    (_MOD, "from ..config import SCRIPTS_DIR", False),
    (_MOD, "from . import color", False),
    (_MOD, "from sdpm.engine.builder import PPTXBuilder", False),
    (_MOD, "import json", False),
    (_PKG_INIT, "from . import builder", False),
    (_PKG_INIT, "from .. import config", False),
    (_NESTED_INIT, "from ... import config", False),
    (_NESTED_INIT, "from .. import builder", False),
])
def test_detector_catches_all_import_forms(module_parts: list, code: str, should_hit: bool):
    """Self-test of the detector across module and package-__init__ contexts."""
    hits = _forbidden_imports(code, module_parts)
    assert bool(hits) == should_hit, f"{code!r} in {module_parts}: expected hit={should_hit}, got {hits}"
