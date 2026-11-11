# SPDX-License-Identifier: MIT-0
"""The install lifecycle of a local SDPM installation (``~/.sdpm/checkout``).

The installed ``sdpm`` command is a bootstrap: it fetches, then runs this file from the
checkout (``update``). The installer runs main's copy (``install``). Launchers from before
this file took over reach it through ``pull`` (#532), the ``client_config.py refresh`` hook
(#529) and ``sdpm._launcher_bridge`` (#397), which all end in ``adopt``.

Stage 1 (``update`` / ``install`` / ``adopt`` / ``pull``) is the code the install already
has. It selects the target (the newest release tag, or ``origin/main`` on the main
channel; never a commit that does not contain the user's), sets local changes aside in a
named git stash, and checks the target out (detached). Stage 2 (``finish``) is the
target's own code, read from the tree just checked out: it prepares the Python
environment and the Web UI, records ``state.json``, replaces the launcher, refreshes the
clients and prints the upgrading notes. When preparing fails, stage 1 goes back to the
previous commit and re-syncs its environment.

Contracts other versions rely on (do not change them): the file path, the
``UPDATER_CONTRACT`` line, the subcommand argv, the ``update-prepared`` sentinel, the
``update-backup/`` layout and the ``adopt-from`` file. Standard library only, one file,
Python 3.8+: launchers copy just this file into a temp dir and run it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

UPDATER_CONTRACT = 1

# Below this no release has `finish`, so nothing below it can be a target.
RELEASE_FLOOR = (0, 13, 0)
FIRST_RELEASE = "v0.13.0"
# Every launcher this project shipped carries the fingerprint; the bootstrap also carries
# the marker and its version ("sdpm-bootstrap 1").
LAUNCHER_FINGERPRINT = "the one launcher for a local SDPM installation"
BOOTSTRAP_MARKER = "sdpm-bootstrap"
REPO = "https://github.com/aws-samples/sample-spec-driven-presentation-maker"
RELEASE_BASE_URL = REPO + "/releases/download"
# The Troubleshooting entry that covers a stopped update.
HELP = REPO + "/blob/main/docs/en/getting-started.md#sdpm-update-stops"
INSTALL_HELP = REPO + "/blob/main/docs/en/getting-started.md#install"

# The interpreter line for every new stage 1 start: no project, a fresh ephemeral
# environment (never a .venv or VIRTUAL_ENV), Python 3.11+ whatever .python-version says.
PY_ARGS = ["run", "--no-project", "--isolated", "--python", ">=3.11", "python"]
# Local tags mirror origin (+ and --prune): a moved tag is followed, a deleted one is gone.
FETCH_ARGS = ["fetch", "--quiet", "--prune", "origin",
              "+refs/heads/main:refs/remotes/origin/main", "+refs/tags/*:refs/tags/*"]
ORIGIN_MAIN = "refs/remotes/origin/main"

STABLE_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
COMMIT = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
AGENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CONTRACT_LINE = re.compile(r"^UPDATER_CONTRACT = (\d+)$", re.MULTILINE)
CHANNELS = ("release", "main")
PROFILES = ("full", "mcp")
DEFAULT_AGENT = "sdpm"
UPDATER_PATH = "servers/local/checkout_update.py"

# finish option -> the first UPDATER_CONTRACT that accepts it. Adding an option bumps the
# contract; an option is never removed or given a new meaning.
FINISH_OPTIONS = {
    "--entry": 1, "--previous": 1, "--since": 1, "--launcher": 1, "--profile": 1,
    "--agent-name": 1, "--channel": 1, "--register": 1, "--non-interactive": 1, "--prepared": 1,
}

# The stash is a commit; git refuses to make one without an identity, which a machine that
# only ever ran the installer may not have.
_IDENTITY = ["-c", "user.name=sdpm update", "-c", "user.email=sdpm-update@localhost"]
_UTF8_BOM = b"\xef\xbb\xbf"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class Stop(Exception):
    """Stop stage 1 with this exit code; the message (if any) is already printed or given."""

    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def out(message: str = "") -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------


def child_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The parent environment without VIRTUAL_ENV (``uv run --isolated`` exports its own)."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    if extra:
        env.update(extra)
    return env


def py_argv(uv: str, script: str, *args: str) -> List[str]:
    return [uv, *PY_ARGS, script, *args]


def tty_allowed(non_interactive: bool = False) -> bool:
    """The one rule for asking anything: stdout is a terminal and a terminal can be read.

    Under ``curl | bash`` stdin is the script, so stdin says nothing; an agent captures
    stdout. /dev/tty is opened, not tested: a runner without a controlling terminal has the
    node but cannot open it.
    """
    if non_interactive:
        return False
    try:
        if not sys.stdout.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if sys.platform == "win32":
        try:
            return sys.stdin.isatty()
        except (AttributeError, ValueError):
            return False
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return False
    os.close(fd)
    return True


_WINDOWS_CTRL_C = 0xC000013A


def run_child(argv: Sequence[str], *, env: Optional[Dict[str, str]] = None,
              cwd: Optional[str] = None) -> Tuple[int, bool]:
    """Run a child and survive Ctrl+C meant for it; ``(returncode, interrupted)``.

    SIGINT reaches the whole foreground process group, so this process gets it too and must
    stay alive to roll back. The handler is installed after the child started (a Python
    handler is not inherited, SIG_IGN would be).
    """
    seen = [False]
    try:
        proc = subprocess.Popen(list(argv), env=env, cwd=cwd)  # nosec B603 - fixed argv
    except OSError as error:
        warn(f"Could not start {argv[0]}: {error.strerror or error}")
        return 127, False
    previous = None
    if os.name != "nt":
        def _record(_signum, _frame) -> None:
            seen[0] = True

        previous = signal.signal(signal.SIGINT, _record)
    try:
        while True:
            try:
                rc = proc.wait()
                break
            except KeyboardInterrupt:
                seen[0] = True
    finally:
        if previous is not None:
            signal.signal(signal.SIGINT, previous)
    if rc in (130, -signal.SIGINT, _WINDOWS_CTRL_C):
        seen[0] = True
    return rc, seen[0]


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


class GitError(Exception):
    pass


def _git(checkout: str, *args: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(  # nosec B603 B607 - fixed git commands on the local checkout
        ["git", "-C", str(checkout), *args],
        capture_output=capture, text=True, encoding="utf-8", errors="replace", check=False,
    )


def rev(checkout: str, ref: str) -> Optional[str]:
    """The commit ``ref`` names, or None."""
    res = _git(checkout, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    sha = res.stdout.strip()
    return sha if res.returncode == 0 and COMMIT.match(sha) else None


def head(checkout: str) -> str:
    sha = rev(checkout, "HEAD")
    if sha is None:
        raise GitError(f"git could not read HEAD in {checkout}")
    return sha


def on_main_branch(checkout: str) -> bool:
    res = _git(checkout, "symbolic-ref", "--quiet", "HEAD")
    return res.returncode == 0 and res.stdout.strip() == "refs/heads/main"


def is_ancestor(checkout: str, a: str, b: str) -> bool:
    """``a`` is contained in ``b``. Any git answer other than yes/no is fatal."""
    res = _git(checkout, "merge-base", "--is-ancestor", a, b)
    if res.returncode == 0:
        return True
    if res.returncode == 1:
        return False
    raise GitError(f"git could not compare {a[:7]} with {b[:7]}: {res.stderr.strip()}")


def short(sha: str) -> str:
    return sha[:7]


def describe(checkout: str, sha: str) -> str:
    res = _git(checkout, "describe", "--tags", "--match", "v[0-9]*", "--exclude", "*-*", "--abbrev=7", sha)
    text = res.stdout.strip()
    return text if res.returncode == 0 and text else short(sha)


def labelled(checkout: str, sha: str) -> str:
    """``v0.13.0 (1a2b3c4)``; just the SHA when no tag is below it."""
    name = describe(checkout, sha)
    return name if name == short(sha) else f"{name} ({short(sha)})"


def fetch(checkout: str) -> subprocess.CompletedProcess:
    return _git(checkout, *FETCH_ARGS)


def refresh_tags(checkout: str) -> None:
    """The bootstrap's fetch, for the entries an old launcher starts (its fetch neither
    force-updates nor prunes tags). A failure leaves the local refs."""
    res = fetch(checkout)
    if res.returncode != 0:
        reason = (res.stderr.strip().splitlines() or ["git fetch failed"])[-1]
        warn(f"(could not refresh tags: {reason}; using the local ones)")


def local_changes(checkout: str) -> List[str]:
    """``git status --porcelain`` lines of the tracked files that differ from HEAD."""
    res = _git(checkout, "status", "--porcelain", "--untracked-files=no")
    return [line for line in res.stdout.splitlines() if line.strip()]


def set_aside(checkout: str) -> Optional[str]:
    """Stash the tracked changes under a name that says where they came from; the stash commit."""
    at = _git(checkout, "rev-parse", "--short", "HEAD").stdout.strip() or "unknown"
    message = f"sdpm update {time.strftime('%Y-%m-%d %H:%M')} (local changes on {at})"
    if _git(checkout, *_IDENTITY, "stash", "push", "--quiet", "-m", message, capture=False).returncode != 0:
        return None
    return _git(checkout, "rev-parse", "--verify", "-q", "refs/stash").stdout.strip() or None


def _quote(path: str) -> str:
    return f'"{path}"'


def stash_line(checkout: str, stash: str) -> str:
    return f"  Your local changes are in stash {stash}: git -C {_quote(checkout)} stash apply {stash}"


def contract_of(checkout: str, sha: str) -> Optional[int]:
    """The UPDATER_CONTRACT of ``sha``'s checkout_update.py, None when it has none."""
    res = _git(checkout, "show", f"{sha}:{UPDATER_PATH}")
    if res.returncode != 0:
        return None
    match = CONTRACT_LINE.search(res.stdout)
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Release tags
# ---------------------------------------------------------------------------


