# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Sync CDP client (sdpm.engine.html.cdp) and browser resolution (sdpm.engine.html.browser)."""

from __future__ import annotations

import contextlib
import json
import threading
import time
from pathlib import Path

import pytest
from websockets.sync.server import serve

from sdpm.engine.html import browser
from sdpm.engine.html.browser import (
    DISABLED_NOTE,
    SKIPPED_NOTE,
    BrowserEndpoint,
    find_browser,
    not_found_note,
    register_browser_source,
    registered_browser_source,
    resolve_browser,
)
from sdpm.engine.html.cdp import CdpConnection, CdpError, CdpTimeout


def _handler(ws):
    """A fake DevTools endpoint: an event before every reply; a few special methods."""
    for raw in ws:
        msg = json.loads(raw)
        method = msg["method"]
        if method == "Silent":
            continue
        if method == "Close":
            ws.close()
            return
        ws.send(json.dumps({"method": "Test.event", "params": {"for": msg["id"]}}))
        if method == "Fail":
            ws.send(json.dumps({"id": msg["id"], "error": {"code": -32000, "message": "nope"}}))
        elif method == "Runtime.evaluate" and msg["params"]["expression"] == "throw":
            ws.send(json.dumps({"id": msg["id"], "result": {
                "result": {"type": "object"},
                "exceptionDetails": {"text": "Uncaught", "exception": {"description": "Error: thrown"}}}}))
        elif method == "Runtime.evaluate":
            ws.send(json.dumps({"id": msg["id"], "result": {"result": {"type": "number", "value": 42}}}))
        else:
            ws.send(json.dumps({"id": msg["id"], "result": {"echo": msg.get("params"),
                                                            "session": msg.get("sessionId")}}))


