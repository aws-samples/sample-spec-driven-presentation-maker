# SPDX-License-Identifier: MIT-0
"""`servers/local/checkout_update.py` — the install lifecycle behind `sdpm update` and the installer.

The rules under test: the target is the newest release tag on main (or main on the main
channel) and always contains the user's commit; local changes go to a named stash, never
lost; a target whose preparation fails is rolled back by the sentinel rule; the previous
Web UI is never lost; state.json describes a prepared version.

This file imports only ``checkout_update``, the standard library and pytest, and uses only
pytest's built-in fixtures, so CI also runs it under Python 3.8 with ``--noconftest``.
"""

from __future__ import annotations

import ast
import http.server
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

LOCAL = Path(__file__).resolve().parents[1] / "servers" / "local"
INSTALL = Path(__file__).resolve().parents[1] / "scripts" / "install"
sys.path.insert(0, str(LOCAL))
import checkout_update as cu  # noqa: E402

ID = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="the fake uv is a script with a shebang")
SOURCE = (LOCAL / "checkout_update.py").read_text(encoding="utf-8")
GUARD = 'if __name__ == "__main__":'


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def variant(snippet: str) -> str:
    """checkout_update.py with ``snippet`` inserted before its one ``__main__`` guard."""
    assert SOURCE.count(GUARD) == 1
    return SOURCE.replace(GUARD, snippet + "\n\n" + GUARD)


FAKE_UV = '''#!{python}
import json, os, subprocess, sys
args = sys.argv[1:]
log = os.environ.get("FAKE_UV_LOG")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps(args) + "\\n")
if args[:1] == ["sync"]:
    sys.exit(int(os.environ.get("FAKE_UV_SYNC_RC", "0")))
if args[:1] == ["run"]:
    rest = args[1:]
    target = rest[rest.index("python") + 1:]
    if "--isolated" in rest:
        sys.exit(subprocess.call([sys.executable] + target))
    if target and target[0].endswith("client_config.py"):
        if "--record" in target:
            with open(target[target.index("--record") + 1], "w") as handle:
                handle.write(os.environ.get("FAKE_UV_RECORD", "{{}}"))
        sys.exit(int(os.environ.get("FAKE_UV_CLIENTS_RC", "0")))
sys.exit(0)
'''