def parse_version(name: str) -> Optional[Tuple[int, int, int]]:
    match = STABLE_TAG.match(name)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def stable_tags(checkout: str) -> List[Tuple[Tuple[int, int, int], str]]:
    """Local stable tags (``vX.Y.Z``), highest first. Local refs only: no network."""
    res = _git(checkout, "for-each-ref", "--format=%(refname:strip=2)", "refs/tags/v*")
    if res.returncode != 0:
        raise GitError(f"git could not list the tags: {res.stderr.strip()}")
    found = []
    for name in res.stdout.split():
        version = parse_version(name)
        if version is not None:
            found.append((version, name))
    return sorted(found, reverse=True)


class Release:
    def __init__(self, name: str, sha: str, version: Tuple[int, int, int]) -> None:
        self.name, self.sha, self.version = name, sha, version

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Release({self.name}, {self.sha[:7]})"


def origin_main(checkout: str) -> str:
    sha = rev(checkout, ORIGIN_MAIN)
    if sha is None:
        raise GitError(f"git could not find {ORIGIN_MAIN} in {checkout}")
    return sha


def latest_release(checkout: str, exclude: Sequence[str] = ()) -> Optional[Release]:
    """The highest stable tag ≥ the floor whose commit is on origin/main (``E``).

    A tag cut from a branch never reaches a user: later releases would not contain it.
    """
    main = origin_main(checkout)
    for version, name in stable_tags(checkout):
        if version < RELEASE_FLOOR or name in exclude:
            continue
        sha = rev(checkout, "refs/tags/" + name)
        if sha is None:
            continue
        if is_ancestor(checkout, sha, main):
            return Release(name, sha, version)
    return None


def tag_at(checkout: str, sha: str) -> Optional[str]:
    """The highest stable tag that points at ``sha``."""
    res = _git(checkout, "tag", "--points-at", sha)
    tags = [(parse_version(n), n) for n in res.stdout.split() if parse_version(n)]
    return max(tags)[1] if tags else None


# ---------------------------------------------------------------------------
# Target selection (the only code that computes targets)
# ---------------------------------------------------------------------------


class Selection:
    """``target`` and why: release | main | stay-release | stay-main."""

    def __init__(self, target: str, kind: str) -> None:
        self.target, self.kind = target, kind

    @property
    def stays(self) -> bool:
        return self.kind.startswith("stay")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Selection({self.target[:7]}, {self.kind})"


class CannotFinish(Exception):
    pass


def select(channel: str, base: Optional[str], current: str, latest: Optional[str], main: str,
           contains: Callable[[str, str], bool], can_finish: Callable[[str], bool], entry: str) -> Selection:
    """Pure: every target contains ``base`` (None: a new install, which contains nothing)."""

    def has(sha: str) -> bool:
        return base is None or contains(base, sha)

    if channel == "release":
        if latest is not None and has(latest):
            chosen = Selection(latest, "release")
        elif base is None:
            chosen = Selection(main, "main")  # no release can be installed yet
        else:
            chosen = Selection(current, "stay-release")
    elif has(main):
        chosen = Selection(main, "main")
    else:
        chosen = Selection(current, "stay-main")
    if chosen.stays and entry in ("install", "update") and not can_finish(current):
        # A tree that cannot finish has nowhere to stay.
        if has(main):
            return Selection(main, "main")
        raise CannotFinish(current)
    return chosen


def resolve_channel(option: Optional[str], environ: Dict[str, str], state: dict) -> str:
    """Option, then SDPM_CHANNEL, then the recorded channel, then release."""
    if option is not None:
        if option not in CHANNELS:
            raise Stop(2, f"--channel must be release or main, not {option!r}.")
        return option
    env = environ.get("SDPM_CHANNEL")
    if env:
        if env not in CHANNELS:
            raise Stop(2, f"SDPM_CHANNEL must be release or main, not {env!r}.")
        return env
    recorded = state.get("channel")
    return recorded if recorded in CHANNELS else "release"


# ---------------------------------------------------------------------------
# State: ~/.sdpm/state.json
# ---------------------------------------------------------------------------

STATE_FILE = "state.json"


