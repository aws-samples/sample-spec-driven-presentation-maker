# SPDX-License-Identifier: MIT-0
"""One-time bridge for installs whose ``sdpm`` command predates the refresh step.

The installer copies ``scripts/install/launcher.sh`` to ``~/.local/bin/sdpm``
(``launcher.ps1`` to ``%USERPROFILE%\\bin\\sdpm.ps1`` on Windows). The launcher shipped
since #397 never replaced that copy, so its ``sdpm update`` cannot reach the install
lifecycle (``servers/local/checkout_update.py``: the release the install follows, the new
launcher, re-registered clients, leftovers removed, upgrading notes). It does, after the
pull, run ``python -m sdpm.knowledge.assets.download`` with the *new* checkout's code — the
one place new code runs inside an old update. That module's ``__main__`` calls :func:`run`,
which starts ``checkout_update.py adopt`` when, and only when, the installed launcher is
such an old one. adopt replaces the launcher with the bootstrap, so the bridge runs once;
an update started by a newer launcher never reaches it.

This is a deliberate exception to the dependency rule (the core starting
``servers/local`` code), kept to a subprocess and to this file. Remove the module and
the ``__main__`` block of ``sdpm/knowledge/assets/download.py`` two minor releases after
the release that ships it; that release's CHANGELOG then tells anyone still on an older
launcher to re-run the installer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

# Every launcher this project shipped carries the fingerprint; the ones that refresh
# themselves name the refresh command (#529, #532), the bootstrap carries its marker. The
# core cannot import servers/local, so these are copies of checkout_update's (a test checks).
LAUNCHER_FINGERPRINT = "the one launcher for a local SDPM installation"
SELF_REFRESH_MARKER = "client_config.py refresh"
BOOTSTRAP_MARKER = "sdpm-bootstrap"
# checkout_update's interpreter line: a fresh environment outside the checkout's .venv.
PY_ARGS = ["run", "--no-project", "--isolated", "--python", ">=3.11", "python"]


def _checkout() -> Path:
    return Path(__file__).resolve().parents[2]


def _sdpm_home() -> Path:
    env = os.environ.get("SDPM_HOME")
    return Path(env).expanduser() if env else Path.home() / ".sdpm"


def installed_launcher() -> Optional[Path]:
    """Where the installer put the ``sdpm`` command (its default, or SDPM_LAUNCHER_DIR)."""
    windows = sys.platform == "win32"
    name = "sdpm.ps1" if windows else "sdpm"
    env = os.environ.get("SDPM_LAUNCHER_DIR")
    if env:
        candidates = [Path(env).expanduser() / name]
    else:
        candidates = [Path.home() / ("bin" if windows else ".local/bin") / name]
        on_path = shutil.which("sdpm.cmd" if windows else "sdpm")
        if on_path:
            candidates.append(Path(on_path).parent / name)
    return next((p for p in candidates if p.is_file()), None)


def is_old_launcher(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return LAUNCHER_FINGERPRINT in text and SELF_REFRESH_MARKER not in text and BOOTSTRAP_MARKER not in text


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


def _uv(home: Path) -> Optional[str]:
    try:
        recorded = (home / ".uv-path").read_text(encoding="utf-8").strip()
    except OSError:
        recorded = ""
    if recorded and Path(recorded).is_file():
        return recorded
    return shutil.which("uv")


def _orig_head(checkout: Path) -> Optional[str]:
    """The commit before the pull: ``git pull`` records it as ORIG_HEAD."""
    out = subprocess.run(  # nosec B603 B607 - fixed git command, local checkout
        ["git", "-C", str(checkout), "rev-parse", "--verify", "-q", "ORIG_HEAD"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def adopt_command(checkout: Path, home: Path) -> Optional[list[str]]:
    """The ``adopt`` to run for this process, or None when there is nothing to bridge."""
    if not (checkout / ".git").exists() or not _same_path(checkout, home / "checkout"):
        return None  # a development clone, or not an installed checkout
    launcher = installed_launcher()
    if launcher is None or not is_old_launcher(launcher):
        return None
    uv = _uv(home)
    if not uv:
        return None
    # The checkout as the launcher names it ($SDPM_HOME/checkout, links unresolved), so the
    # clients get the same paths as from `sdpm register`.
    installed = home / "checkout"
    argv = [uv, *PY_ARGS, str(installed / "servers" / "local" / "checkout_update.py"),
            "--checkout", str(installed), "--uv", uv, "adopt"]
    since = _orig_head(installed)
    if since:
        argv += ["--from", since]
    # The #397 launcher synced Python; it builds the Web UI itself after this returns.
    return argv + ["--launcher", str(launcher), "--prepared", "python"]


def _child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}


def run(call: Callable[..., int] = subprocess.call) -> None:
    """Finish an update started by an old launcher. Never fails the caller's update."""
    try:
        checkout = _checkout()
        home = _sdpm_home()
        argv = adopt_command(checkout, home)
        if argv is None:
            return
        print("> Refreshing the sdpm command and MCP clients (once: this sdpm command predates the step)...")
        sys.stdout.flush()
        # uv's interpreter line and checkout_update.py; outside the .venv this process runs in.
        if call(argv, env=_child_env(), cwd=str(home)) != 0:  # nosec B603
            print("  Some of it did not finish (see above); `sdpm update` again retries.")
    except Exception as error:  # noqa: BLE001 - the old launcher's update must go on
        print(f"  Could not refresh the sdpm command ({error}); `sdpm update` again retries.")