class World:
    """An upstream repository, an install cloned from it, a launcher and a fake uv."""

    def __init__(self, tmp: Path, monkeypatch) -> None:
        self.tmp = tmp
        self.upstream = tmp / "upstream"
        self.home = tmp / "home"
        self.checkout = self.home / "checkout"
        self.bin = tmp / "bin"
        self.launcher = self.bin / "sdpm"
        self.log = tmp / "uv.log"
        self.uv = tmp / "fake-uv"
        self.uv.write_text(FAKE_UV.format(python=sys.executable), encoding="utf-8")
        self.uv.chmod(0o755)
        monkeypatch.setenv("FAKE_UV_LOG", str(self.log))
        monkeypatch.setenv("SDPM_RELEASE_BASE_URL", (tmp / "releases").as_uri())
        for name in ("SDPM_CHANNEL", "SDPM_AGENT_NAME", "SDPM_UPDATER", "VIRTUAL_ENV"):
            monkeypatch.delenv(name, raising=False)
        self.upstream.mkdir()
        git(self.upstream, "init", "-q", "-b", "main")
        write(self.upstream / "servers" / "local" / "checkout_update.py", SOURCE)
        for name in ("launcher.sh", "launcher.ps1"):
            write(self.upstream / "scripts" / "install" / name, (INSTALL / name).read_text(encoding="utf-8"))
        write(self.upstream / "CHANGELOG.md", "# Changelog\n")
        write(self.upstream / "uv.lock", "lock\n")
        self.base = self.commit("base")

    def commit(self, message: str, files=None) -> str:
        for name, text in (files or {}).items():
            if text is None:
                git(self.upstream, "rm", "-q", name)
            else:
                write(self.upstream / name, text)
        git(self.upstream, "add", "-A")
        git(self.upstream, *ID, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.upstream, "rev-parse", "HEAD")

    def tag(self, name: str, sha: str = "HEAD") -> str:
        git(self.upstream, "tag", name, sha)
        return git(self.upstream, "rev-parse", name + "^{commit}")

    def install(self, at: str = "", bootstrap: bool = True) -> None:
        """A checkout as an earlier install left it: at ``at``, with state.json."""
        self.home.mkdir(exist_ok=True)
        git(self.tmp, "clone", "-q", "--branch", "main", str(self.upstream), str(self.checkout))
        if at:
            git(self.checkout, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", at)
        self.bin.mkdir(exist_ok=True)
        if bootstrap:
            shutil.copy(str(INSTALL / "launcher.sh"), str(self.launcher))
        (self.home / ".uv-path").write_text(str(self.uv) + "\n")
        head = git(self.checkout, "rev-parse", "HEAD")
        cu.write_state(self.home, channel="release", profile="mcp", agent_name="sdpm", commit=head, tag=None,
                       clients=[])

    def fetch(self) -> None:
        assert cu.fetch(str(self.checkout)).returncode == 0

    def head(self) -> str:
        return git(self.checkout, "rev-parse", "HEAD")

    def state(self) -> dict:
        return json.loads((self.home / "state.json").read_text(encoding="utf-8"))

    def run(self, *args: str) -> int:
        return cu.main(["--checkout", str(self.checkout), "--uv", str(self.uv), *args])

    def update(self, *args: str) -> int:
        self.fetch()
        return self.run("update", "--launcher", str(self.launcher), *args)

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


# ---------------------------------------------------------------------------
# Tags and selection
# ---------------------------------------------------------------------------


def test_only_stable_semver_names_count():
    assert cu.parse_version("v0.13.0") == (0, 13, 0)
    assert cu.parse_version("v1.10.2") == (1, 10, 2)
    for name in ("v0.13.0-rc.1", "v0.13.0+build", "v01.2.3", "0.13.0", "v0.13", "vX.Y.Z"):
        assert cu.parse_version(name) is None, name


def test_latest_release_is_on_main_and_above_the_floor(world):
    world.tag("v0.12.0")
    one = world.commit("one")
    world.tag("v0.13.0")
    world.tag("v0.14.0-rc.1")
    git(world.upstream, "checkout", "-q", "-b", "side")
    world.commit("hotfix on a branch")
    world.tag("v1.1.0")  # the highest, but not on main: never a candidate
    git(world.upstream, "checkout", "-q", "main")
    world.install()
    world.fetch()
    latest = cu.latest_release(str(world.checkout))
    assert latest is not None and (latest.name, latest.sha) == ("v0.13.0", one)
    assert cu.latest_release(str(world.checkout), exclude=["v0.13.0"]) is None  # v0.12.0 is below the floor


def test_a_missing_origin_main_is_fatal_before_anything_moves(world):
    world.install()
    git(world.checkout, "update-ref", "-d", "refs/remotes/origin/main")
    with pytest.raises(cu.GitError):
        cu.latest_release(str(world.checkout))


def test_resolve_channel_option_then_environment_then_state_then_release():
    assert cu.resolve_channel("main", {"SDPM_CHANNEL": "release"}, {"channel": "release"}) == "main"
    assert cu.resolve_channel(None, {"SDPM_CHANNEL": "main"}, {"channel": "release"}) == "main"
    assert cu.resolve_channel(None, {}, {"channel": "main"}) == "main"
    assert cu.resolve_channel(None, {}, {}) == "release"
    with pytest.raises(cu.Stop) as stop:
        cu.resolve_channel(None, {"SDPM_CHANNEL": "nightly"}, {})
    assert stop.value.code == 2


ANC = {("b", "e"), ("b", "m"), ("e", "m"), ("c", "m"), ("b", "c"), ("f", "c"), ("f", "e"), ("f", "m")}


def contains(a, b):
    return a == b or (a, b) in ANC


@pytest.mark.parametrize("channel,base,current,latest,entry,finishes,expected", [
    ("release", "b", "b", "e", "update", True, ("e", "release")),       # move to the release
    ("release", "e", "e", "e", "update", True, ("e", "release")),       # up to date
    ("release", "x", "x", "e", "update", True, ("x", "stay-release")),  # ahead of every release: stay
    ("release", "x", "x", None, "update", True, ("x", "stay-release")),
    ("release", None, "m", "e", "install", True, ("e", "release")),     # a new install takes E
    ("release", None, "m", None, "install", True, ("m", "main")),       # no release yet: main
    ("main", "b", "b", "e", "update", True, ("m", "main")),
    ("main", "x", "x", "e", "update", True, ("x", "stay-main")),        # commits main does not have
    ("release", "f", "c", "e", "adopt", True, ("e", "release")),        # adopt: base behind current
    ("release", "c", "c", None, "update", False, ("m", "main")),        # cannot finish, main has it
])
def test_select_table(channel, base, current, latest, entry, finishes, expected):
    chosen = cu.select(channel, base, current, latest, "m", contains, lambda _sha: finishes, entry)
    assert (chosen.target, chosen.kind) == expected


def test_select_cannot_finish_and_not_on_main_stops():
    with pytest.raises(cu.CannotFinish):
        cu.select("release", "x", "x", None, "m", contains, lambda _sha: False, "update")


def test_is_fresh_needs_all_three_files_missing(tmp_path):
    assert cu.is_fresh(tmp_path)
    (tmp_path / ".uv-path").write_text("/uv\n")
    assert not cu.is_fresh(tmp_path)  # state.json deleted by hand does not make an install new


# ---------------------------------------------------------------------------
# update / install end to end (stage 1 in-process, finish in a real subprocess)
# ---------------------------------------------------------------------------


@POSIX_ONLY
def test_update_moves_to_the_latest_release_and_records_it(world, capfd):
    world.install()
    (world.home / ".profile").write_text("mcp\n")
    (world.home / ".agent-name").write_text("sdpm\n")
    released = world.commit("release")
    world.tag("v0.13.0")
    world.commit("main moves on")
    assert world.update() == 0
    assert world.head() == released
    state = world.state()
    assert state["version"] == {"tag": "v0.13.0", "commit": released} and state["channel"] == "release"
    out = capfd.readouterr().out
    assert f"Updating {cu.short(world.base)} → v0.13.0 ({cu.short(released)})." in out
    assert "Update complete." in out
    assert not (world.home / ".profile").exists() and not (world.home / ".agent-name").exists()
    assert (world.home / ".uv-path").read_text().strip() == str(world.uv)
    assert git(world.checkout, "status", "--porcelain") == ""


@POSIX_ONLY
def test_a_main_user_stays_until_a_release_contains_the_commit(world, capfd):
    world.tag("v0.13.0", world.base)
    ahead = world.commit("main ahead")
    world.install(at=ahead)
    assert world.update() == 0
    assert world.head() == ahead
    out = capfd.readouterr().out
    assert "no release contains it yet (latest: v0.13.0); sdpm update moves on once one does." in out
    world.tag("v0.13.1", ahead)
    assert world.update() == 0
    assert world.state()["version"]["tag"] == "v0.13.1"
    assert "Up to date: v0.13.1" in capfd.readouterr().out


@POSIX_ONLY
def test_channel_main_follows_main_and_release_goes_back_without_moving(world, capfd):
    world.tag("v0.13.0", world.base)
    world.install()
    tip = world.commit("main ahead")
    assert world.update("--channel", "main") == 0
    assert world.head() == tip and world.state()["channel"] == "main"
    assert "Following main" in capfd.readouterr().out
    assert world.update("--channel", "release") == 0
    assert world.head() == tip and world.state()["channel"] == "release"
    assert "Staying on" in capfd.readouterr().out


@POSIX_ONLY
def test_local_changes_go_to_a_named_stash_and_the_checkout_detaches(world, capfd):
    world.install()
    released = world.commit("release", {"uv.lock": "new lock\n"})
    world.tag("v0.13.0")
    (world.checkout / "uv.lock").write_text("rewritten by uv\n")
    (world.checkout / "mine.txt").write_text("untracked\n")
    assert world.update() == 0
    assert world.head() == released
    assert subprocess.run(["git", "-C", str(world.checkout), "symbolic-ref", "-q", "HEAD"]).returncode != 0
    assert (world.checkout / "mine.txt").read_text() == "untracked\n"
    stash = git(world.checkout, "rev-parse", "refs/stash")
    assert git(world.checkout, "show", f"{stash}:uv.lock") == "rewritten by uv"
    assert git(world.checkout, "log", "-1", "--format=%s", "refs/stash").split(": ", 1)[1].startswith("sdpm update ")
    assert f"stash apply {stash}" in capfd.readouterr().out


@POSIX_ONLY
def test_a_failed_checkout_keeps_everything(world, capfd):
    world.install()
    world.commit("release", {"new.txt": "tracked upstream\n"})
    world.tag("v0.13.0")
    before = world.head()
    (world.checkout / "new.txt").write_text("an untracked file in the way\n")
    assert world.update() == 1
    assert world.head() == before
    assert (world.checkout / "new.txt").read_text() == "an untracked file in the way\n"
    assert "Nothing was discarded" in capfd.readouterr().err


def test_no_reset_clean_or_force_in_git_argv():
    tree = ast.parse(SOURCE)
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not {"reset", "clean", "--force", "-f"} & strings


# ---------------------------------------------------------------------------
# Rollback by the sentinel rule
# ---------------------------------------------------------------------------

FAIL_SYNC = "prepare_python = lambda checkout, uv: 1"
RAISE = '''def prepare_python(checkout, uv):
    raise RuntimeError("test: boom")'''
EXIT_2 = "sys.exit(2)"


@POSIX_ONLY
@pytest.mark.parametrize("snippet,message", [(FAIL_SYNC, "Could not sync"), (RAISE, "RuntimeError"),
                                             (EXIT_2, "")])
def test_a_target_that_fails_before_the_sentinel_is_rolled_back(world, capfd, snippet, message):
    world.install()
    before = world.head()
    world.commit("broken release", {"servers/local/checkout_update.py": variant(snippet)})
    world.tag("v0.13.0")
    state = (world.home / "state.json").read_bytes()
    assert world.update() == 1
    assert world.head() == before
    assert (world.home / "state.json").read_bytes() == state
    err = capfd.readouterr().err
    assert message in err and "Back on" in err and "as before" in err
    assert not (world.home / "update-prepared").exists()
    rollback = [c for c in world.calls() if "prepare" in c]
    assert rollback, "the previous tree's environment was not prepared again"


@POSIX_ONLY
def test_a_target_without_the_contract_is_never_moved_to(world, capfd):
    world.install()
    before = world.head()
    world.commit("no contract", {"servers/local/checkout_update.py": SOURCE.replace("UPDATER_CONTRACT = 1", "X = 1")})
    world.tag("v0.13.0")
    assert world.update() == 1
    assert world.head() == before
    assert "cannot be installed by sdpm update" in capfd.readouterr().err


@POSIX_ONLY
def test_a_failure_after_the_sentinel_is_not_rolled_back(world, monkeypatch):
    world.install()
    released = world.commit("release")
    world.tag("v0.13.0")
    monkeypatch.setenv("FAKE_UV_CLIENTS_RC", "1")
    assert world.update() == 1
    assert world.head() == released
    assert world.state()["version"]["commit"] == released


@POSIX_ONLY
def test_install_maps_a_failure_after_the_sentinel_to_4(world, monkeypatch, capfd):
    world.tag("v0.13.0", world.base)
    world.home.mkdir()
    git(world.tmp, "clone", "-q", "--branch", "main", str(world.upstream), str(world.checkout))
    monkeypatch.setenv("FAKE_UV_CLIENTS_RC", "1")
    rc = world.run("install", "--launcher", str(world.launcher), "--profile", "mcp", "--register", "yes",
                   "--new-checkout")
    assert rc == 4
    assert world.launcher.is_file() and cu.bootstrap_version(world.launcher) == 1


@POSIX_ONLY
def test_a_new_install_whose_finish_fails_stays_at_the_target_and_retries_fresh(world, monkeypatch, capfd):
    world.commit("release")
    released = world.tag("v0.13.0")
    world.commit("main ahead")
    world.home.mkdir()
    git(world.tmp, "clone", "-q", "--branch", "main", str(world.upstream), str(world.checkout))
    monkeypatch.setenv("FAKE_UV_SYNC_RC", "1")
    args = ["install", "--launcher", str(world.launcher), "--profile", "mcp", "--register", "no"]
    assert world.run(*args, "--new-checkout") == 1
    assert world.head() == released  # no previous commit to return to
    assert "Run the installer again" in capfd.readouterr().err
    assert cu.is_fresh(world.home)
    monkeypatch.setenv("FAKE_UV_SYNC_RC", "0")
    assert world.run(*args) == 0  # the retry: an existing checkout, still fresh
    assert world.head() == released
    assert "Installing v0.13.0" in capfd.readouterr().out


@POSIX_ONLY
@pytest.mark.parametrize("channel,tagged", [("main", False), ("main", True), ("release", False)])
def test_a_new_install_names_what_it_installs_on_each_channel(world, capfd, channel, tagged):
    if tagged:
        world.tag("v0.13.0", world.base)
    tip = world.commit("main ahead")
    world.home.mkdir()
    git(world.tmp, "clone", "-q", "--branch", "main", str(world.upstream), str(world.checkout))
    assert world.run("install", "--launcher", str(world.launcher), "--profile", "mcp", "--register", "no",
                     "--new-checkout", "--channel", channel) == 0
    assert world.head() == tip and world.state()["channel"] == channel
    out = capfd.readouterr().out
    no_release = "No release can be installed yet"
    if channel == "main":
        assert "Following main" in out and no_release not in out
        assert f"Installing {cu.labelled(str(world.checkout), tip)}." in out
    else:
        assert f"{no_release}; installing main {cu.short(tip)}." in out


def test_install_without_profile_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit) as stop:
        cu.main(["--checkout", str(tmp_path), "--uv", "uv", "install", "--launcher", "/x"])
    assert stop.value.code == 2