def valid_agent_name(name: object) -> bool:
    return isinstance(name, str) and bool(AGENT_NAME.match(name))


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + "-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_state(home: Path, *, warnings: bool = True) -> dict:
    """The recorded state, field by field; migrated from .profile / .agent-name when the
    file is missing. ``present`` says whether state.json was read."""

    def note(message: str) -> None:
        if warnings:
            warn(f"(state.json: {message})")

    path = home / STATE_FILE
    raw: dict = {}
    present = False
    if path.is_file():
        text = _read_text(path)
        try:
            loaded = json.loads(text) if text is not None else None
        except ValueError:
            loaded = None
        if isinstance(loaded, dict):
            raw, present = loaded, True
        else:
            note(f"{path} is not valid JSON; using the defaults")
    legacy_profile = _read_text(home / ".profile")
    legacy_agent = _read_text(home / ".agent-name")
    state = {"present": present, "raw": raw, "clients": [], "commit": None, "tag": None}
    if present:
        channel = raw.get("channel")
        if channel not in CHANNELS:
            note(f"channel {channel!r} is not release or main; using release")
            channel = "release"
        profile = raw.get("profile")
        if profile not in PROFILES:
            note(f"profile {profile!r} is not full or mcp; using full")
            profile = "full"
        agent = raw.get("agent_name")
        if not valid_agent_name(agent):
            note(f"agent_name {agent!r} is not a valid name; using {DEFAULT_AGENT}")
            agent = DEFAULT_AGENT
        version = raw.get("version") if isinstance(raw.get("version"), dict) else {}
        commit = version.get("commit")
        state["commit"] = commit if isinstance(commit, str) and COMMIT.match(commit) else None
        tag = version.get("tag")
        state["tag"] = tag if isinstance(tag, str) and parse_version(tag) else None
        clients = raw.get("clients")
        state["clients"] = [c for c in clients if isinstance(c, str)] if isinstance(clients, list) else []
    else:
        channel = "release"
        profile = legacy_profile if legacy_profile in PROFILES else "full"
        if legacy_agent and valid_agent_name(legacy_agent):
            agent = legacy_agent
        else:
            if legacy_agent:
                note(f".agent-name {legacy_agent!r} is not a valid name; using {DEFAULT_AGENT}")
            agent = DEFAULT_AGENT
    # An old launcher can write .profile after state.json was written; it only ever writes full.
    if legacy_profile == "full" and profile == "mcp":
        profile = "full"
    state.update(channel=channel, profile=profile, agent_name=agent)
    return state


def write_state(home: Path, **fields: object) -> None:
    """Rewrite state.json with ``fields``; keys this version does not know are kept."""
    path = home / STATE_FILE
    raw: dict = {}
    text = _read_text(path) if path.is_file() else None
    if text:
        try:
            loaded = json.loads(text)
            raw = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            raw = {}
    raw["schema"] = 1
    for key in ("channel", "profile", "agent_name"):
        if key in fields:
            raw[key] = fields[key]
    if "commit" in fields:
        raw["version"] = {"tag": fields.get("tag"), "commit": fields["commit"]}
    if "clients" in fields:
        raw["clients"] = list(fields["clients"])  # type: ignore[arg-type]
    raw["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_atomic(path, json.dumps(raw, indent=2) + "\n")


def record_clients(home: Path, record: Path) -> None:
    """Fold a ``client_config.py --record`` file into state.json's ``clients``."""
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict) or not (home / STATE_FILE).is_file():
        return

    def ids(key: str) -> List[str]:
        value = data.get(key)
        return [c for c in value if isinstance(c, str)] if isinstance(value, list) else []

    current = load_state(home, warnings=False)["clients"]
    gone = set(ids("unregistered"))
    clients = sorted((set(current) | set(ids("here")) | set(ids("registered"))) - gone)
    write_state(home, clients=clients)


def is_fresh(home: Path) -> bool:
    """No finish and no installer ever recorded a choice here."""
    return not any((home / name).exists() for name in (STATE_FILE, ".profile", ".uv-path"))


def read_commit_file(path: Path) -> Optional[str]:
    text = _read_text(path)
    return text if text and COMMIT.match(text) else None


def sdpm_home() -> Path:
    """$SDPM_HOME, else ~/.sdpm (the launchers' rule)."""
    env = os.environ.get("SDPM_HOME")
    return Path(env).expanduser() if env else Path.home() / ".sdpm"


def same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))


# ---------------------------------------------------------------------------
# The launcher
# ---------------------------------------------------------------------------


def launcher_source(checkout: Path, installed: Path) -> Path:
    ps1 = installed.suffix.lower() == ".ps1"
    return checkout / "scripts" / "install" / ("launcher.ps1" if ps1 else "launcher.sh")


