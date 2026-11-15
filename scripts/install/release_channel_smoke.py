# SPDX-License-Identifier: MIT-0
"""The release-channel scenarios (R8) against a local mirror with test tags, on any OS.

    python3 scripts/install/release_channel_smoke.py --work /tmp/rc --profile mcp

CI runs it on ubuntu, macos and windows (.github/workflows/installer.yml, job
release-channel); it runs the same way locally. Everything goes into ``--work``: the mirror
(``SDPM_REPO_URL``), the install (``SDPM_HOME``, ``SDPM_LAUNCHER_DIR``) and the release
manifests, served from files (``SDPM_RELEASE_BASE_URL=file://…``). The test tags (v99.x) sit
on the mirror's ``main`` above every real tag, so the installs follow them. ``HOME`` and
``PATH`` are used as given, and step 9 installs with ``--register``: it registers every MCP
client it finds there. On a machine with your own clients, run it with ``HOME`` and
``KIRO_HOME`` set to temporary directories and no client CLIs on ``PATH``.

Steps (the numbers of the design's §13): 1 a new install lands on the tag, 2 up to date,
3 a main user stays, 4 --channel main, 5 the #397 / #529 / #532 launchers, 6 a changed
checkout, 7 rollback after a real environment change (offline), 8 rollback of a failed Web
UI build (full), 9 / 10 install and update without a terminal, 11 the manifest is read,
12 manifest fallback, 13 the real release URL. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
WINDOWS = sys.platform == "win32"
OLD_LAUNCHERS = {"7c53267d": "#397", "7a49558b": "#529", "7842f982": "#532"}
USER_COMMIT = "1c618b58"   # a real install's commit (v0.10.4-1)


def decode(data: bytes) -> str:
    """UTF-8, else the ANSI code page: a Windows pipe gets the updater's output in the latter."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(locale.getpreferredencoding(False), errors="replace")


class Failed(Exception):
    pass


def check(condition: bool, what: str) -> None:
    if not condition:
        raise Failed(what)