@POSIX_ONLY
def test_sigint_during_prepare_rolls_back_and_exits_130(world, tmp_path):
    world.install()
    before = world.head()
    started = tmp_path / "started"
    world.commit("slow release", {"servers/local/checkout_update.py": variant(
        f'''def prepare_python(checkout, uv):
    open({str(started)!r}, "w").close()
    time.sleep(30)
    return 0''')})
    world.tag("v0.13.0")
    world.fetch()
    proc = subprocess.Popen([sys.executable, str(LOCAL / "checkout_update.py"), "--checkout", str(world.checkout),
                             "--uv", str(world.uv), "update", "--launcher", str(world.launcher)],
                            start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline = time.time() + 30
    while not started.exists() and time.time() < deadline:
        time.sleep(0.1)
    assert started.exists()
    t0 = time.time()
    os.killpg(proc.pid, signal.SIGINT)
    out, _ = proc.communicate(timeout=30)
    assert proc.returncode == 130, out
    assert time.time() - t0 < 20  # the child reacted to SIGINT (it would sleep 30 s otherwise)
    assert world.head() == before


# ---------------------------------------------------------------------------
# Old launchers: pull (#532) and adopt (#529, #397)
# ---------------------------------------------------------------------------


@POSIX_ONLY
def test_pull_on_a_tree_without_the_contract_prints_the_stay_line(world, capfd):
    old = world.commit("pre-0.13", {"servers/local/checkout_update.py": "# no contract\n"})
    world.install()
    assert world.head() == old
    (world.home / "state.json").unlink()
    (world.home / ".profile").write_text("mcp\n")
    world.commit("main ahead", {"servers/local/checkout_update.py": SOURCE})
    git(world.checkout, "fetch", "-q", "origin", "main")  # what the #532 launcher does
    assert cu.main(["--checkout", str(world.checkout), "pull"]) == 0
    out = capfd.readouterr().out
    assert "no release contains it yet (the first is v0.13.0)" in out  # a stay on a tree without the contract
    assert world.head() == old


@POSIX_ONLY
def test_pull_moves_to_the_release_and_refreshes_tags_first(world, capfd):
    world.install()
    git(world.upstream, "tag", "v0.13.0", world.base)
    world.fetch()
    git(world.upstream, "tag", "-d", "v0.13.0")  # yanked upstream: the fetch in pull prunes it
    released = world.commit("release")
    world.tag("v0.13.1")
    (world.home / "state.json").unlink()
    assert cu.main(["--checkout", str(world.checkout), "pull"]) == 0
    assert world.head() == released
    assert "v0.13.0" not in git(world.checkout, "tag", "-l")
    assert capfd.readouterr().out == ""  # the adopt later in the same run prints the one version line


def test_pull_with_an_invalid_channel_exits_2(world, monkeypatch):
    world.install()
    monkeypatch.setenv("SDPM_CHANNEL", "nightly")
    assert cu.main(["--checkout", str(world.checkout), "pull"]) == 2


@POSIX_ONLY
def test_adopt_names_the_users_commit_and_lands_on_the_release(world, capfd):
    world.commit("pre-0.13", {"servers/local/checkout_update.py": "# no contract\n"})
    user = git(world.upstream, "rev-parse", "HEAD")
    released = world.commit("release", {"servers/local/checkout_update.py": SOURCE})
    world.tag("v0.13.0")
    tip = world.commit("main tip")
    world.install(at=tip, bootstrap=False)
    (world.home / "state.json").unlink()
    (world.home / ".profile").write_text("mcp\n")
    (world.home / ".agent-name").write_text("sdpm\n")
    world.launcher.write_text("#!/bin/sh\n# sdpm — the one launcher for a local SDPM installation (~/.sdpm).\n")
    assert world.run("adopt", "--from", user, "--launcher", str(world.launcher), "--prepared", "all") == 0
    assert world.head() == released
    out = capfd.readouterr().out
    assert len(re.findall(r"^Updating .* → v0\.13\.0", out, re.MULTILINE)) == 1
    assert f"Updating {cu.short(user)}" in out
    assert cu.bootstrap_version(world.launcher) == 1
    assert (world.home / ".profile").exists() and (world.home / ".agent-name").exists()  # the old launcher reads them
    assert not (world.home / "adopt-from").exists()


@POSIX_ONLY
def test_an_adopt_that_rolls_back_keeps_its_base_for_the_next_update(world, capfd):
    user = world.commit("pre-0.13", {"servers/local/checkout_update.py": "# no contract\n"})
    world.commit("broken release", {"servers/local/checkout_update.py": variant(FAIL_SYNC)})
    world.tag("v0.13.0")
    tip = world.commit("main tip, fixed", {"servers/local/checkout_update.py": SOURCE})
    world.install(at=tip, bootstrap=False)
    (world.home / "state.json").unlink()
    (world.home / ".profile").write_text("mcp\n")
    world.launcher.write_text("# the one launcher for a local SDPM installation\n")
    assert world.run("adopt", "--from", user, "--launcher", str(world.launcher), "--prepared", "all") == 1
    assert world.head() == tip
    assert (world.home / "adopt-from").read_text().strip() == user
    fixed = world.commit("fixed release")
    world.tag("v0.13.1")
    assert world.update() == 0  # base from adopt-from: the release, not the main tip
    assert world.head() == fixed
    assert not (world.home / "adopt-from").exists()


@POSIX_ONLY
def test_adopt_before_the_first_release_prints_the_transition_line_once(world, capfd):
    user = world.commit("pre-0.13", {"servers/local/checkout_update.py": "# no contract\n"})
    tip = world.commit("main tip", {"servers/local/checkout_update.py": SOURCE})
    world.install(at=tip, bootstrap=False)
    (world.home / "state.json").unlink()
    world.launcher.write_text("# the one launcher for a local SDPM installation\n")
    assert world.run("adopt", "--from", user, "--launcher", str(world.launcher), "--prepared", "all") == 0
    out = capfd.readouterr().out
    assert out.count(f"This update moved to main {cu.short(tip)}") == 1
    assert "Staying on" not in out and "Updating" not in out


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


def test_finish_argv_drops_what_the_target_does_not_know_and_stops_on_a_request(tmp_path):
    run = cu.Run(str(tmp_path / "checkout"), "/uv")
    options = [("--entry", "update", False), ("--channel", "main", True)]
    argv = cu._finish_argv(run, Path("/x.py"), 1, options, "v0.13.0")
    assert argv[:len(cu.PY_ARGS) + 1] == ["/uv", *cu.PY_ARGS]
    assert "--isolated" in argv and argv[-4:] == ["--entry", "update", "--channel", "main"]
    with pytest.raises(cu.Stop):
        cu._finish_argv(run, Path("/x.py"), 0, options, "v0.13.0")


def test_the_v1_finish_parser_accepts_the_current_argv_and_finish_ignores_unknown_options():
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
    import finish_contract_v1 as v1

    argv = ["finish", "--entry", "update", "--previous", "a" * 40, "--since", "b" * 40, "--launcher", "/l",
            "--profile", "mcp", "--agent-name", "sdpm", "--channel", "release", "--register", "default",
            "--non-interactive", "--prepared", "all"]
    v1.parse(argv)
    args, extra = cu._parser().parse_known_args(["--checkout", "/c", "--uv", "/u", *argv, "--from-the-future", "x"])
    assert args.command == "finish" and args.since == "b" * 40 and extra == ["--from-the-future", "x"]
    assert set(cu.FINISH_OPTIONS) == set(v1.OPTIONS)


def test_child_env_has_no_virtual_env(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/.venv")
    env = cu.child_env({"SDPM_UPDATER": "1"})
    assert "VIRTUAL_ENV" not in env and env["SDPM_UPDATER"] == "1"


@pytest.mark.skipif(sys.version_info < (3, 10), reason="sys.stdlib_module_names is 3.10+")
def test_stage_1_is_one_standard_library_file():
    tree = ast.parse(SOURCE)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert names <= set(sys.stdlib_module_names) | {"__future__"}
    assert SOURCE.count(GUARD) == 1 and re.search(r"^UPDATER_CONTRACT = \d+$", SOURCE, re.MULTILINE)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def test_load_state_migrates_the_old_files_and_validates_each_field(tmp_path, capsys):
    (tmp_path / ".profile").write_text("mcp\n")
    (tmp_path / ".agent-name").write_text("my-agent\n")
    state = cu.load_state(tmp_path)
    assert (state["present"], state["profile"], state["agent_name"], state["channel"]) == (False, "mcp", "my-agent",
                                                                                         "release")
    (tmp_path / ".agent-name").write_text("../evil\n")
    assert cu.load_state(tmp_path)["agent_name"] == "sdpm"
    (tmp_path / "state.json").write_text(json.dumps({"schema": 1, "channel": "nightly", "profile": "x",
                                                     "agent_name": "-x", "version": {"commit": "zz"}}))
    state = cu.load_state(tmp_path)
    assert (state["channel"], state["profile"], state["agent_name"], state["commit"]) == ("release", "full", "sdpm",
                                                                                        None)
    assert capsys.readouterr().err.count("state.json") >= 3
    (tmp_path / "state.json").write_text("{not json")
    assert cu.load_state(tmp_path)["present"] is False


def test_an_old_launchers_late_profile_full_wins(tmp_path):
    cu.write_state(tmp_path, channel="release", profile="mcp", agent_name="sdpm", commit="a" * 40, tag=None,
                   clients=[])
    (tmp_path / ".profile").write_text("full\n")
    assert cu.load_state(tmp_path)["profile"] == "full"


def test_write_state_keeps_unknown_keys_and_one_key_per_line(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"schema": 2, "future": {"x": 1}}))
    cu.write_state(tmp_path, channel="main", profile="full", agent_name="sdpm", commit="a" * 40, tag="v0.13.0",
                   clients=["kiro-cli"])
    text = (tmp_path / "state.json").read_text()
    data = json.loads(text)
    assert data["future"] == {"x": 1} and data["channel"] == "main" and data["version"]["tag"] == "v0.13.0"
    assert re.search(r'^  "profile": "full",$', text, re.MULTILINE)  # what the bash installer reads
    assert not list(tmp_path.glob(".state.json-*"))