def bootstrap_version(path: Path) -> int:
    """The ``sdpm-bootstrap <n>`` of an installed launcher; 0 for an older one or none."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    match = re.search(BOOTSTRAP_MARKER + r" (\d+)", text)
    return int(match.group(1)) if match else 0


def refresh_launcher(installed: Path, checkout: Path) -> str:
    """Replace the installed ``sdpm`` command with the checkout's launcher; say what happened.

    The new file is written next to the old one and renamed over it. A running bash keeps
    reading the old file (its open inode), so the ``sdpm update`` that calls this is not
    corrupted. Only a launcher we installed is replaced: a link (a developer pointing
    ``sdpm`` at a working tree) or a foreign file is left alone.
    """
    installed, checkout = Path(installed), Path(checkout)
    ps1 = installed.suffix.lower() == ".ps1"
    source = launcher_source(checkout, installed)
    if installed.is_symlink():
        return f"left alone ({installed} is a link)"
    try:
        current = installed.read_bytes()
        new = source.read_bytes()
    except OSError as error:
        return f"not refreshed ({error.strerror or error})"
    if LAUNCHER_FINGERPRINT.encode() not in current:
        return f"left alone ({installed} is not an SDPM launcher)"
    if ps1 and not new.startswith(_UTF8_BOM):
        new = _UTF8_BOM + new  # Windows PowerShell 5.1 reads a file without a BOM as ANSI
    if current == new:
        return "up to date"
    fd, tmp = tempfile.mkstemp(prefix=".sdpm-", dir=str(installed.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(new)
        os.chmod(tmp, stat.S_IMODE(installed.stat().st_mode))
        os.replace(tmp, str(installed))
    except OSError as error:
        Path(tmp).unlink(missing_ok=True)
        return f"not refreshed ({error.strerror or error}); the next `sdpm update` retries"
    return "updated"


def write_launcher(installed: Path, checkout: Path) -> str:
    """Write the launcher where there is none (a first install, or one the user deleted)."""
    installed = Path(installed)
    new = launcher_source(Path(checkout), installed).read_bytes()
    if installed.suffix.lower() == ".ps1" and not new.startswith(_UTF8_BOM):
        new = _UTF8_BOM + new
    installed.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".sdpm-", dir=str(installed.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(new)
        # The sdpm command in the user's own bin directory: rwx for the owner, r-x for the rest, as chmod +x.
        os.chmod(tmp, 0o755)  # nosec B103 # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        os.replace(tmp, str(installed))
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise
    return "installed"


def would_leave_alone(installed: Path) -> bool:
    installed = Path(installed)
    if installed.is_symlink():
        return True
    if not installed.exists():
        return False
    try:
        return LAUNCHER_FINGERPRINT.encode() not in installed.read_bytes()
    except OSError:
        return True


# ---------------------------------------------------------------------------
# Release manifests (R11)
# ---------------------------------------------------------------------------

MANIFEST_MAX_BYTES = 64 * 1024
MANIFEST_TOOLS = ("git", "uv", "node", "python")
_MIN_VERSION = re.compile(r"^\d+(\.\d+){0,3}$")


def manifest_os() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"


def manifest_name(os_name: str, use: str) -> str:
    return f"release-{os_name}-{use}.json"


def release_base_url(environ: Dict[str, str]) -> str:
    override = environ.get("SDPM_RELEASE_BASE_URL")
    if override:
        if override.startswith(("https://", "file://")):
            return override.rstrip("/")
        warn("(SDPM_RELEASE_BASE_URL must start with https:// or file://; using the release URL)")
    return RELEASE_BASE_URL


def clean_text(value: str) -> str:
    """Remote text without control characters (no terminal escapes)."""
    return _CONTROL.sub("", value)


def parse_manifest(data: object, *, tag: str, os_name: str, use: str) -> dict:
    """A validated schema-1 manifest; ValueError names the first violation."""

    def need(condition: bool, what: str) -> None:
        if not condition:
            raise ValueError(what)

    need(isinstance(data, dict), "not an object")
    assert isinstance(data, dict)
    schema = data.get("schema")
    need(isinstance(schema, int) and not isinstance(schema, bool) and schema >= 1, "schema")
    version = data.get("version")
    need(isinstance(version, str) and parse_version("v" + version) is not None, "version")
    need(data.get("tag") == tag and version == tag[1:], "tag")
    commit = data.get("commit")
    need(isinstance(commit, str) and bool(COMMIT.match(commit)), "commit")
    need(data.get("os") == os_name, "os")
    need(data.get("use") == use, "use")
    min_launcher = data.get("min_launcher", 0)
    need(isinstance(min_launcher, int) and not isinstance(min_launcher, bool) and 0 <= min_launcher <= 1000,
         "min_launcher")
    requires = data.get("requires", [])
    need(isinstance(requires, list) and len(requires) <= 20, "requires")
    parsed_requires = []
    for item in requires:
        need(isinstance(item, dict), "requires item")
        name, minimum = item.get("name"), item.get("min")
        profiles = item.get("profiles", list(PROFILES))
        help_text = item.get("help", "")
        need(isinstance(name, str) and 0 < len(name) <= 40, "requires name")
        need(isinstance(minimum, str) and bool(_MIN_VERSION.match(minimum)), "requires min")
        need(isinstance(profiles, list) and all(p in PROFILES for p in profiles), "requires profiles")
        need(isinstance(help_text, str) and len(help_text) <= 300, "requires help")
        parsed_requires.append({"name": clean_text(name), "min": minimum, "profiles": list(profiles),
                                "help": clean_text(help_text)})
    notes = data.get("notes", [])
    need(isinstance(notes, list) and len(notes) <= 20, "notes")
    need(all(isinstance(n, str) and len(n) <= 500 for n in notes), "notes item")
    return {"schema": schema, "version": version, "tag": tag, "commit": commit, "os": os_name, "use": use,
            "min_launcher": min_launcher, "requires": parsed_requires, "notes": [clean_text(n) for n in notes]}


def fetch_manifest(tag: str, use: str, *, base: str, os_name: Optional[str] = None,
                   timeout: float = 5.0) -> Tuple[str, Optional[dict], str]:
    """``("ok", manifest, "")``, ``("absent", None, "")`` (404 or a missing file) or
    ``("error", None, reason)``. Never raises: the manifest never fails an install."""
    os_name = os_name or manifest_os()
    url = f"{base}/{tag}/{manifest_name(os_name, use)}"
    request = urllib.request.Request(url, headers={"User-Agent": "sdpm"})
    try:
        # base is the release URL or an SDPM_RELEASE_BASE_URL checked for https:// or file:// (release_base_url).
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            body = response.read(MANIFEST_MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return "absent", None, ""
        return "error", None, f"HTTP {error.code}"
    except urllib.error.URLError as error:
        if isinstance(error.reason, FileNotFoundError):
            return "absent", None, ""
        return "error", None, str(error.reason)
    except FileNotFoundError:
        return "absent", None, ""
    except (OSError, ValueError) as error:
        return "error", None, str(error) or type(error).__name__
    if len(body) > MANIFEST_MAX_BYTES:
        return "error", None, "larger than 64 KiB"
    try:
        data = json.loads(body.decode("utf-8"))
        return "ok", parse_manifest(data, tag=tag, os_name=os_name, use=use), ""
    except (ValueError, UnicodeDecodeError) as error:
        return "error", None, f"invalid ({error})"


def _version_tuple(text: str) -> Tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)*)", text)
    return tuple(int(p) for p in match.group(1).split(".")) if match else ()


def _pad(v: Tuple[int, ...]) -> Tuple[int, ...]:
    return v + (0,) * (4 - len(v))


def tool_version(name: str, uv: str) -> Optional[str]:
    exe = {"uv": uv}.get(name) or shutil.which(name)
    if not exe:
        return None
    try:
        res = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20, check=False)  # nosec B603
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (res.stdout or res.stderr).strip()
    found = _version_tuple(text)
    return ".".join(str(p) for p in found) if found else None


def unmet_requirement(manifest: dict, profile: str, uv: str) -> Optional[Tuple[dict, Optional[str]]]:
    """The first ``requires`` entry this machine does not meet. Python is listed for the
    record but uv provides it, so it never stops anything; unknown names are ignored."""
    for item in manifest["requires"]:
        if item["name"] not in ("git", "uv", "node") or profile not in item["profiles"]:
            continue
        found = tool_version(item["name"], uv)
        if found is None or _pad(_version_tuple(found)) < _pad(_version_tuple(item["min"])):
            return item, found
    return None


def print_manifest_notes(manifest: dict) -> None:
    if manifest.get("notes"):
        out(f"  {manifest['tag']} notes:")
        for note in manifest["notes"]:
            out(f"    - {note}")


# ---------------------------------------------------------------------------
# The Web UI backup (frozen layout) and the prepared sentinel
# ---------------------------------------------------------------------------

WEBUI_PARTS = ("node_modules", "build")
STAMP = ".sdpm-source"


def sentinel_path(home: Path) -> Path:
    return home / "update-prepared"


def backup_dir(home: Path) -> Path:
    return home / "update-backup"


def stamp_path(checkout: Path) -> Path:
    return checkout / "web-ui" / "build" / STAMP


def read_stamp(checkout: Path) -> Optional[str]:
    return read_commit_file(stamp_path(checkout))


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(str(path))


def put_back(home: Path, checkout: Path) -> bool:
    """The previous node_modules / build back into web-ui/; False when a rename failed."""
    backup, webui = backup_dir(home), checkout / "web-ui"
    try:
        if (backup / "build").exists():
            stamp = stamp_path(checkout)
            if stamp.exists():
                stamp.unlink()
        for name in WEBUI_PARTS:
            saved = backup / name
            if saved.exists() or saved.is_symlink():
                _remove(webui / name)
                os.replace(str(saved), str(webui / name))
        complete = backup / ".complete"
        if complete.exists():
            complete.unlink()
        backup.rmdir()
    except OSError as error:
        warn(f"Web UI files could not be put back ({getattr(error, 'filename', None) or backup}); "
             f"run sdpm update again once {error.strerror or error}")
        return False
    return True


def recover_webui(home: Path, checkout: Path, expected: str) -> bool:
    """Apply the backup rule: keep a completed build of ``expected``, otherwise put the
    previous Web UI back. Runs at the start of every stage 1 and after every failed finish."""
    backup, webui = backup_dir(home), checkout / "web-ui"
    if not backup.is_dir():
        return True
    if not (backup / ".complete").exists():
        # The move aside was interrupted: rename back what has no counterpart.
        ok = True
        for name in WEBUI_PARTS:
            saved = backup / name
            if not saved.exists():
                continue
            if (webui / name).exists():
                warn(f"Web UI files could not be put back ({saved}); run sdpm update again once "
                     f"{webui / name} is moved away")
                ok = False
                continue
            try:
                os.replace(str(saved), str(webui / name))
            except OSError as error:
                warn(f"Web UI files could not be put back ({saved}); run sdpm update again once "
                     f"{error.strerror or error}")
                ok = False
        try:
            backup.rmdir()
        except OSError:
            pass
        return ok
    if read_stamp(checkout) == expected:
        shutil.rmtree(str(backup), ignore_errors=True)
        return True
    return put_back(home, checkout)


# ---------------------------------------------------------------------------
# Stage 2: finish (the target's code) and prepare
# ---------------------------------------------------------------------------


def prepare_python(checkout: str, uv: str) -> int:
    """``uv sync --frozen`` for the MCP server (a module-level function: tests rebind it)."""
    out("> Syncing the MCP server environment...")
    argv = [uv, "sync", "--frozen", "--directory", str(Path(checkout) / "servers" / "local")]
    try:
        return subprocess.call(argv, env=child_env())  # nosec B603 - fixed argv
    except OSError as error:
        warn(f"Could not run uv: {error.strerror or error}")
        return 127


def prepare_icons(checkout: Path, uv: str) -> None:
    sets = (("AWS Architecture", "aws", "download_aws_icons.py"),
            ("Material Symbols", "material", "download_material_icons.py"))
    for label, folder, script in sets:
        if (checkout / "sdpm" / "assets" / folder / "manifest.json").is_file():
            continue
        out(f"> Downloading the {label} icons...")
        argv = [uv, "run", "--frozen", "--directory", str(checkout / "servers" / "local"), "python",
                str(checkout / "sdpm" / "scripts" / script)]
        try:
            rc = subprocess.call(argv, env=child_env())  # nosec B603 - fixed argv
        except OSError:
            rc = 127
        if rc != 0:
            warn(f"  The {label} icons were not downloaded; they install on first use.")


def prepare_webui(checkout: Path, home: Path, commit: str) -> Tuple[int, bool]:
    """Build the Web UI unless its stamp names ``commit``; ``(rc, moved_aside)``.

    The previous build is renamed aside to the frozen backup layout first and put back on
    any failure, so the Web UI that worked before is never lost.
    """
    if read_stamp(checkout) == commit:
        out(f"> Web UI: up to date (built from {short(commit)})")
        return 0, False
    npm = shutil.which("npm")
    if npm is None:
        warn("Node.js 20+ is required for the Web UI: https://nodejs.org/")
        return 3, False
    backup, webui = backup_dir(home), checkout / "web-ui"
    backup.mkdir()
    moved: List[str] = []
    for name in WEBUI_PARTS:
        if not (webui / name).exists():
            continue
        try:
            os.replace(str(webui / name), str(backup / name))
            moved.append(name)
        except OSError as error:
            for done in moved:
                try:
                    os.replace(str(backup / done), str(webui / done))
                except OSError:
                    pass
            try:
                backup.rmdir()
            except OSError:
                pass
            warn(f"Could not move {webui / name} aside ({error.strerror or error}). "
                 "Stop sdpm webui and run sdpm update again.")
            return 3, False
    write_atomic(backup / ".complete", "")
    try:
        out("> Installing Web UI dependencies...")
        rc = subprocess.call([npm, "ci"], cwd=str(webui), env=child_env())  # nosec B603 - fixed argv
        if rc == 0:
            out("> Building the Web UI (Local mode)...")
            rc = subprocess.call([npm, "run", "build"], cwd=str(webui),  # nosec B603 - fixed argv
                                 env=child_env({"NEXT_PUBLIC_MODE": "local"}))
    except KeyboardInterrupt:
        put_back(home, checkout)
        return 130, True
    except OSError as error:
        warn(f"Could not run npm: {error.strerror or error}")
        rc = 127
    if rc != 0 or not (webui / "build").is_dir():
        warn("The Web UI build failed (see above); the previous Web UI was put back.")
        put_back(home, checkout)
        return 3, True
    write_atomic(stamp_path(checkout), commit + "\n")
    return 0, True


def _client_argv(uv: str, checkout: Path, agent_name: str, *args: str) -> List[str]:
    return [uv, "run", "--frozen", "--directory", str(checkout / "servers" / "local"), "python",
            str(checkout / "servers" / "local" / "client_config.py"), "--uv", uv,
            "--checkout", str(checkout), "--agent-name", agent_name, *args]


NON_INTERACTIVE_LINE = ("  Non-interactive: clients were not registered. Later: sdpm register   "
                        "(or re-run with --register)")


def finish_clients(args: argparse.Namespace, checkout: Path, home: Path, fresh: bool) -> int:
    """Register (a fresh install) or refresh (everything else); the client CLI's rc."""
    out()
    if args.register == "no":
        out("  Skipping client registration (--no-register). Later: sdpm register")
        return 0
    if not fresh:
        call = ["refresh"]
        if args.since and COMMIT.match(args.since):
            call += ["--since", args.since]
        if args.register == "yes":
            call.append("--register-missing")
    elif args.entry != "install":
        out(NON_INTERACTIVE_LINE)  # sdpm update never prompts
        return 0
    elif args.register == "yes":
        call = ["register", "--yes"]
    elif tty_allowed(args.non_interactive):
        call = ["register"]
    else:
        out(NON_INTERACTIVE_LINE)
        return 0
    out("> Refreshing the MCP clients..." if call[0] == "refresh" else "> Registering the MCP clients...")
    fd, record = tempfile.mkstemp(prefix="sdpm-clients-", suffix=".json")
    os.close(fd)
    try:
        argv = _client_argv(args.uv, checkout, args.agent_name, *call, "--record", record)
        try:
            rc = subprocess.call(argv, env=child_env({"SDPM_UPDATER": "1"}))  # nosec B603 - fixed argv
        except OSError as error:
            warn(f"Could not run uv: {error.strerror or error}")
            rc = 127
        try:
            record_clients(home, Path(record))
        except OSError as error:
            warn(f"could not record the install state ({error.strerror or error})")
    finally:
        try:
            os.unlink(record)
        except OSError:
            pass
    return rc


