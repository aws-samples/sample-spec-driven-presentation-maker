# SPDX-License-Identifier: MIT-0
"""`sdpm._launcher_bridge` — the #397 launcher's `sdpm update` hands over to `adopt` once.

The bridge acts only for the installed checkout and only when the installed `sdpm` command
is the #397 launcher (neither the #529/#532 refresh step nor the bootstrap marker); it runs
`checkout_update.py adopt` outside the checkout's .venv and never fails the old update.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sdpm import _launcher_bridge as bridge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "servers" / "local"))
import checkout_update as cu  # noqa: E402

OLD = "#!/usr/bin/env bash\n# sdpm — the one launcher for a local SDPM installation (~/.sdpm).\n"
SELF_REFRESHING = OLD + "#   sdpm update     pull, sync, rebuild, then client_config.py refresh\n"
BOOTSTRAP = OLD + "# sdpm-bootstrap 1\n"


@pytest.fixture
def install(tmp_path, monkeypatch):
    """An isolated install: SDPM_HOME with a git checkout, a uv record, a launcher dir."""
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    checkout = home / "checkout"
    checkout.mkdir(parents=True)
    bin_dir.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    subprocess.run(["git", "-C", str(checkout), "update-ref", "ORIG_HEAD", "HEAD"], check=True)
    (home / ".uv-path").write_text(sys.executable)  # any existing file stands in for uv
    monkeypatch.setenv("SDPM_HOME", str(home))
    monkeypatch.setenv("SDPM_LAUNCHER_DIR", str(bin_dir))
    launcher = bin_dir / ("sdpm.ps1" if sys.platform == "win32" else "sdpm")
    return home, checkout, launcher


def test_only_the_397_launcher_is_old(tmp_path):
    path = tmp_path / "sdpm"
    for text, old in ((OLD, True), (SELF_REFRESHING, False), (BOOTSTRAP, False), ("#!/bin/sh\n", False)):
        path.write_text(text)
        assert bridge.is_old_launcher(path) is old, text


def test_the_old_launcher_gets_adopt_with_its_path_and_the_pre_pull_commit(install):
    home, checkout, launcher = install
    launcher.write_text(OLD)
    argv = bridge.adopt_command(checkout, home)
    assert argv is not None
    assert argv[:7] == [sys.executable, "run", "--no-project", "--isolated", "--python", ">=3.11", "python"]
    assert argv[7] == str(checkout / "servers" / "local" / "checkout_update.py")
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert argv[argv.index("adopt"):] == ["adopt", "--from", head, "--launcher", str(launcher), "--prepared", "python"]


def test_newer_launchers_a_development_clone_or_no_launcher_do_nothing(install, tmp_path):
    home, checkout, launcher = install
    for text in (SELF_REFRESHING, BOOTSTRAP):
        launcher.write_text(text)
        assert bridge.adopt_command(checkout, home) is None
    launcher.write_text(OLD)
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    assert bridge.adopt_command(clone, home) is None  # not the installed checkout
    launcher.unlink()
    assert bridge.adopt_command(checkout, home) is None


def test_run_starts_adopt_outside_the_venv_reports_and_never_raises(install, monkeypatch, capsys):
    home, checkout, launcher = install
    launcher.write_text(OLD)
    monkeypatch.setattr(bridge, "_checkout", lambda: checkout)
    monkeypatch.setenv("VIRTUAL_ENV", str(checkout / ".venv"))
    calls = []
    bridge.run(call=lambda argv, env, cwd: (calls.append((argv, env, cwd)), 1)[1])
    assert len(calls) == 1 and calls[0][2] == str(home)
    assert "VIRTUAL_ENV" not in calls[0][1]
    assert "retries" in capsys.readouterr().out

    def boom(*_a, **_k):
        raise OSError("no python")

    bridge.run(call=boom)
    assert "Could not refresh" in capsys.readouterr().out


def test_the_bridge_copies_match_checkout_update():
    assert bridge.LAUNCHER_FINGERPRINT == cu.LAUNCHER_FINGERPRINT
    assert bridge.BOOTSTRAP_MARKER == cu.BOOTSTRAP_MARKER
    assert bridge.PY_ARGS == cu.PY_ARGS