def test_record_clients_folds_here_registered_and_unregistered(tmp_path):
    cu.write_state(tmp_path, channel="release", profile="mcp", agent_name="sdpm", commit="a" * 40, tag=None,
                   clients=["vscode", "codex"])
    record = tmp_path / "record.json"
    record.write_text(json.dumps({"here": ["kiro-cli"], "registered": ["claude-code"], "unregistered": ["codex"]}))
    cu.record_clients(tmp_path, record)
    assert cu.load_state(tmp_path)["clients"] == ["claude-code", "kiro-cli", "vscode"]


@pytest.mark.parametrize("name,ok", [("sdpm", True), ("sdpm-dev.2", True), ("-x", False), (".", False),
                                     ("a:b", False), ("a/b", False), ("x" * 65, False), ("", False)])
def test_agent_name_is_one_portable_file_name(name, ok):
    assert cu.valid_agent_name(name) is ok


def test_an_invalid_agent_name_option_exits_2(tmp_path):
    assert cu.main(["--checkout", str(tmp_path), "--uv", "/uv", "install", "--launcher", "/l", "--profile", "mcp",
                    "--agent-name", "a:b"]) == 2


@POSIX_ONLY
def test_agent_name_is_recorded_only_by_an_install(world, monkeypatch):
    world.install()
    cu.write_state(world.home, channel="release", profile="mcp", agent_name="foo", commit=world.base, tag=None,
                   clients=[])
    monkeypatch.setenv("SDPM_AGENT_NAME", "bar")  # old launchers always export one
    assert world.update() == 0
    assert world.state()["agent_name"] == "foo"
    monkeypatch.delenv("SDPM_AGENT_NAME")
    assert world.run("install", "--launcher", str(world.launcher), "--profile", "mcp", "--register", "no") == 0
    assert world.state()["agent_name"] == "foo"  # no option: the recorded name
    assert world.run("install", "--launcher", str(world.launcher), "--profile", "mcp", "--register", "no",
                     "--agent-name", "baz") == 0
    assert world.state()["agent_name"] == "baz"