def finish(args: argparse.Namespace) -> int:
    """Stage 2, run from the target's tree: prepare, sentinel, state, launcher, clients."""
    checkout = Path(args.checkout)
    home = checkout.parent
    fresh = is_fresh(home)
    try:
        commit = head(str(checkout))
    except GitError as error:
        warn(str(error))
        return 3
    if backup_dir(home).exists():
        warn(f"A previous Web UI backup is still at {backup_dir(home)}; run sdpm update again.")
        return 3
    moved_aside = False
    if args.prepared is None:
        if prepare_python(str(checkout), args.uv) != 0:
            warn("Could not sync the MCP server environment (see above). If an MCP client is "
                 "running SDPM, close it and run sdpm update again.")
            return 3
        if args.entry == "install":
            prepare_icons(checkout, args.uv)
        if args.profile == "full":
            rc, moved_aside = prepare_webui(checkout, home, commit)
            if rc != 0:
                return rc
    elif args.prepared == "all" and args.profile == "full" and (checkout / "web-ui" / "build").is_dir():
        # The old launcher built this tree in this run.
        write_atomic(stamp_path(checkout), commit + "\n")
    write_atomic(sentinel_path(home), commit + "\n")
    if moved_aside:
        try:
            shutil.rmtree(str(backup_dir(home)))
        except OSError as error:
            warn(f"(could not remove {backup_dir(home)}: {error.strerror or error}; the next update does)")

    failed = False
    # State. agent_name is recorded only by an install; update and adopt keep the recorded
    # (or migrated) name, so a one-off SDPM_AGENT_NAME never becomes it.
    previous_state = load_state(home, warnings=False)
    agent = args.agent_name if args.entry == "install" else previous_state["agent_name"]
    try:
        write_state(home, channel=args.channel, profile=args.profile, agent_name=agent,
                    commit=commit, tag=tag_at(str(checkout), commit), clients=previous_state["clients"])
        write_atomic(home / ".uv-path", args.uv + "\n")
        adopt_from = home / "adopt-from"
        if adopt_from.exists():
            adopt_from.unlink()
    except OSError as error:
        warn(f"could not record the install state ({error.strerror or error})")
        failed = True

    # The launcher.
    launcher = Path(args.launcher)
    foreign = False
    if launcher.exists() or launcher.is_symlink():
        result = refresh_launcher(launcher, checkout)
        out(f"  sdpm command: {result}")
        if args.entry == "install" and result.startswith("left alone") and "not an SDPM launcher" in result:
            foreign = True
    else:
        try:
            out(f"  sdpm command: {write_launcher(launcher, checkout)} ({launcher})")
        except OSError as error:
            warn(f"  sdpm command: not written ({error.strerror or error})")
            failed = True

    if finish_clients(args, checkout, home, fresh) != 0:
        failed = True

    # The files state.json replaces go once the bootstrap is in place; adopt keeps them, the
    # old launcher that started it reads them after it returns.
    if args.entry in ("install", "update") and bootstrap_version(launcher) > 0:
        for name in (".profile", ".agent-name"):
            try:
                (home / name).unlink()
            except FileNotFoundError:
                pass
            except OSError as error:
                warn(f"(could not remove {home / name}: {error.strerror or error})")
    if foreign:
        warn(f"{launcher} exists and is not an SDPM launcher; it was left alone. "
             "Move it aside and run the installer again.")
    return 1 if failed or foreign else 0


