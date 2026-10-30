# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Optional JS error check for HTML decks in headless Chrome / Edge (design §8.5).

``check_js`` opens ``output.html#print-pdf&sdpm-check`` in a headless Chrome or Edge with
console logging written to a file. The print view runs every slide script once (each
fragment clone too), and the slide helper logs ``sdpm-check:done`` one second after
``pdf-ready``. The log is read every 0.1 s until that line or the timeout; then the
browser is stopped and its temporary profile removed. Console lines that report a
failing slide (``sdpm slide <slug>: …``), an uncaught exception or a CSP violation
become errors, attributed to a slug through the assembler's line map.

The check executes slide code the agent wrote, so the browser runs without network:
every request goes to a dead proxy on 127.0.0.1:9 (loopback included), host names do
not resolve, and WebRTC may not use UDP outside the proxy. No DevTools port is opened.

Stdlib only: no Playwright, no WebSocket. ``SDPM_BROWSER`` names the executable
(``none`` disables the check); ``SDPM_JS_CHECK=0`` turns it off (the cloud runtime
image has no browser).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DONE = "sdpm-check:done"
_ERROR_HINTS = ("sdpm slide ", "Uncaught", "violates the following Content Security Policy",
                "Refused to")
# [pid:tid:date/time.us:INFO:CONSOLE:<n>] "<msg>", source: <url> (<n>)   (Chrome 156 / Edge 152)
# [pid:tid:date/time.us:INFO:CONSOLE(<n>)] "<msg>", source: <url> (<n>)  (older builds)
_CONSOLE_RE = re.compile(
    r':INFO:CONSOLE(?::\d+|\(\d+\))\] "(?P<msg>.*?)", source: (?P<src>\S*) \((?P<line>\d+)\)',
    re.DOTALL)
_HASHES_RE = re.compile(r"script-src(?: 'sha256-[^']+')+")
_HELPER_SLUG_RE = re.compile(r"sdpm slide (\S+?): ")
_MAX_MESSAGE = 400

_MAC_APPS = ("Google Chrome.app/Contents/MacOS/Google Chrome",
             "Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
_LINUX_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "microsoft-edge", "microsoft-edge-stable")
_WINDOWS_ROOTS = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")
_WINDOWS_EXES = (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe")

_FLAGS = (
    "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-background-networking", "--disable-sync", "--mute-audio",
    "--window-size=1920,1080",
    # No network: the check runs untrusted slide code automatically.
    "--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>",
    "--host-resolver-rules=MAP * ~NOTFOUND",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
)

SKIPPED_NOTE = ("No Chrome or Edge found; JS errors were not checked — open output.html and "
                "look at the browser console.")


def js_check_enabled() -> bool:
    """False when ``SDPM_JS_CHECK`` is ``0`` / ``false`` / ``off``."""
    return os.environ.get("SDPM_JS_CHECK", "").strip().lower() not in {"0", "false", "off"}


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


def parse_console_log(text: str) -> list[tuple[int, str]]:
    """``(output.html line, message)`` of the error lines of a browser console log."""
    out: list[tuple[int, str]] = []
    for m in _CONSOLE_RE.finditer(text):
        msg = m.group("msg")
        if DONE in msg or not any(hint in msg for hint in _ERROR_HINTS):
            continue
        item = (int(m.group("line")), _HASHES_RE.sub("script-src …", msg)[:_MAX_MESSAGE])
        if item not in out:
            out.append(item)
    return out


def attribute(line: int, line_map) -> str | None:
    """The slug whose section or slide script covers ``line`` (``(first, last, slug)`` ranges)."""
    for first, last, slug in line_map:
        if first <= line <= last:
            return slug
    return None


def _slug_of(line: int, message: str, line_map) -> str | None:
    """The slug the helper names (``sdpm slide <slug>: …``, logged from the helper's own
    line), else the one whose lines contain ``line``."""
    m = _HELPER_SLUG_RE.match(message)
    if m and any(slug == m.group(1) for _, _, slug in line_map):
        return m.group(1)
    return attribute(line, line_map)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


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


def check_js(output_html: Path, line_map, *, timeout: float = 15.0) -> dict:
    """Open ``output_html`` headless and collect JS errors. Never raises.

    Returns:
        ``{status, browser?, seconds?, errors, note?}``; status is ``ok`` / ``errors`` /
        ``skipped`` (no browser) / ``timeout`` (no done line; errors read so far kept) /
        ``failed`` (the browser could not be run or exited early). errors:
        ``[{slug | None, line, message}]``.
    """
    browser = find_browser()
    if browser is None:
        return {"status": "skipped", "errors": [], "note": SKIPPED_NOTE}
    profile = tempfile.mkdtemp(prefix="sdpm-jscheck-")
    log_file = Path(profile) / "console.log"
    url = Path(output_html).resolve().as_uri() + "#print-pdf&sdpm-check"
    argv = [browser, *_FLAGS, f"--user-data-dir={profile}", "--enable-logging",
            f"--log-file={log_file}", "--v=0", url]
    started = time.monotonic()
    done = False
    exit_code = None
    try:
        # Fixed argv, no shell; the executable comes from a fixed list or SDPM_BROWSER.
        proc = subprocess.Popen(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            while time.monotonic() - started < timeout:
                if DONE in _read(log_file):
                    done = True
                    break
                exit_code = proc.poll()
                if exit_code is not None:
                    break
                time.sleep(0.1)
        finally:
            _stop(proc)
        seconds = round(time.monotonic() - started, 1)
        time.sleep(0.2)
        text = _read(log_file)
    except OSError as exc:
        _remove(profile)
        return {"status": "failed", "browser": browser, "errors": [],
                "note": f"JS check could not run {Path(browser).name}: {exc}"}
    _remove(profile)
    done = done or DONE in text
    errors = [{"slug": _slug_of(line, msg, line_map), "line": line, "message": msg}
              for line, msg in parse_console_log(text)]
    result = {"status": "errors" if errors else "ok", "browser": browser, "seconds": seconds,
              "errors": errors}
    if not done and exit_code is not None:
        result["status"] = "failed"
        result["note"] = (f"{Path(browser).name} exited (code {exit_code}) before the JS check "
                          f"finished; {len(errors)} error(s) read.")
    elif not done:
        result["status"] = "timeout"
        result["note"] = (f"JS check did not finish within {timeout:g} s; "
                          f"{len(errors)} error(s) read before it stopped.")
    return result


__all__ = ["SKIPPED_NOTE", "attribute", "check_js", "find_browser", "js_check_enabled",
           "parse_console_log"]