# ---------------------------------------------------------------------------
# finish: clients and the launcher
# ---------------------------------------------------------------------------


def _client_calls(world):
    return [c for c in world.calls() if any(str(a).endswith("client_config.py") for a in c)]


def test_finish_clients_asks_only_on_a_fresh_install_with_a_terminal(tmp_path, monkeypatch, capsys):
    import argparse

    monkeypatch.setattr(cu, "tty_allowed", lambda non_interactive=False: True)
    called = []
    monkeypatch.setattr(cu.subprocess, "call", lambda argv, **_k: called.append(argv) or 0)
    args = argparse.Namespace(register="default", since="", entry="update", uv="/uv", agent_name="sdpm",
                              non_interactive=False)
    assert cu.finish_clients(args, tmp_path / "checkout", tmp_path, fresh=True) == 0
    assert called == [] and "Non-interactive" in capsys.readouterr().out  # sdpm update never prompts
    args.entry = "adopt"
    assert cu.finish_clients(args, tmp_path / "checkout", tmp_path, fresh=True) == 0
    assert called == []
    args.entry = "install"
    assert cu.finish_clients(args, tmp_path / "checkout", tmp_path, fresh=True) == 0
    assert "register" in called[-1] and "--yes" not in called[-1]  # the picker
    monkeypatch.setattr(cu, "tty_allowed", lambda non_interactive=False: False)
    called.clear()
    assert cu.finish_clients(args, tmp_path / "checkout", tmp_path, fresh=True) == 0
    assert called == []