def prepare_command(args: argparse.Namespace) -> int:
    return prepare_python(args.checkout, args.uv)


# ---------------------------------------------------------------------------
# Stage 1
# ---------------------------------------------------------------------------


class Run:
    """What one stage 1 run knows: where, which uv, the home, HEAD before anything moved."""

    def __init__(self, checkout: str, uv: Optional[str]) -> None:
        self.checkout = str(checkout)
        self.uv = uv or ""
        self.home = Path(checkout).parent


def _move_to(run: Run, target: str) -> Optional[str]:
    """Set local changes aside, check out ``target`` detached; the stash or "" (Stop on failure)."""
    stash = ""
    changes = local_changes(run.checkout)
    if changes:
        made = set_aside(run.checkout)
        if made is None:
            warn(f"Could not move the local changes in {run.checkout} to a git stash; nothing was changed.")
            warn(f"  See {HELP}.")
            raise Stop(1)
        stash = made
        out(f"  Local changes in {run.checkout} were set aside (git stash) so the update can move on:")
        for line in changes:
            out(f"    {line}")
        out("  If you did not edit these files, an earlier version's tools wrote them: nothing to do.")
        out(f"  To bring them back: git -C {_quote(run.checkout)} stash apply {stash}")
    res = _git(run.checkout, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", target,
               capture=False)
    if res.returncode != 0:
        warn(f"sdpm update could not check out {short(target)} in {run.checkout} (git's message above). "
             "Nothing was discarded.")
        if stash:
            warn(stash_line(run.checkout, stash))
        warn(f"  See {HELP}.")
        raise Stop(1)
    return stash


def _finish_argv(run: Run, script: Path, contract: int, options: List[Tuple[str, Optional[str], bool]],
                 label: str) -> List[str]:
    """finish's argv with only what the target's contract accepts; Stop when the user asked
    for something it cannot do."""
    argv = py_argv(run.uv, str(script), "--checkout", run.checkout, "--uv", run.uv, "finish")
    for option, value, requested in options:
        if FINISH_OPTIONS.get(option, UPDATER_CONTRACT + 1) > contract:
            if requested:
                warn(f"{label} does not support {option}; use --channel main or wait for the next "
                     "release. Nothing was changed.")
                raise Stop(1)
            continue
        argv.append(option)
        if value is not None:
            argv.append(value)
    return argv


def _rollback(run: Run, previous: str, was_main: bool, target: str, interrupted: bool) -> int:
    checkout = run.checkout
    target_label = labelled(checkout, target)
    recover_webui(run.home, Path(checkout), previous)
    step = "check out the previous commit"
    try:
        stash = ""
        if local_changes(checkout):
            stash = set_aside(checkout) or ""
        res = _git(checkout, "checkout", "--quiet", "main", capture=False) if was_main else \
            _git(checkout, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", previous,
                 capture=False)
        if res.returncode != 0 or rev(checkout, "HEAD") != previous:
            raise GitError("checkout")
        step = "prepare the previous environment"
        if contract_of(checkout, previous) is not None:
            argv = py_argv(run.uv, str(Path(checkout) / UPDATER_PATH), "--checkout", checkout, "--uv", run.uv,
                           "prepare", "--python")
        else:
            argv = [run.uv, "sync", "--frozen", "--directory", str(Path(checkout) / "servers" / "local")]
        rc, _ = run_child(argv, env=child_env(), cwd=str(run.home))
        if rc != 0:
            raise GitError("prepare")
    except GitError:
        at = labelled(checkout, rev(checkout, "HEAD") or target)
        warn(f"Could not prepare {target_label}, and the way back stopped: could not {step}. "
             f"The checkout is at {at}. Nothing was discarded.")
        warn(f"  The previous environment may need the network. Run the installer again: {INSTALL_HELP}")
        return 130 if interrupted else 1
    warn(f"Could not prepare {target_label} (see above). Back on {labelled(checkout, previous)}, as before.")
    if stash:
        warn(stash_line(checkout, stash))
    warn(f"  See {HELP}.")
    return 130 if interrupted else 1


