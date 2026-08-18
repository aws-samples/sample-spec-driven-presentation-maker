# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""JSON file I/O helpers with explicit UTF-8 encoding."""

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any, *, indent: int = 2, ensure_ascii: bool = False, suffix: str = "") -> None:
    path.write_text(json.dumps(data, indent=indent, ensure_ascii=ensure_ascii) + suffix, encoding="utf-8")