@POSIX_ONLY
def test_a_fresh_install_registers_and_writes_a_missing_launcher(world, monkeypatch):
    world.tag("v0.13.0", world.base)
    world.home.mkdir()
    git(world.tmp, "clone", "-q", "--branch", "main", str(world.upstream), str(world.checkout))
    monkeypatch.setenv("FAKE_UV_RECORD", json.dumps({"registered": ["claude-code"]}))
    assert world.run("install", "--launcher", str(world.launcher), "--profile", "mcp", "--register", "yes",
                     "--new-checkout") == 0
    calls = _client_calls(world)
    assert calls and "register" in calls[-1] and "--yes" in calls[-1]
    assert world.launcher.read_bytes() == (INSTALL / "launcher.sh").read_bytes()
    assert world.state()["clients"] == ["claude-code"]


@POSIX_ONLY
def test_an_existing_install_is_refreshed_and_update_never_asks(world, monkeypatch, tmp_path):
    world.tag("v0.13.0", world.base)
    world.install()
    assert world.update() == 0
    assert "refresh" in _client_calls(world)[-1]
    # Fresh (all three files gone) on update: never the picker, even with a terminal.
    for name in ("state.json", ".uv-path"):
        (world.home / name).unlink()
    world.log.unlink()
    monkeypatch.setattr(cu, "tty_allowed", lambda non_interactive=False: True)
    # Nothing recorded means profile full (today's default): give it an npm that builds.
    monkeypatch.setenv("PATH", str(_fake_npm(tmp_path, 0)) + os.pathsep + os.environ["PATH"])
    (world.checkout / "web-ui").mkdir()
    assert world.update() == 0
    assert _client_calls(world) == []


@POSIX_ONLY
def test_a_foreign_launcher_is_left_alone_and_fails_the_install(world, capfd):
    world.tag("v0.13.0", world.base)
    world.install()
    world.launcher.write_text("#!/bin/sh\necho mine\n")
    rc = world.run("install", "--launcher", str(world.launcher), "--profile", "mcp", "--register", "no")
    assert rc == 4
    assert world.launcher.read_text() == "#!/bin/sh\necho mine\n"
    assert "is not an SDPM launcher; it was left alone" in capfd.readouterr().err


@POSIX_ONLY
def test_register_no_skips_the_clients(world, capfd):
    world.tag("v0.13.0", world.base)
    world.install()
    assert world.run("install", "--launcher", str(world.launcher), "--profile", "mcp", "--register", "no") == 0
    assert _client_calls(world) == []
    assert "Skipping client registration" in capfd.readouterr().out


@POSIX_ONLY
def test_finish_passes_since_not_previous_to_refresh(world):
    world.install()
    released = world.commit("release")
    world.tag("v0.13.0")
    assert world.update() == 0
    call = _client_calls(world)[-1]
    assert call[call.index("--since") + 1] == world.base
    assert world.head() == released


# ---------------------------------------------------------------------------
# The Web UI backup
# ---------------------------------------------------------------------------


def _webui(checkout: Path, stamp: str = "") -> None:
    (checkout / "web-ui" / "node_modules").mkdir(parents=True, exist_ok=True)
    (checkout / "web-ui" / "node_modules" / "old").write_text("old\n")
    (checkout / "web-ui" / "build").mkdir(parents=True, exist_ok=True)
    (checkout / "web-ui" / "build" / "index").write_text("old build\n")
    if stamp:
        (checkout / "web-ui" / "build" / cu.STAMP).write_text(stamp + "\n")


def _aside(home: Path, checkout: Path, *, complete: bool = True) -> None:
    backup = cu.backup_dir(home)
    backup.mkdir(parents=True)
    for name in cu.WEBUI_PARTS:
        os.replace(str(checkout / "web-ui" / name), str(backup / name))
    if complete:
        (backup / ".complete").write_text("")


def test_recover_webui_puts_a_build_back_unless_it_matches_expected(tmp_path):
    home, checkout = tmp_path, tmp_path / "checkout"
    old, new = "a" * 40, "b" * 40
    _webui(checkout, old)
    _aside(home, checkout)  # a hard kill during the build: .complete, no new stamp
    (checkout / "web-ui" / "node_modules").mkdir()
    assert cu.recover_webui(home, checkout, new)
    assert (checkout / "web-ui" / "node_modules" / "old").exists() and cu.read_stamp(checkout) == old
    assert not cu.backup_dir(home).exists()
    _aside(home, checkout)
    (checkout / "web-ui" / "build").mkdir()
    (checkout / "web-ui" / "build" / cu.STAMP).write_text(new + "\n")
    assert cu.recover_webui(home, checkout, new)  # the new build completed: keep it, drop the backup
    assert cu.read_stamp(checkout) == new and not cu.backup_dir(home).exists()


