# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Hatch build hook for bundling runtime data without moving source files."""

from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_IGNORED_NAMES = {".DS_Store", "__MACOSX", "__pycache__", "config.example.json", "config.json"}


def _add_tree(build_data: dict, source: Path, destination: str) -> None:
    """Add filtered files below *source* to Hatch's force-include map."""
    if not source.is_dir():
        raise RuntimeError(f"Required bundle directory not found: {source}")

    force_include = build_data.setdefault("force_include", {})
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if not path.is_file() or any(part in _IGNORED_NAMES for part in relative.parts):
            continue
        if path.suffix == ".pyc" or path.name.startswith("._"):
            continue
        force_include[str(path)] = (Path(destination) / relative).as_posix()


class CustomBuildHook(BuildHookInterface):
    """Bundle data and the repository-level shared package for both build paths."""

    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)

        if self.target_name == "sdist":
            for directory in ("references", "templates", "assets"):
                _add_tree(build_data, root / directory, directory)
            _add_tree(build_data, root.parent / "shared", "shared")
            return

        if self.target_name == "wheel":
            for directory in ("references", "templates", "assets"):
                _add_tree(build_data, root / directory, f"sdpm/_data/{directory}")

            # A direct checkout build sees ../shared. A wheel built from the
            # generated sdist sees shared/ inside the extracted project root.
            shared = root / "shared"
            if not shared.is_dir():
                shared = root.parent / "shared"
            _add_tree(build_data, shared, "shared")
