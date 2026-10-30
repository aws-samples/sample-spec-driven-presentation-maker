# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Where the browser check gets its browser (design §9).

A ``BrowserSource`` is a callable ``(width, height) -> ContextManager[BrowserEndpoint]``:
entering it starts (or borrows) a browser and yields the DevTools WebSocket URL, the
headers to connect with and a display name; leaving it releases the browser.

Two kinds exist. The local source (``local_browser``) starts the Chrome or Edge found on
this machine headless, with DevTools on a random loopback port, a temporary profile and
no network. Adapters register their own with ``register_browser_source`` — the remote
server registers AgentCore Browser; the core itself never imports AWS code.

``resolve_browser`` picks one: ``SDPM_BROWSER=none`` → the registered source →
``SDPM_BROWSER=<path>`` → an auto-detected Chrome / Edge → none (with a skip note).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, ContextManager, Iterator


@dataclass(frozen=True)
class BrowserEndpoint:
    """A DevTools browser endpoint: WebSocket URL, connect headers, display name."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    name: str = "browser"


BrowserSource = Callable[[int, int], ContextManager[BrowserEndpoint]]

DISABLED_NOTE = ("Browser check skipped: turned off here (SDPM_BROWSER=none), so layout, JS errors "
                 "and PNG previews of the slides are unknown.")
SKIPPED_NOTE = ("Browser check skipped: no Chrome or Edge found, so layout, JS errors and PNG previews "
                "of the slides are unknown — install Chrome or Edge, or open output.html to look.")


def not_found_note(value: str) -> str:
    """The skip note for an ``SDPM_BROWSER`` path that does not exist."""
    return (f"Browser check skipped: SDPM_BROWSER={value!r} is not an executable, so layout, JS errors "
            "and PNG previews of the slides are unknown.")


_registered: BrowserSource | None = None


def register_browser_source(source: BrowserSource | None) -> None:
    """Make ``source`` the browser of every check in this process (None removes it)."""
    global _registered
    _registered = source


def registered_browser_source() -> BrowserSource | None:
    """The source an adapter registered, or None."""
    return _registered


# ── local Chrome / Edge ───────────────────────────────────────────────────

_MAC_APPS = ("Google Chrome.app/Contents/MacOS/Google Chrome",
             "Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
_LINUX_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "microsoft-edge", "microsoft-edge-stable")
_WINDOWS_ROOTS = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")
_WINDOWS_EXES = (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe")

_FLAGS = (
    "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-background-networking", "--disable-sync", "--mute-audio",
    # No network: the check runs untrusted slide code automatically.
    "--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>",
    "--host-resolver-rules=MAP * ~NOTFOUND",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
)


def find_browser() -> str | None:
    """Chrome or Edge executable, or None. ``SDPM_BROWSER`` (a path; ``none`` disables) wins."""
    override = os.environ.get("SDPM_BROWSER", "").strip()
    if override:
        if override.lower() == "none":
            return None
        return override if os.path.isfile(override) else shutil.which(override)
    candidates: list[str] = []
    if sys.platform == "darwin":
        for root in ("/Applications", os.path.expanduser("~/Applications")):
            candidates += [os.path.join(root, app) for app in _MAC_APPS]
    if os.name == "nt":
        for exe in _WINDOWS_EXES:
            candidates += [os.path.join(os.environ[root], exe)
                           for root in _WINDOWS_ROOTS if os.environ.get(root)]
    for path in candidates:
        if os.path.isfile(path):
            return path
    if os.name != "nt":
        for name in _LINUX_NAMES:
            found = shutil.which(name)
            if found:
                return found
    return None


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _remove(profile: str) -> None:
    shutil.rmtree(profile, ignore_errors=True)
    if os.path.exists(profile):  # Windows: the browser may still hold files for a moment
        time.sleep(0.5)
        shutil.rmtree(profile, ignore_errors=True)


def _display_name(executable: str) -> str:
    name = Path(executable).name.lower()
    if "edge" in name:
        return "Microsoft Edge"
    if "chromium" in name:
        return "Chromium"
    if "chrome" in name:
        return "Google Chrome"
    return Path(executable).name


@contextlib.contextmanager
def local_browser(executable: str, width: int, height: int, *,
                  start_timeout: float = 15.0) -> Iterator[BrowserEndpoint]:
    """Start ``executable`` headless with DevTools on a random 127.0.0.1 port.

    The port and path come from ``DevToolsActivePort`` in a temporary profile; the
    browser is stopped and the profile removed on exit.
    """
    profile = tempfile.mkdtemp(prefix="sdpm-browser-")
    proc = None
    try:
        argv = [executable, *_FLAGS, f"--window-size={width},{height}", "--remote-debugging-port=0",
                f"--user-data-dir={profile}", "about:blank"]
        # Fixed argv, no shell; the executable comes from a fixed list or SDPM_BROWSER.
        proc = subprocess.Popen(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = Path(profile) / "DevToolsActivePort"
        started = time.monotonic()
        while True:
            lines = port_file.read_text(encoding="utf-8").splitlines() if port_file.is_file() else []
            if len(lines) >= 2 and lines[0].strip().isdigit():
                break
            code = proc.poll()
            if code is not None:
                raise RuntimeError(f"{Path(executable).name} exited (code {code}) before DevTools started")
            if time.monotonic() - started > start_timeout:
                raise TimeoutError(f"DevTools did not start within {start_timeout:g} s")
            time.sleep(0.05)
        port, path = lines[0].strip(), lines[1].strip()
        yield BrowserEndpoint(f"ws://127.0.0.1:{port}{path}", {}, _display_name(executable))
    finally:
        if proc is not None:
            _stop(proc)
        _remove(profile)


def _local_source(executable: str) -> BrowserSource:
    def source(width: int, height: int) -> ContextManager[BrowserEndpoint]:
        return local_browser(executable, width, height)
    source.browser_name = _display_name(executable)  # type: ignore[attr-defined]  # named before it starts
    return source


def resolve_browser() -> tuple[BrowserSource | None, str | None]:
    """``(source, None)`` for the browser to use, or ``(None, skip note)``."""
    override = os.environ.get("SDPM_BROWSER", "").strip()
    if override.lower() == "none":
        return None, DISABLED_NOTE
    if _registered is not None:
        return _registered, None
    executable = find_browser()
    if executable is None:
        return None, not_found_note(override) if override else SKIPPED_NOTE
    return _local_source(executable), None


__all__ = ["BrowserEndpoint", "BrowserSource", "DISABLED_NOTE", "SKIPPED_NOTE", "find_browser",
           "local_browser", "not_found_note", "register_browser_source", "registered_browser_source",
           "resolve_browser"]