def test_recover_webui_finishes_a_half_done_put_back_without_deleting_what_it_restored(tmp_path):
    home, checkout = tmp_path, tmp_path / "checkout"
    _webui(checkout, "a" * 40)
    _aside(home, checkout)
    os.replace(str(cu.backup_dir(home) / "node_modules"), str(checkout / "web-ui" / "node_modules"))  # put back 1/2
    assert cu.recover_webui(home, checkout, "c" * 40)
    assert (checkout / "web-ui" / "node_modules" / "old").exists()
    assert (checkout / "web-ui" / "build" / "index").exists()


def test_recover_webui_without_complete_renames_back_only_what_is_missing(tmp_path):
    home, checkout = tmp_path, tmp_path / "checkout"
    _webui(checkout, "a" * 40)
    backup = cu.backup_dir(home)
    backup.mkdir()
    os.replace(str(checkout / "web-ui" / "node_modules"), str(backup / "node_modules"))  # killed between renames
    assert cu.recover_webui(home, checkout, "c" * 40)
    assert (checkout / "web-ui" / "node_modules" / "old").exists()
    assert cu.read_stamp(checkout) == "a" * 40 and not backup.exists()


def _fake_npm(tmp_path: Path, build_rc: int) -> Path:
    bin_dir = tmp_path / "npm-bin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(f"""#!/bin/sh
