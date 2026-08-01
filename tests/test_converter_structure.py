# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Structural guards for the converter/elements package (v0.5.2 split).

The package must keep a one-way dependency DAG:

    shapes.py       media.py          (leaves)
        ^              ^
    textbox.py         |
        ^              |
        +---- dispatch.py
                  ^
              __init__.py  (re-export facade only)

- submodules never import the package facade (no cycles)
- edges outside the table below are a design violation, not a convenience
"""

import ast
import importlib
from pathlib import Path

import pytest

_PKG_DIR = Path(__file__).resolve().parents[1] / "sdpm" / "sdpm" / "engine" / "converter" / "elements"
_PKG_NAME = "sdpm.engine.converter.elements"

# module -> allowed intra-package imports
_ALLOWED_EDGES = {
    "shapes": set(),
    "media": set(),
    "textbox": {"shapes"},
    "dispatch": {"shapes", "textbox", "media"},
    "__init__": {"shapes", "textbox", "media", "dispatch"},
}

_EXPECTED_MODULES = sorted(_ALLOWED_EDGES)


def _intra_package_imports(path: Path) -> set[str]:
    """Names of sibling modules imported by *path* (resolving relative imports).

    Also returns the sentinel ``"<package>"`` if the module imports the
    elements package facade itself.
    """
    tree = ast.parse(path.read_text())
    hits: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1:  # from .x import y  (x is a sibling)
                if node.module:
                    hits.add(node.module.split(".")[0])
                else:  # from . import x
                    hits.update(a.name for a in node.names)
            elif node.level == 0 and node.module:
                if node.module == _PKG_NAME:
                    hits.add("<package>")
                elif node.module.startswith(_PKG_NAME + "."):
                    hits.add(node.module[len(_PKG_NAME) + 1:].split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _PKG_NAME:
                    hits.add("<package>")
                elif alias.name.startswith(_PKG_NAME + "."):
                    hits.add(alias.name[len(_PKG_NAME) + 1:].split(".")[0])
    return hits


def test_package_layout_is_exactly_the_designed_split():
    found = sorted(p.stem for p in _PKG_DIR.glob("*.py"))
    assert found == _EXPECTED_MODULES, (
        "converter/elements gained or lost a module — update the design DAG "
        "(design.md of SPEC 20260731-2310) and _ALLOWED_EDGES together")


@pytest.mark.parametrize("module", _EXPECTED_MODULES)
def test_intra_package_dependencies_follow_the_dag(module):
    imports = _intra_package_imports(_PKG_DIR / f"{module}.py")
    assert "<package>" not in imports, (
        f"{module}.py imports the elements package facade — that is a cycle")
    unexpected = imports - _ALLOWED_EDGES[module]
    assert not unexpected, (
        f"{module}.py imports {sorted(unexpected)} — not part of the designed DAG")


@pytest.mark.parametrize("module", _EXPECTED_MODULES)
def test_submodule_imports_cleanly(module):
    name = _PKG_NAME if module == "__init__" else f"{_PKG_NAME}.{module}"
    importlib.import_module(name)
