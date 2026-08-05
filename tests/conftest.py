# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Test configuration — add servers/remote/ and sdpm/ to sys.path."""

import sys
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Emu

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_root / "servers" / "remote"))
sys.path.insert(0, str(_root / "sdpm"))

# Standard slide dimensions in EMU
_W_16X9 = 12192000
_H_16X9 = 6858000
_W_4X3 = 9144000
_H_4X3 = 6858000


@pytest.fixture()
def template_16x9() -> Path:
    """Path to the bundled 16:9 blank-dark template (no copy needed)."""
    return _root / "sdpm" / "templates" / "blank-dark.pptx"


@pytest.fixture()
def template_4x3(tmp_path: Path) -> Path:
    """Generate a 4:3 template from blank-dark.pptx by resizing slide dimensions.

    The roundtrip depends on layout name "Blank" existing in the template,
    so we cannot use a bare Presentation() — we must base it on blank-dark.pptx.
    """
    src = _root / "sdpm" / "templates" / "blank-dark.pptx"
    prs = Presentation(str(src))
    prs.slide_width = Emu(_W_4X3)
    prs.slide_height = Emu(_H_4X3)
    out = tmp_path / "blank-dark-4x3.pptx"
    prs.save(str(out))
    return out