class Smoke:
    def __init__(self, work: Path, profile: str) -> None:
        self.work = work
        self.profile = profile
        self.mirror = work / "mirror.git"
        self.releases = work / "releases"
        self.home = work / "sdpm" / ".sdpm"
        self.bin = work / "bin"
        self.checkout = self.home / "checkout"
        self.env = dict(os.environ)
        self.env.update({
            "SDPM_HOME": str(self.home), "SDPM_LAUNCHER_DIR": str(self.bin), "SDPM_REPO_URL": str(self.mirror),
            "SDPM_RELEASE_BASE_URL": self.releases.as_uri(), "SDPM_SKIP_KIRO_CLI": "1",
            "GIT_AUTHOR_NAME": "ci", "GIT_AUTHOR_EMAIL": "ci@localhost",
            "GIT_COMMITTER_NAME": "ci", "GIT_COMMITTER_EMAIL": "ci@localhost",
        })
        self.env.pop("SDPM_CHANNEL", None)
        self.env.pop("VIRTUAL_ENV", None)
        local_bin = str(Path.home() / ".local" / "bin")
        self.env["PATH"] = local_bin + os.pathsep + self.env.get("PATH", "")

    # -- processes ----------------------------------------------------------------------

    def run(self, argv: List[str], *, env: Optional[Dict[str, str]] = None, timeout: float = 1200,
            quiet: bool = False) -> Tuple[int, str]:
        print("$ " + " ".join(argv), flush=True)
        try:
            res = subprocess.run(argv, env=env or self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as error:
            raise Failed(f"timed out after {timeout:.0f} s (it waited for input?): {argv}") from error
        text = decode(res.stdout)
        if not quiet:
            print(text, flush=True)
        return res.returncode, text

    def git(self, *args: str, cwd: Optional[Path] = None) -> str:
        res = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, env=self.env, capture_output=True,
                             text=True, check=False)
        if res.returncode != 0:
            raise Failed(f"git {' '.join(args)}: {res.stderr.strip()}")
        return res.stdout.strip()

    def mgit(self, *args: str) -> str:
        return self.git("-C", str(self.mirror), *args)

    def cgit(self, *args: str) -> str:
        return self.git("-C", str(self.checkout), *args)

    def uv(self) -> str:
        recorded = self.home / ".uv-path"
        if recorded.is_file():
            return recorded.read_text(encoding="utf-8").strip()
        found = shutil.which("uv", path=self.env["PATH"])
        check(found is not None, "uv is not on PATH")
        return str(found)

    def installer(self, *options: str, timeout: float = 1500) -> Tuple[int, str]:
        if WINDOWS:
            names = {"--mcp-only": "-McpOnly", "--full": "-Full", "--register": "-Register",
                     "--no-register": "-NoRegister", "--skip-libreoffice": "-SkipLibreOffice",
                     "--skip-shortcut": "-SkipShortcut", "--non-interactive": "-NonInteractive"}
            argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    str(REPO / "scripts" / "install" / "dist" / "install.ps1"), *[names[o] for o in options]]
        else:
            argv = ["bash", str(REPO / "scripts" / "install" / "dist" / "install.sh"), *options]
        return self.run(argv, timeout=timeout)

    def sdpm(self, *args: str, env: Optional[Dict[str, str]] = None, timeout: float = 1200) -> Tuple[int, str]:
        if WINDOWS:
            return self.run(["cmd", "/c", str(self.bin / "sdpm.cmd"), *args], env=env, timeout=timeout)
        return self.run([str(self.bin / "sdpm"), *args], env=env, timeout=timeout)

    @property
    def launcher(self) -> Path:
        return self.bin / ("sdpm.ps1" if WINDOWS else "sdpm")

    def launcher_source(self, rev: str = "") -> bytes:
        name = "scripts/install/" + ("launcher.ps1" if WINDOWS else "launcher.sh")
        if rev:
            data = subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{name}"], capture_output=True,
                                  check=True).stdout
        else:
            data = (REPO / name).read_bytes()
        return (b"\xef\xbb\xbf" + data) if WINDOWS and not data.startswith(b"\xef\xbb\xbf") else data

    # -- checks -------------------------------------------------------------------------

    def head(self) -> str:
        return self.cgit("rev-parse", "HEAD")

    def tag_sha(self, tag: str) -> str:
        return self.mgit("rev-parse", tag + "^{commit}")

    def state(self) -> dict:
        return json.loads((self.home / "state.json").read_text(encoding="utf-8"))

    def clean(self) -> None:
        status = self.cgit("status", "--porcelain")
        check(status == "", f"the checkout has changes:\n{status}")

    def handshake(self) -> None:
        argv = ([str(self.bin / "sdpm.cmd")] if WINDOWS else [str(self.bin / "sdpm")]) + ["mcp"]
        rc, out = self.run([sys.executable, str(REPO / "scripts" / "install" / "mcp_smoke.py"), *argv], quiet=True)
        check(rc == 0 and "OK:" in out, f"MCP handshake failed:\n{out}")

    def manifests(self, tag: str, commit: Optional[str] = None) -> None:
        commit = commit or self.tag_sha(tag)
        rc, out = self.run([self.uv(), "run", "--no-project", "--python", ">=3.11", "python",
                            str(REPO / "scripts" / "release" / "manifest.py"), "--tag", tag, "--commit", commit,
                            "--version", tag[1:], "--out", str(self.releases / tag)], quiet=True)
        check(rc == 0, f"manifest.py failed:\n{out}")

    def new_commit(self, message: str, parent: str = "main") -> str:
        """A commit with ``parent``'s tree on top of it; main moves there."""
        sha = self.mgit("commit-tree", f"{parent}^{{tree}}", "-p", parent, "-m", message)
        self.mgit("update-ref", "refs/heads/main", sha)
        return sha

    # -- steps --------------------------------------------------------------------------

    def setup(self) -> None:
        if self.work.exists():
            shutil.rmtree(str(self.work))
        self.work.mkdir(parents=True)
        self.git("clone", "-q", "--bare", str(REPO), str(self.mirror))
        self.mgit("branch", "-f", "main", self.git("-C", str(REPO), "rev-parse", "HEAD"))
        self.mgit("tag", "v99.0.0", "main")
        self.ahead = self.new_commit("main ahead")
        self.mgit("tag", "v99.1.0-rc.1", self.ahead)
        self.manifests("v99.0.0")

    def step1(self) -> None:
        profile = "--full" if self.profile == "full" else "--mcp-only"
        rc, out = self.installer(profile, "--non-interactive", "--skip-libreoffice", "--skip-shortcut",
                                 "--no-register")
        check(rc == 0, f"install exited {rc}")
        check(self.head() == self.tag_sha("v99.0.0"), "a new install is not on v99.0.0")
        state = self.state()
        check(state["channel"] == "release" and state["version"]["tag"] == "v99.0.0", f"state.json: {state}")
        check(self.launcher.read_bytes() == self.launcher_source(), "the installed launcher is not the bootstrap")
        check("Installing v99.0.0" in out, "no Installing line")
        self.clean()
        self.handshake()

    def step2(self) -> None:
        build = self.checkout / "web-ui" / "build"
        mtime = build.stat().st_mtime if build.exists() else None
        rc, out = self.sdpm("update")
        check(rc == 0 and "Up to date: v99.0.0" in out, "not up to date")
        if self.profile == "full":
            check(build.stat().st_mtime == mtime, "the Web UI was rebuilt")
        self.clean()

    def step3(self) -> None:
        self.cgit("-c", "advice.detachedHead=false", "checkout", "-q", "--detach", self.ahead)
        rc, out = self.sdpm("update")
        check(rc == 0, f"a stay exited {rc}")
        check(self.head() == self.ahead, "a main user was moved down")
        check("no release contains it yet (latest: v99.0.0)" in out, "no stay line")
        self.mgit("tag", "v99.1.0", self.ahead)
        self.manifests("v99.1.0")
        rc, out = self.sdpm("update")
        check(rc == 0 and self.state()["version"]["tag"] == "v99.1.0", "not on v99.1.0")
        self.clean()

    def step4(self) -> None:
        self.ahead2 = self.new_commit("main ahead 2", self.ahead)
        rc, out = self.sdpm("update", "--channel", "main")
        check(rc == 0 and self.head() == self.ahead2 and self.state()["channel"] == "main", "not on main")
        check("manifest" not in out, "the main channel read a manifest")
        rc, out = self.sdpm("update", "--channel", "release")
        check(rc == 0 and self.head() == self.ahead2 and self.state()["channel"] == "release", "release went down")
        self.clean()

    def old_install(self, rev: str) -> None:
        """What a real install with that launcher looks like."""
        self.cgit("checkout", "-q", "-f", "-B", "main", USER_COMMIT)
        (self.home / "state.json").unlink()
        (self.home / ".profile").write_text(self.profile + "\n", encoding="ascii")
        (self.home / ".agent-name").write_text("sdpm\n", encoding="ascii")
        self.launcher.write_bytes(self.launcher_source(rev))

    def step5(self, revs: Optional[List[str]] = None) -> None:
        latest = self.tag_sha("v99.1.0")
        for rev in revs or list(OLD_LAUNCHERS):
            print(f"--- the {OLD_LAUNCHERS[rev]} launcher ({rev})", flush=True)
            self.old_install(rev)
            rc, out = self.sdpm("update")
            check(rc == 0, f"{rev}: update exited {rc}")
            check(self.head() == latest, f"{rev}: not on v99.1.0")
            lines = re.findall(r"^Updating \S*1c618b5[0-9a-f]* (?:→|\?) v99\.1\.0", out, re.MULTILINE)
            check(len(lines) == 1, f"{rev}: {len(lines)} Updating lines naming the user's commit")
            check("What to do after this update:" in out, f"{rev}: no upgrading notes")
            check(re.search(r"sdpm\s+update\s+-\s*-\s*channel\s+main", out) is not None,
                  f"{rev}: the notes are not taken since the user's commit")
            check(b"sdpm-bootstrap" in self.launcher.read_bytes(), f"{rev}: the bootstrap is not installed")
            check((self.home / "state.json").is_file() and not (self.home / "adopt-from").exists(),
                  f"{rev}: state.json / adopt-from")
            check((self.home / ".profile").exists() and (self.home / ".agent-name").exists(),
                  f"{rev}: the files the old launcher reads were removed")
            if self.profile == "mcp":
                check(not (self.checkout / "web-ui" / "node_modules").exists(), f"{rev}: the Web UI was built")
            self.handshake()
            self.clean()
            rc, _ = self.sdpm("update")
            check(rc == 0, f"{rev}: the next update exited {rc}")
            check(not (self.home / ".profile").exists() and not (self.home / ".agent-name").exists(),
                  f"{rev}: .profile / .agent-name remain")
            check(self.state()["profile"] == self.profile, f"{rev}: the profile changed")

    def step5_529(self) -> None:
        self.step5(["7a49558b"])

    def step6(self) -> None:
        self.cgit("-c", "advice.detachedHead=false", "checkout", "-q", "--detach", "v99.0.0")
        for name, line in (("uv.lock", "# rewritten by uv"), ("web-ui/next-env.d.ts", "// rewritten by next build")):
            with open(str(self.checkout / name), "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        rc, out = self.sdpm("update")
        check(rc == 0 and self.head() == self.tag_sha("v99.1.0"), "a changed checkout did not update")
        check(self.cgit("log", "-1", "--format=%s", "refs/stash").split(": ", 1)[-1].startswith("sdpm update"),
              "no named stash")
        check("rewritten by next build" in self.cgit("show", "stash@{0}:web-ui/next-env.d.ts"), "the change is lost")
        check("stash apply" in out, "no stash apply line")
        self.clean()

    def step7(self) -> None:
        main_before = self.mgit("rev-parse", "main")
        work = self.work / "broken"
        self.git("clone", "-q", "--branch", "main", str(self.mirror), str(work))
        lock = (work / "uv.lock").read_text(encoding="utf-8")
        orig = re.search(r'name = "idna"\nversion = "([^"]+)"', lock).group(1)
        # Any idna other than the lock's that the tree still accepts (httpx2, via mcp 2.x,
        # needs >= 3.18).
        pin = "3.18"
        check(orig != pin, "pick another version")
        pyproject = (work / "pyproject.toml").read_text(encoding="utf-8")
        check("[tool.uv.workspace]" in pyproject, "no [tool.uv.workspace] in pyproject.toml")
        (work / "pyproject.toml").write_text(pyproject.replace(
            "[tool.uv.workspace]", f'[tool.uv]\nconstraint-dependencies = ["idna=={pin}"]\n\n[tool.uv.workspace]', 1),
            encoding="utf-8")
        rc, out = self.run([self.uv(), "lock", "--directory", str(work)], quiet=True)
        check(rc == 0, f"uv lock failed:\n{out}")
        check(f'name = "idna"\nversion = "{pin}"' in (work / "uv.lock").read_text(encoding="utf-8"), "idna not pinned")
        updater = work / "servers" / "local" / "checkout_update.py"
        source = updater.read_text(encoding="utf-8")
        guard = 'if __name__ == "__main__":'
        check(source.count(guard) == 1, "the guard is not unique")
        updater.write_text(source.replace(guard, (
            "_real_prepare_python = prepare_python\n\n\n"
            "def prepare_python(checkout, uv):\n"
            "    _real_prepare_python(checkout, uv)\n"
            '    raise RuntimeError("test: fail after sync")\n\n\n') + guard), encoding="utf-8")
        self.git("-C", str(work), "commit", "-qam", "test: a release whose finish fails after a real sync")
        self.git("-C", str(work), "push", "-q", "origin", "HEAD:refs/heads/main", "HEAD:refs/tags/v99.2.0")
        self.manifests("v99.2.0")
        # Warm uv's cache with the pinned wheel, as the same uv the update uses.
        rc, out = self.run([self.uv(), "sync", "--frozen", "--directory", str(work / "servers" / "local")], quiet=True)
        check(rc == 0, f"warming the cache failed:\n{out}")
        before = (self.home / "state.json").read_bytes()
        offline = dict(self.env, UV_OFFLINE="1")
        rc, out = self.sdpm("update", env=offline)
        check(rc == 1, f"a failed prepare exited {rc}")
        check(f"+ idna=={pin}" in out and "RuntimeError" in out and "Back on v99.1.0" in out, "no rollback lines")
        check(self.head() == self.tag_sha("v99.1.0"), "not back on v99.1.0")
        check((self.home / "state.json").read_bytes() == before, "state.json changed")
        rc, version = self.run([self.uv(), "run", "--no-sync", "--directory", str(self.checkout / "servers" / "local"),
                                "python", "-c", 'import importlib.metadata as m; print(m.version("idna"))'],
                               env=offline, quiet=True)
        check(version.strip().splitlines()[-1] == orig, f"idna is {version.strip()}, not {orig}")
        self.handshake()
        self.clean()
        self.mgit("tag", "-d", "v99.2.0")
        self.mgit("update-ref", "refs/heads/main", main_before)

    def step8(self) -> None:
        main_before = self.mgit("rev-parse", "main")
        work = self.work / "broken-webui"
        self.git("clone", "-q", "--branch", "main", str(self.mirror), str(work))
        package = json.loads((work / "web-ui" / "package.json").read_text(encoding="utf-8"))
        package["scripts"]["build"] = "exit 1"
        (work / "web-ui" / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
        self.git("-C", str(work), "commit", "-qam", "test: a release whose Web UI build fails")
        self.git("-C", str(work), "push", "-q", "origin", "HEAD:refs/heads/main", "HEAD:refs/tags/v99.2.0")
        self.manifests("v99.2.0")
        stamp = (self.checkout / "web-ui" / "build" / ".sdpm-source").read_text(encoding="utf-8")
        rc, out = self.sdpm("update")
        check(rc == 1 and "Back on v99.1.0" in out, f"a failed build exited {rc}")
        check((self.checkout / "web-ui" / "node_modules").is_dir(), "node_modules is gone")
        check((self.checkout / "web-ui" / "build" / ".sdpm-source").read_text(encoding="utf-8") == stamp,
              "the previous build is not back")
        check(not (self.home / "update-backup").exists(), "update-backup remains")
        rc, out = self.sdpm()
        check("webui      installed" in out, "the status does not see the Web UI")
        self.clean()
        self.mgit("tag", "-d", "v99.2.0")
        self.mgit("update-ref", "refs/heads/main", main_before)

    def step9_10(self) -> None:
        fresh = Smoke(self.work / "no-tty", self.profile)
        fresh.mirror, fresh.releases = self.mirror, self.releases
        fresh.env = dict(self.env, SDPM_HOME=str(fresh.home), SDPM_LAUNCHER_DIR=str(fresh.bin))
        fresh.work.mkdir()
        # No --non-interactive and no terminal: nothing may wait for input (the timeout fails it).
        rc, _ = fresh.installer("--mcp-only", "--register", "--skip-libreoffice", timeout=900)
        check(rc == 0, f"an install without a terminal exited {rc}")
        rc, _ = fresh.sdpm("update", timeout=300)
        check(rc == 0, f"an update without a terminal exited {rc}")
        rc, out = fresh.sdpm("register", timeout=120)
        check(rc in (0, 2), f"sdpm register without a terminal exited {rc}")

    def step11(self) -> None:
        main_before = self.mgit("rev-parse", "main")
        sha = self.new_commit("v99.3.0")
        self.mgit("tag", "v99.3.0", sha)
        self.manifests("v99.3.0", commit=self.tag_sha("v99.1.0"))  # names another commit
        rc, out = self.sdpm("update")
        check(rc == 0 and "skipping v99.3.0" in out, "the manifest's commit was not checked")
        check(self.head() == self.tag_sha("v99.1.0"), "moved to a release whose manifest disagrees")
        self.mgit("tag", "-d", "v99.3.0")
        self.mgit("update-ref", "refs/heads/main", main_before)

    def step12(self) -> None:
        empty = self.work / "no-manifests"
        empty.mkdir(exist_ok=True)
        rc, out = self.sdpm("update", env=dict(self.env, SDPM_RELEASE_BASE_URL=empty.as_uri()))
        check(rc == 0 and "manifest" not in out, "a release without manifests did not fall back quietly")
        self.clean()

    def step13(self) -> None:
        tags = [t for t in self.git("-C", str(REPO), "tag", "-l", "v*").split()
                if re.match(r"^v\d+\.\d+\.\d+$", t) and not t.startswith("v99.")]
        tag = max(tags, key=lambda t: tuple(int(p) for p in t[1:].split(".")))
        rc, out = self.run([self.uv(), "run", "--no-project", "--isolated", "--python", ">=3.11", "python",
                            str(REPO / "servers" / "local" / "checkout_update.py"), "--checkout", str(self.checkout),
                            "manifest-probe", "--tag", tag])
        check(rc == 0 and out.strip().splitlines()[-1] in ("ok", "absent"), f"the real release URL: {out.strip()}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        # A Windows pipe has the ANSI code page: print '?' for what it cannot encode, never fail.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--profile", choices=("mcp", "full"), default="mcp")
    parser.add_argument("--skip", default="", help="comma-separated step names to leave out (local runs)")
    args = parser.parse_args()
    smoke = Smoke(args.work.resolve(), args.profile)
    if args.profile == "full":
        steps = [smoke.setup, smoke.step1, smoke.step2, smoke.step3, smoke.step5_529, smoke.step8]
    else:
        steps = [smoke.setup, smoke.step1, smoke.step2, smoke.step3, smoke.step4, smoke.step5, smoke.step6,
                 smoke.step7, smoke.step9_10, smoke.step11, smoke.step12, smoke.step13]
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    for step in steps:
        name = step.__name__
        if name in skip:
            print(f"\n===== {name} skipped", flush=True)
            continue
        print(f"\n===== {name} =====", flush=True)
        started = time.time()
        try:
            step()
        except Failed as error:
            print(f"\nFAILED in {name}: {error}", file=sys.stderr, flush=True)
            return 1
        print(f"===== {name} passed ({time.time() - started:.0f} s)", flush=True)
    print("\nAll release-channel scenarios passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