@pytest.fixture
def fake_devtools():
    with serve(_handler, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.socket.getsockname()[1]
        try:
            yield f"ws://127.0.0.1:{port}/devtools/browser/x"
        finally:
            server.shutdown()


def test_reply_is_returned_and_events_are_kept(fake_devtools) -> None:
    with CdpConnection(fake_devtools) as cdp:
        assert cdp.send("Target.getTargets", {"a": 1}) == {"echo": {"a": 1}, "session": None}
        assert cdp.send("Page.enable", session="S1")["session"] == "S1"
        events = cdp.take_events()
        assert [e["method"] for e in events] == ["Test.event", "Test.event"]
        assert cdp.take_events() == []


def test_on_event_sees_events_while_waiting(fake_devtools) -> None:
    seen = []
    with CdpConnection(fake_devtools) as cdp:
        cdp.on_event = seen.append
        cdp.send("X")
    assert [e["method"] for e in seen] == ["Test.event"]


def test_post_from_on_event_keeps_the_awaited_reply(fake_devtools) -> None:
    """A command posted while a reply is awaited is sent; its own reply is ignored."""
    posted = []

    def hook(event):
        if not posted:
            posted.append(event)
            cdp.post("Answer", {"n": 1}, session="S2")

    with CdpConnection(fake_devtools) as cdp:
        cdp.on_event = hook
        assert cdp.send("X", {"k": 2}) == {"echo": {"k": 2}, "session": None}
        assert cdp.send("Y", {"k": 3}) == {"echo": {"k": 3}, "session": None}
    assert len(posted) == 1


def test_evaluate(fake_devtools) -> None:
    with CdpConnection(fake_devtools) as cdp:
        assert cdp.evaluate("S1", "1+1") == 42
        with pytest.raises(CdpError, match="Error: thrown"):
            cdp.evaluate("S1", "throw")


def test_error_reply_raises(fake_devtools) -> None:
    with CdpConnection(fake_devtools) as cdp:
        with pytest.raises(CdpError, match="Fail: nope"):
            cdp.send("Fail")


def test_silent_server_times_out(fake_devtools) -> None:
    with CdpConnection(fake_devtools) as cdp:
        started = time.monotonic()
        with pytest.raises(CdpTimeout):
            cdp.send("Silent", timeout=0.3)
        assert time.monotonic() - started < 2


def test_closed_socket_raises(fake_devtools) -> None:
    with CdpConnection(fake_devtools) as cdp:
        with pytest.raises(CdpError) as info:
            cdp.send("Close", timeout=5)
        assert not isinstance(info.value, CdpTimeout)


def test_connect_failure_is_a_cdp_error() -> None:
    with pytest.raises(CdpError, match="could not connect"):
        with CdpConnection("ws://127.0.0.1:9/devtools", open_timeout=2):
            pass


# ── browser resolution ────────────────────────────────────────────────────

@contextlib.contextmanager
def _registered_endpoint(width, height):
    yield BrowserEndpoint("ws://x", {"Authorization": "a"}, "Registered")


def test_register_browser_source() -> None:
    assert registered_browser_source() is None  # conftest clears it
    register_browser_source(_registered_endpoint)
    assert registered_browser_source() is _registered_endpoint
    register_browser_source(None)
    assert registered_browser_source() is None


def test_resolve_order(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "chrome"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(browser, "_registered", _registered_endpoint)
    monkeypatch.setenv("SDPM_BROWSER", "none")
    assert resolve_browser() == (None, DISABLED_NOTE)  # none beats registered
    monkeypatch.setenv("SDPM_BROWSER", str(exe))
    assert resolve_browser() == (_registered_endpoint, None)  # registered beats a path
    monkeypatch.setattr(browser, "_registered", None)
    source, note = resolve_browser()
    assert note is None and source.browser_name == "Google Chrome"
    missing = str(tmp_path / "missing")
    monkeypatch.setenv("SDPM_BROWSER", missing)
    assert resolve_browser() == (None, not_found_note(missing))
    monkeypatch.delenv("SDPM_BROWSER")
    monkeypatch.setattr(browser, "find_browser", lambda: None)
    assert resolve_browser() == (None, SKIPPED_NOTE)
    monkeypatch.setattr(browser, "find_browser", lambda: "/opt/msedge")
    source, note = resolve_browser()
    assert note is None and source.browser_name == "Microsoft Edge"


def test_find_browser_honours_sdpm_browser(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "chrome"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("SDPM_BROWSER", "none")
    assert find_browser() is None
    monkeypatch.setenv("SDPM_BROWSER", str(exe))
    assert find_browser() == str(exe)
    monkeypatch.setenv("SDPM_BROWSER", str(tmp_path / "missing"))
    assert find_browser() is None


def test_local_browser_temp_dir_failure_raises_before_starting(monkeypatch) -> None:
    def no_space(**_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(browser.tempfile, "mkdtemp", no_space)
    monkeypatch.setattr(browser.subprocess, "Popen", lambda *a, **k: pytest.fail("browser started"))
    with pytest.raises(OSError, match="No space"):
        with browser.local_browser("/opt/chrome", 1920, 1080):
            pass


class _FakeBrowser:
    """Popen stand-in: launch number ``n`` writes DevToolsActivePort when ``n`` is in
    ``ready``, exits with ``exit_code`` when given, and otherwise never starts DevTools."""

    ready: set = set()
    exit_code: int | None = None
    launched: list = []

    def __init__(self, argv, **_kwargs):
        self.profile = Path(next(a for a in argv if a.startswith("--user-data-dir=")).split("=", 1)[1])
        self.stopped = False
        type(self).launched.append(self)
        if len(type(self).launched) in type(self).ready:
            (self.profile / "DevToolsActivePort").write_text("4242\n/devtools/browser/x\n", encoding="utf-8")

    def poll(self):
        if self.exit_code is not None:
            return self.exit_code
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.stopped = True


@pytest.fixture
def fake_browser(monkeypatch):
    _FakeBrowser.ready, _FakeBrowser.exit_code, _FakeBrowser.launched = set(), None, []
    monkeypatch.setattr(browser.subprocess, "Popen", _FakeBrowser)
    return _FakeBrowser


def test_local_browser_retries_a_launch_whose_devtools_does_not_start(fake_browser, caplog) -> None:
    fake_browser.ready = {2}
    with caplog.at_level("WARNING", logger=browser.__name__):
        with browser.local_browser("/opt/google-chrome", 1280, 720, start_timeout=0.1) as endpoint:
            assert endpoint == BrowserEndpoint("ws://127.0.0.1:4242/devtools/browser/x", {}, "Google Chrome")
            first, second = fake_browser.launched
            assert first.stopped and not first.profile.exists(), "the hung launch is stopped and cleaned up"
            assert first.profile != second.profile and not second.stopped
    assert second.stopped and not second.profile.exists()
    assert "DevTools did not start within 0.1 s; starting it once more" in caplog.text


def test_local_browser_gives_up_after_the_second_timeout(fake_browser) -> None:
    with pytest.raises(TimeoutError, match=r"^DevTools did not start within 0.1 s \(tried 2 times\)$"):
        with browser.local_browser("/opt/google-chrome", 1280, 720, start_timeout=0.1):
            pytest.fail("no endpoint")
    assert len(fake_browser.launched) == 2
    assert all(p.stopped and not p.profile.exists() for p in fake_browser.launched)


def test_local_browser_does_not_retry_a_browser_that_exits(fake_browser) -> None:
    fake_browser.exit_code = 1
    with pytest.raises(RuntimeError, match=r"exited \(code 1\) before DevTools started"):
        with browser.local_browser("/opt/google-chrome", 1280, 720, start_timeout=5):
            pytest.fail("no endpoint")
    assert len(fake_browser.launched) == 1 and not fake_browser.launched[0].profile.exists()


@pytest.mark.parametrize(("value", "expected"), [
    (None, 15.0), ("", 15.0), ("45", 45.0), ("2.5", 2.5), ("1000", 120.0),
    ("0", 15.0), ("-3", 15.0), ("soon", 15.0), ("nan", 15.0), ("inf", 15.0),
])
def test_browser_start_timeout_reads_the_environment(monkeypatch, value, expected) -> None:
    if value is None:
        monkeypatch.delenv(browser.START_TIMEOUT_ENV, raising=False)
    else:
        monkeypatch.setenv(browser.START_TIMEOUT_ENV, value)
    assert browser.browser_start_timeout() == expected