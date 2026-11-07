# SPDX-License-Identifier: MIT-0
"""The one TTY rule (R10): ask only when stdout is a terminal and a terminal can be read.

Python side: `checkout_update.tty_allowed` and `picker._tty_available`. An agent that captures
stdout, a runner without a controlling terminal, and --non-interactive all get no prompt.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "servers" / "local"))
import checkout_update as cu  # noqa: E402
import picker  # noqa: E402


class Stream:
    def __init__(self, tty: bool) -> None:
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


@pytest.mark.parametrize("rule", [cu.tty_allowed, picker._tty_available])
def test_captured_stdout_means_no_prompt(rule, monkeypatch):
    monkeypatch.setattr(sys, "stdout", Stream(False))
    monkeypatch.setattr(sys, "stdin", Stream(True))
    assert rule() is False


@pytest.mark.skipif(sys.platform == "win32", reason="/dev/tty")
@pytest.mark.parametrize("rule", [cu.tty_allowed, picker._tty_available])
def test_no_controlling_terminal_means_no_prompt(rule, monkeypatch):
    monkeypatch.setattr(sys, "stdout", Stream(True))

    def fail(*_a, **_k):
        raise OSError("ENXIO")

    monkeypatch.setattr(os, "open", fail)
    assert rule() is False


@pytest.mark.skipif(sys.platform == "win32", reason="/dev/tty")
def test_a_terminal_means_a_prompt_unless_non_interactive(monkeypatch):
    monkeypatch.setattr(sys, "stdout", Stream(True))
    monkeypatch.setattr(os, "open", lambda *_a, **_k: 99)
    monkeypatch.setattr(os, "close", lambda _fd: None)
    assert cu.tty_allowed() is True and picker._tty_available() is True
    assert cu.tty_allowed(non_interactive=True) is False