def _base(run: Run, entry: str, state: dict, current: str, *, new_checkout: bool = False,
          from_sha: Optional[str] = None) -> Optional[str]:
    """The commit the user had (None: a new install)."""
    if entry == "install" and (new_checkout or is_fresh(run.home)):
        return None
    if entry == "adopt" and from_sha and COMMIT.match(from_sha) and rev(run.checkout, from_sha):
        return from_sha
    if not state["present"]:
        recorded = read_commit_file(run.home / "adopt-from")
        if recorded and rev(run.checkout, recorded):
            try:
                if is_ancestor(run.checkout, recorded, current):
                    return recorded
            except GitError:
                pass
    return current


def _since(state: dict, base: Optional[str]) -> str:
    if state["present"] and state["commit"]:
        return state["commit"]
    return base or ""


def _stay_line(run: Run, selection: Selection, latest: Optional[Release]) -> str:
    at = describe(run.checkout, selection.target)
    if selection.kind == "stay-main":
        return f"Staying on {at}: it has commits origin/main does not have."
    latest_part = f"latest: {latest.name}" if latest else f"the first is {FIRST_RELEASE}"
    return f"Staying on {at}: no release contains it yet ({latest_part}); sdpm update moves on once one does."


def _version_line(run: Run, entry: str, base: Optional[str], current: str, selection: Selection,
                  latest: Optional[Release], channel: str) -> str:
    target = selection.target
    if base is None:
        if channel == "release" and latest is None and selection.kind == "main":
            return (f"No release can be installed yet; installing main {short(target)}. "
                    "sdpm update moves to the first release that contains it.")
        return f"Installing {labelled(run.checkout, target)}."
    if selection.stays:
        if entry == "adopt" and base != current and selection.kind == "stay-release":
            return (f"This update moved to main {short(current)} (the previous sdpm command followed main). "
                    "From now on sdpm follows releases and stays here until a release contains it.")
        return _stay_line(run, selection, latest)
    if base == target:
        return f"Up to date: {labelled(run.checkout, target)}."
    return f"Updating {describe(run.checkout, base)} → {labelled(run.checkout, target)}."


def stage1(run: Run, entry: str, *, channel_option: Optional[str] = None, with_webui: bool = False,
           profile_option: Optional[str] = None, agent_option: Optional[str] = None,
           register: str = "default", non_interactive: bool = False, new_checkout: bool = False,
           launcher: Optional[str] = None, from_sha: Optional[str] = None,
           prepared: Optional[str] = None) -> int:
    checkout = run.checkout
    home = run.home
    current = head(checkout)
    recover_webui(home, Path(checkout), current)
    state = load_state(home)
    environ = dict(os.environ)
    channel = resolve_channel(channel_option, environ, state)

    if entry == "adopt":
        if from_sha and COMMIT.match(from_sha):
            try:
                write_atomic(home / "adopt-from", from_sha + "\n")
            except OSError as error:
                warn(f"(could not record {home / 'adopt-from'}: {error.strerror or error})")
        if launcher:
            out(f"  sdpm command: {refresh_launcher(Path(launcher), Path(checkout))}")
    if entry in ("adopt", "pull"):
        refresh_tags(checkout)

    base = _base(run, entry, state, current, new_checkout=new_checkout, from_sha=from_sha)
    since = from_sha if entry == "adopt" and from_sha and COMMIT.match(from_sha) else _since(state, base)
    if entry == "install":
        profile = profile_option or "full"
        if agent_option is not None:
            agent = agent_option
        else:
            agent = state["agent_name"]
    else:
        profile = "full" if with_webui else state["profile"]
        env_agent = environ.get("SDPM_AGENT_NAME")
        if env_agent and valid_agent_name(env_agent):
            agent = env_agent
        else:
            if env_agent:
                warn(f"(SDPM_AGENT_NAME {env_agent!r} is not a valid name; using {state['agent_name']})")
            agent = state["agent_name"]

    # The target.
    main = origin_main(checkout)
    latest = latest_release(checkout) if channel == "release" else None
    manifest = None
    if latest is not None and entry != "pull":
        use = "install" if entry == "install" and new_checkout else "update"
        status, manifest, reason = fetch_manifest(latest.name, use, base=release_base_url(environ))
        if status == "error":
            warn(f"(release manifest not available: {reason}; using git tags)")
        if manifest is not None and manifest["commit"] != latest.sha:
            warn(f"The release manifest of {latest.name} names {short(manifest['commit'])}, the tag points at "
                 f"{short(latest.sha)}; skipping {latest.name}.")
            print_manifest_notes(manifest)
            latest = latest_release(checkout, exclude=[latest.name])
            manifest = None

    def contains(a: str, b: str) -> bool:
        return is_ancestor(checkout, a, b)

    try:
        selection = select(channel, base, current, latest.sha if latest else None, main, contains,
                           lambda sha: contract_of(checkout, sha) is not None, entry)
    except CannotFinish:
        warn(f"{describe(checkout, current)} has commits origin/main does not have and cannot update itself; "
             f"nothing was changed. See {HELP}.")
        return 1
    target = selection.target

    if channel == "main" and state["channel"] != "main":
        out("Following main: every merged change reaches this install. sdpm update --channel release goes "
            "back (it stays here until a release contains it).")

    if entry == "pull":
        # The #532 launcher prepares and refreshes by itself; adopt (in its refresh) prints the
        # version line, unless this tree predates the hook.
        if selection.stays and contract_of(checkout, current) is None:
            out(_stay_line(run, selection, latest))
        if target != current:
            _move_to(run, target)
        return 0

    out(_version_line(run, entry, base, current, selection, latest, channel))

    # Before anything moves: what the target asks of this machine.
    if manifest is not None and latest is not None and target == latest.sha and \
            (target != current or entry == "install"):
        unmet = unmet_requirement(manifest, profile, run.uv)
        if unmet is not None:
            item, found = unmet
            warn(f"{latest.name} needs {item['name']} {item['min']}+ (found {found or 'none'}): {item['help']}. "
                 "Nothing was changed.")
            print_manifest_notes(manifest)
            return 1
        if launcher and bootstrap_version(Path(launcher)) < manifest["min_launcher"] and \
                would_leave_alone(Path(launcher)):
            warn(f"{latest.name} needs a newer sdpm command than {launcher}; re-run the installer.")
            print_manifest_notes(manifest)
            return 1
    if profile == "full" and prepared is None and shutil.which("npm") is None:
        warn("Node.js 20+ is required for the Web UI: https://nodejs.org/")
        return 1

    target_label = latest.name if latest is not None and target == latest.sha else short(target)
    contract = contract_of(checkout, target)
    if contract is None:
        warn(f"{target_label} cannot be installed by sdpm update. Nothing was changed.")
        return 1
    options: List[Tuple[str, Optional[str], bool]] = [
        ("--entry", entry, False),
        ("--previous", current, False),
        ("--since", since, False),
        ("--launcher", launcher or "", False),
        ("--profile", profile, with_webui),
        ("--agent-name", agent, agent_option is not None),
        ("--channel", channel, channel_option is not None),
        ("--register", register, False),
    ]
    if non_interactive:
        options.append(("--non-interactive", None, False))
    if prepared is not None and target == current:
        options.append(("--prepared", prepared, False))
    script = Path(checkout) / UPDATER_PATH
    finish_argv = _finish_argv(run, script, contract, options, target_label)

    previous, was_main = current, on_main_branch(checkout)
    sentinel = sentinel_path(home)
    moved = target != current
    if moved:
        _move_to(run, target)
    try:
        if sentinel.exists():
            sentinel.unlink()
        rc, interrupted = run_child(finish_argv, env=child_env(), cwd=str(home))
        prepared_ok = read_commit_file(sentinel) == target
    finally:
        try:
            sentinel.unlink()
        except OSError:
            pass
    if rc == 0 and not interrupted:
        return 0
    if prepared_ok or not moved or base is None:
        recover_webui(home, Path(checkout), rev(checkout, "HEAD") or target)
        if interrupted:
            return 130
        if prepared_ok:
            return 4 if entry == "install" else 1
        if base is None:
            warn(f"Could not prepare {target_label} (see above). Run the installer again.")
        else:
            warn("The update did not finish (see above); nothing was moved.")
        return 1
    return _rollback(run, previous, was_main, target, interrupted)


