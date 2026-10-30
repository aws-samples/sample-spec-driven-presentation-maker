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