if [ "$1" = ci ]; then mkdir -p node_modules && echo new > node_modules/new; exit 0; fi
if [ "$1" = run ]; then mkdir -p build && echo new > build/index; exit {build_rc}; fi
""")
    npm.chmod(0o755)
    return bin_dir


@POSIX_ONLY
def test_a_failed_web_ui_build_puts_the_previous_one_back_and_rolls_back(world, monkeypatch, tmp_path):
    world.install()
    before = world.head()
    cu.write_state(world.home, channel="release", profile="full", agent_name="sdpm", commit=before, tag=None,
                   clients=[])
    _webui(world.checkout, before)
    world.commit("release")
    world.tag("v0.13.0")
    monkeypatch.setenv("PATH", str(_fake_npm(tmp_path, 1)) + os.pathsep + os.environ["PATH"])
    assert world.update() == 1
    assert world.head() == before
    assert (world.checkout / "web-ui" / "node_modules" / "old").exists()
    assert cu.read_stamp(world.checkout) == before
    assert not cu.backup_dir(world.home).exists()


@POSIX_ONLY
def test_a_finish_that_built_and_then_stopped_before_the_sentinel_gets_the_old_web_ui_back(world, monkeypatch,
                                                                                          tmp_path):
    world.install()
    before = world.head()
    cu.write_state(world.home, channel="release", profile="full", agent_name="sdpm", commit=before, tag=None,
                   clients=[])
    _webui(world.checkout, before)
    world.commit("release", {"servers/local/checkout_update.py": variant(
        '''_real_write_atomic = write_atomic


def write_atomic(path, text):
    if path.name == "update-prepared":
        sys.exit(1)
    _real_write_atomic(path, text)''')})
    world.tag("v0.13.0")
    monkeypatch.setenv("PATH", str(_fake_npm(tmp_path, 0)) + os.pathsep + os.environ["PATH"])
    assert world.update() == 1
    assert world.head() == before
    assert (world.checkout / "web-ui" / "node_modules" / "old").exists()
    assert cu.read_stamp(world.checkout) == before
    assert not cu.backup_dir(world.home).exists()


@POSIX_ONLY
def test_the_stamp_skips_the_rebuild_and_prepared_all_stamps_only_full(world, monkeypatch, tmp_path, capfd):
    world.tag("v0.13.0", world.base)
    world.install()
    cu.write_state(world.home, channel="release", profile="full", agent_name="sdpm", commit=world.base, tag=None,
                   clients=[])
    _webui(world.checkout, world.base)
    monkeypatch.setenv("PATH", str(_fake_npm(tmp_path, 1)) + os.pathsep + os.environ["PATH"])  # would fail
    assert world.update() == 0
    assert "Web UI: up to date" in capfd.readouterr().out
    (world.checkout / "web-ui" / "build" / cu.STAMP).unlink()
    cu.write_state(world.home, profile="mcp")
    assert world.run("adopt", "--from", world.base, "--launcher", str(world.launcher), "--prepared", "all") == 0
    assert cu.read_stamp(world.checkout) is None  # a stale build on mcp is not stamped


@POSIX_ONLY
def test_finish_with_a_leftover_backup_exits_3(world):
    world.install()
    cu.backup_dir(world.home).mkdir()
    rc = world.run("finish", "--entry", "update", "--launcher", str(world.launcher), "--profile", "mcp")
    assert rc == 3


# ---------------------------------------------------------------------------
# Release manifests
# ---------------------------------------------------------------------------

SHA = "c" * 40


def manifest(**overrides):
    data = {"schema": 1, "version": "0.13.0", "tag": "v0.13.0", "commit": SHA, "os": "linux", "use": "update",
            "min_launcher": 1, "requires": [{"name": "uv", "min": "0.5.0", "profiles": ["full", "mcp"],
                                             "help": "https://docs.astral.sh/uv/"}],
            "notes": ["Run sdpm register once."]}
    data.update(overrides)
    return data


def test_parse_manifest_accepts_schema_1_and_a_higher_schema():
    assert cu.parse_manifest(manifest(), tag="v0.13.0", os_name="linux", use="update")["min_launcher"] == 1
    assert cu.parse_manifest(manifest(schema=2, extra=1), tag="v0.13.0", os_name="linux", use="update")


@pytest.mark.parametrize("field,value", [
    ("schema", 0), ("schema", True), ("version", "0.13"), ("tag", "v0.13.1"), ("commit", "xyz"), ("os", "macos"),
    ("use", "install"), ("min_launcher", 1001), ("min_launcher", "1"), ("requires", [{"name": "uv"}] * 21),
    ("requires", [{"name": "uv", "min": "latest"}]), ("requires", [{"name": "uv", "min": "1", "profiles": ["x"]}]),
    ("notes", ["x" * 501]), ("notes", "text"),
])
def test_parse_manifest_rejects_each_invalid_field(field, value):
    with pytest.raises(ValueError):
        cu.parse_manifest(manifest(**{field: value}), tag="v0.13.0", os_name="linux", use="update")


def test_manifest_text_loses_control_characters():
    parsed = cu.parse_manifest(manifest(notes=["\x1b[31mred\x1b[0m\x07"]), tag="v0.13.0", os_name="linux",
                               use="update")
    assert parsed["notes"] == ["[31mred[0m"]


def test_fetch_manifest_from_files(tmp_path):
    base = tmp_path.as_uri()
    assert cu.fetch_manifest("v0.13.0", "update", base=base, os_name="linux")[0] == "absent"
    write(tmp_path / "v0.13.0" / "release-linux-update.json", json.dumps(manifest()))
    status, data, _ = cu.fetch_manifest("v0.13.0", "update", base=base, os_name="linux")
    assert status == "ok" and data["commit"] == SHA
    write(tmp_path / "v0.13.0" / "release-linux-update.json", "{")
    assert cu.fetch_manifest("v0.13.0", "update", base=base, os_name="linux")[0] == "error"
    write(tmp_path / "v0.13.0" / "release-linux-update.json", " " * (cu.MANIFEST_MAX_BYTES + 10))
    assert cu.fetch_manifest("v0.13.0", "update", base=base, os_name="linux")[2] == "larger than 64 KiB"


def test_fetch_manifest_times_out_on_a_stalled_server():
    release = threading.Event()

    class Stall(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            release.wait(10)

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Stall)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        status, _, reason = cu.fetch_manifest("v0.13.0", "update", base=f"http://127.0.0.1:{port}", timeout=0.5)
        assert status == "error" and reason
    finally:
        release.set()
        server.shutdown()


def test_the_release_base_url_override_is_https_or_file_only(capsys):
    assert cu.release_base_url({"SDPM_RELEASE_BASE_URL": "file:///tmp/r/"}) == "file:///tmp/r"
    assert cu.release_base_url({"SDPM_RELEASE_BASE_URL": "http://evil"}) == cu.RELEASE_BASE_URL
    assert "SDPM_RELEASE_BASE_URL" in capsys.readouterr().err


def test_requirements_python_never_stops_and_unknown_names_are_ignored(monkeypatch):
    monkeypatch.setattr(cu, "tool_version", lambda name, uv: {"uv": "0.4.0", "git": "2.40.0"}.get(name))
    data = cu.parse_manifest(manifest(requires=[
        {"name": "python", "min": "99", "profiles": ["mcp"]}, {"name": "rust", "min": "1"},
        {"name": "node", "min": "20", "profiles": ["full"]}, {"name": "uv", "min": "0.5.0"}]),
        tag="v0.13.0", os_name="linux", use="update")
    item, found = cu.unmet_requirement(data, "mcp", "/uv")
    assert item["name"] == "uv" and found == "0.4.0"


def _world_manifest(world, tag: str, commit: str, **overrides) -> None:
    os_name = cu.manifest_os()
    write(world.tmp / "releases" / tag / cu.manifest_name(os_name, "update"),
          json.dumps(manifest(tag=tag, version=tag[1:], commit=commit, os=os_name, **overrides)))


@POSIX_ONLY
def test_a_manifest_naming_another_commit_skips_that_release(world, capfd):
    world.install()
    first = world.commit("first")
    world.tag("v0.13.0")
    world.commit("second")
    world.tag("v0.13.1")
    _world_manifest(world, "v0.13.1", first)
    assert world.update() == 0
    assert world.head() == first
    captured = capfd.readouterr()
    assert "skipping v0.13.1" in captured.err and "Run sdpm register once." in captured.out


@POSIX_ONLY
def test_an_unmet_requirement_stops_before_moving(world, capfd):
    world.install()
    before = world.head()
    released = world.commit("release")
    world.tag("v0.13.0")
    _world_manifest(world, "v0.13.0", released,
                    requires=[{"name": "git", "min": "999", "profiles": ["mcp"], "help": "get a newer git"}])
    assert world.update() == 1
    assert world.head() == before
    assert "v0.13.0 needs git 999+" in capfd.readouterr().err


@POSIX_ONLY
def test_min_launcher_stops_only_for_a_launcher_that_cannot_be_replaced(world, capfd):
    world.install()
    before = world.head()
    released = world.commit("release")
    world.tag("v0.13.0")
    _world_manifest(world, "v0.13.0", released, min_launcher=2, requires=[])
    world.launcher.unlink()
    world.launcher.symlink_to(INSTALL / "launcher.sh")
    assert world.update() == 1
    assert world.head() == before
    assert "needs a newer sdpm command" in capfd.readouterr().err


@POSIX_ONLY
def test_exactly_one_manifest_fetch_per_update_and_none_on_main(world, monkeypatch):
    world.tag("v0.13.0", world.base)
    world.install()
    fetched = []
    real = cu.fetch_manifest
    monkeypatch.setattr(cu, "fetch_manifest", lambda *a, **k: (fetched.append(a), real(*a, **k))[1])
    assert world.update() == 0
    assert [a[:2] for a in fetched] == [("v0.13.0", "update")]
    fetched.clear()
    assert world.update("--channel", "main") == 0
    assert fetched == []


def test_manifest_probe_reports_absent_or_error(monkeypatch, capsys):
    monkeypatch.setattr(cu, "fetch_manifest", lambda *a, **k: ("absent", None, ""))
    assert cu.main(["--checkout", "/c", "manifest-probe", "--tag", "v0.12.0"]) == 0
    monkeypatch.setattr(cu, "fetch_manifest", lambda *a, **k: ("error", None, "TLS"))
    assert cu.main(["--checkout", "/c", "manifest-probe", "--tag", "v0.12.0"]) == 1
    assert capsys.readouterr().out.splitlines() == ["absent", "error: TLS"]


# ---------------------------------------------------------------------------
# The TTY rule
# ---------------------------------------------------------------------------


class _Stream:
    def __init__(self, tty: bool) -> None:
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


def test_tty_rule_needs_stdout_and_a_terminal(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _Stream(False))
    assert not cu.tty_allowed()
    monkeypatch.setattr(sys, "stdout", _Stream(True))
    assert not cu.tty_allowed(non_interactive=True)
    if sys.platform != "win32":
        def no_tty(*_a, **_k):
            raise OSError("no controlling terminal")

        monkeypatch.setattr(os, "open", no_tty)
        assert not cu.tty_allowed()
