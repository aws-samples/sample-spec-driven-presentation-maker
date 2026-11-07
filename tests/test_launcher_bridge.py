# SPDX-License-Identifier: MIT-0
"""`sdpm._launcher_bridge` — an old launcher's `sdpm update` runs the refresh once.

The bridge acts only for the installed checkout and only when the installed `sdpm`
command is a launcher from before the refresh step; it never fails the old update.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sdpm import _launcher_bridge as bridge

OLD = "#!/usr/bin/env bash\n# sdpm — the one launcher for a local SDPM installation (~/.sdpm).\n"
NEW = OLD + "#   sdpm update     pull, sync, rebuild, then client_config.py refresh\n"


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


def test_old_launcher_gets_the_refresh_with_its_path_and_the_pre_pull_commit(install):
    home, checkout, launcher = install
    launcher.write_text(OLD)
    argv = bridge.refresh_command(checkout, home)
    assert argv is not None
    assert argv[0] == sys.executable and argv[1] == str(checkout / "servers" / "local" / "client_config.py")
    assert argv[argv.index("refresh") + 1:argv.index("refresh") + 3] == ["--launcher", str(launcher)]
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert argv[-2:] == ["--since", head]


def test_new_launcher_development_clone_or_no_launcher_do_nothing(install, tmp_path):
    home, checkout, launcher = install
    launcher.write_text(NEW)
    assert bridge.refresh_command(checkout, home) is None  # the new launcher refreshes itself
    launcher.write_text(OLD)
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    assert bridge.refresh_command(clone, home) is None  # not the installed checkout
    launcher.unlink()
    assert bridge.refresh_command(checkout, home) is None


def test_run_reports_and_never_raises(install, monkeypatch, capsys):
    home, checkout, launcher = install
    launcher.write_text(OLD)
    monkeypatch.setattr(bridge, "_checkout", lambda: checkout)
    calls = []
    bridge.run(call=lambda argv, cwd: (calls.append((argv, cwd)), 1)[1])
    assert len(calls) == 1 and calls[0][1] == str(checkout / "servers" / "local")
    assert "retries" in capsys.readouterr().out

    def boom(*_a, **_k):
        raise OSError("no python")

    bridge.run(call=boom)
    assert "Could not refresh" in capsys.readouterr().out
