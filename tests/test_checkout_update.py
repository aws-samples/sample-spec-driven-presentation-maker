# SPDX-License-Identifier: MIT-0
"""`servers/local/checkout_update.py` — the pull of `sdpm update` and of the installer.

An installed checkout whose tracked files were changed (by tools of an earlier version, or
by the user) must still fast-forward, and nothing in it may be lost: the changes go to a
named stash that the printed command brings back. Nothing is reset, nothing is cleaned.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "servers" / "local"))
import checkout_update as cu  # noqa: E402

ID = ["-c", "user.name=t", "-c", "user.email=t@example.com"]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def install(tmp_path):
    """An upstream with a newer main than the install, which has fetched it (FETCH_HEAD)."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "-q", "-b", "main")
    (upstream / "sdpm").mkdir()
    (upstream / "sdpm" / "uv.lock").write_text("old lock\n")
    (upstream / "next-env.d.ts").write_text("tracked\n")
    git(upstream, "add", ".")
    git(upstream, *ID, "commit", "-q", "-m", "one")
    checkout = tmp_path / "checkout"
    git(tmp_path, "clone", "-q", "--branch", "main", str(upstream), str(checkout))
    git(upstream, "rm", "-q", "sdpm/uv.lock")  # the 0.12 workspace change
    (upstream / "new.txt").write_text("new\n")
    git(upstream, "add", ".")
    git(upstream, *ID, "commit", "-q", "-m", "two")
    git(checkout, "fetch", "-q", "origin", "main")
    return upstream, checkout


def test_clean_checkout_fast_forwards_without_a_stash(install, capsys):
    upstream, checkout = install
    assert cu.pull(str(checkout)) == 0
    assert git(checkout, "rev-parse", "HEAD") == git(upstream, "rev-parse", "HEAD")
    assert git(checkout, "stash", "list") == ""
    assert capsys.readouterr().out == ""


def test_changed_tracked_files_are_set_aside_and_can_be_brought_back(install, capsys):
    upstream, checkout = install
    (checkout / "sdpm" / "uv.lock").write_text("rewritten by uv\n")  # deleted upstream: blocks a plain pull
    (checkout / "next-env.d.ts").write_text("rewritten by next build\n")
    (checkout / "notes.txt").write_text("mine, untracked\n")
    assert cu.pull(str(checkout)) == 0
    assert git(checkout, "rev-parse", "HEAD") == git(upstream, "rev-parse", "HEAD")
    assert git(checkout, "status", "--porcelain", "--untracked-files=no") == ""
    assert (checkout / "notes.txt").read_text() == "mine, untracked\n"  # untracked files are not touched
    out = capsys.readouterr().out
    assert "M sdpm/uv.lock" in out and "M next-env.d.ts" in out
    stash = git(checkout, "rev-parse", "refs/stash")
    assert f'git -C "{checkout}" stash apply {stash}' in out
    assert git(checkout, "log", "-1", "--format=%s", "refs/stash").startswith("On main: sdpm update ")
    # The printed command brings the edit to a file that still exists back.
    subprocess.run(["git", "-C", str(checkout), "checkout", stash, "--", "next-env.d.ts"], check=True)
    assert (checkout / "next-env.d.ts").read_text() == "rewritten by next build\n"


def test_a_checkout_that_cannot_fast_forward_stops_and_keeps_everything(install, capsys):
    _upstream, checkout = install
    (checkout / "local.txt").write_text("a local commit\n")
    git(checkout, "add", "local.txt")
    git(checkout, *ID, "commit", "-q", "-m", "local")
    head = git(checkout, "rev-parse", "HEAD")
    (checkout / "next-env.d.ts").write_text("edited\n")
    assert cu.pull(str(checkout)) == 1
    assert git(checkout, "rev-parse", "HEAD") == head  # no reset
    err = capsys.readouterr().err
    stash = git(checkout, "rev-parse", "refs/stash")
    assert "Nothing was discarded" in err and stash in err and "#sdpm-update-stops" in err
    assert git(checkout, "show", f"{stash}:next-env.d.ts") == "edited"


def test_another_branch_is_left_for_main(install):
    upstream, checkout = install
    git(checkout, "checkout", "-q", "-b", "elsewhere")
    (checkout / "next-env.d.ts").write_text("edited\n")
    assert cu.pull(str(checkout)) == 0
    assert git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(checkout, "rev-parse", "HEAD") == git(upstream, "rev-parse", "HEAD")


def test_it_runs_on_its_own(install):
    # Launchers and installers run the fetched copy with any Python: standard library only.
    _upstream, checkout = install
    source = Path(cu.__file__).read_text(encoding="utf-8")
    imports = {line.split()[1].split(".")[0] for line in source.splitlines() if line.startswith(("import ", "from "))}
    assert imports <= {"__future__", "argparse", "subprocess", "sys", "time", "typing"}
    rc = subprocess.run([sys.executable, cu.__file__, "--checkout", str(checkout), "pull"], check=False).returncode
    assert rc == 0