def print_update_complete(home: Path) -> None:
    out("Update complete.")
    if load_state(home, warnings=False)["profile"] == "full":
        out("  sdpm webui     open the browser Web UI")
    else:
        out("  sdpm webui     (not installed — sdpm update --with-webui)")


PROBE_RETRY_DELAYS = (2.0, 5.0)


def _transient_manifest_error(reason: str) -> bool:
    """Whether a ``fetch_manifest`` error ``reason`` may pass on retry: a 5xx or a network
    error (a timeout, a reset). A 4xx, an invalid body or an oversized one is permanent."""
    match = re.match(r"HTTP (\d+)$", reason)
    if match:
        return int(match.group(1)) >= 500
    return not reason.startswith(("invalid (", "larger than "))


def manifest_probe(tag: str) -> int:
    """CI: fetch ``tag``'s update manifest from the real release URL; ok / absent / error.

    GitHub's release-asset host has slow spells (2026-11-08/09: 5 s read timeouts on every
    OS at once); the probe checks that the URL is right, not that GitHub is fast, so a
    transient error is retried with a longer timeout. ``sdpm update`` keeps its 5 s and
    no retry: there an error only falls back to git tags."""
    status, reason = "error", ""
    for delay in (*PROBE_RETRY_DELAYS, None):
        status, _manifest, reason = fetch_manifest(tag, "update", base=RELEASE_BASE_URL, timeout=15.0)
        if status != "error" or delay is None or not _transient_manifest_error(reason):
            break
        warn(f"(release manifest: {reason}; retrying in {delay:.0f} s)")
        time.sleep(delay)
    out(status if status != "error" else f"error: {reason}")
    return 1 if status == "error" else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="checkout_update.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--checkout", required=True, help="the installed checkout ($SDPM_HOME/checkout)")
    parser.add_argument("--uv", help="absolute path of uv")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("update", help="sdpm update: select, move, then the target's finish")
    p.add_argument("--launcher", required=True)
    p.add_argument("--channel", choices=CHANNELS)
    p.add_argument("--with-webui", action="store_true")

    p = sub.add_parser("install", help="the installer's hand-off")
    p.add_argument("--launcher", required=True)
    p.add_argument("--register", choices=("default", "yes", "no"), default="default")
    p.add_argument("--profile", choices=PROFILES, required=True)
    p.add_argument("--new-checkout", action="store_true")
    p.add_argument("--agent-name")
    p.add_argument("--channel", choices=CHANNELS)
    p.add_argument("--non-interactive", action="store_true")

    p = sub.add_parser("adopt", help="finish an update an old launcher started")
    p.add_argument("--launcher", required=True)
    p.add_argument("--from", dest="from_sha")
    p.add_argument("--prepared", choices=("all", "python"))

    p = sub.add_parser("finish", help="stage 2 (the target's code)")
    p.add_argument("--entry", choices=("install", "update", "adopt"), required=True)
    p.add_argument("--previous", default="")
    p.add_argument("--since", default="")
    p.add_argument("--launcher", required=True)
    p.add_argument("--profile", choices=PROFILES, required=True)
    p.add_argument("--agent-name", default=DEFAULT_AGENT)
    p.add_argument("--channel", choices=CHANNELS, default="release")
    p.add_argument("--register", choices=("default", "yes", "no"), default="default")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--prepared", choices=("all", "python"))

    p = sub.add_parser("prepare", help="prepare this tree's environment (rollback)")
    p.add_argument("--python", action="store_true", required=True)

    p = sub.add_parser("manifest-probe", help="CI: fetch a release's update manifest")
    p.add_argument("--tag", required=True)

    sub.add_parser("pull", help="legacy (#532 launcher): select and move only")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # A Windows pipe has the ANSI code page; show '?' for what it cannot encode, never fail.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    parser = _parser()
    args, extra = parser.parse_known_args(argv)
    if extra and args.command != "finish":
        parser.error("unrecognized arguments: " + " ".join(extra))
    if args.command in ("update", "install", "adopt", "finish", "prepare") and not args.uv:
        parser.error("--uv is required")
    try:
        if args.command == "finish":
            return finish(args)
        if args.command == "prepare":
            return prepare_command(args)
        if args.command == "manifest-probe":
            return manifest_probe(args.tag)
        if args.command == "install" and args.agent_name is not None and not valid_agent_name(args.agent_name):
            warn(f"--agent-name {args.agent_name!r} is not a valid name (letters, digits, '.', '_', '-'; "
                 "it starts with a letter or digit).")
            return 2
        run = Run(args.checkout, args.uv)
        if args.command == "update":
            rc = stage1(run, "update", channel_option=args.channel, with_webui=args.with_webui,
                        launcher=args.launcher)
            if rc == 0:
                print_update_complete(run.home)
            return rc
        if args.command == "install":
            return stage1(run, "install", channel_option=args.channel, profile_option=args.profile,
                          agent_option=args.agent_name, register=args.register,
                          non_interactive=args.non_interactive, new_checkout=args.new_checkout,
                          launcher=args.launcher)
        if args.command == "adopt":
            return stage1(run, "adopt", launcher=args.launcher, from_sha=args.from_sha, prepared=args.prepared)
        if args.command == "pull":
            return stage1(run, "pull")
    except Stop as stop:
        if stop.message:
            warn(stop.message)
        return stop.code
    except GitError as error:
        warn(f"{error}; nothing was changed.")
        return 1
    except KeyboardInterrupt:
        return 130
    return 2


if __name__ == "__main__":
    sys.exit(main())
