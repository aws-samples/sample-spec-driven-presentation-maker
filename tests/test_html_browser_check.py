# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Browser check for HTML decks (sdpm.engine.html.browser_check).

The real-browser tests are opt-in: ``SDPM_TEST_BROWSER=1`` with Chrome or Edge installed
(``SDPM_BROWSER`` picks one). Everything else uses fake events and sources.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sdpm import api
from sdpm.engine.html import browser, browser_check
from sdpm.engine.html.browser import DISABLED_NOTE, BrowserEndpoint, find_browser
from sdpm.engine.html.browser_check import check_deck, deadline_for, errors_from_events

# conftest sets SDPM_BROWSER=none for every test; the real-browser tests restore this.
_ENV_BROWSER = os.environ.get("SDPM_BROWSER")
LINE_MAP = [(10, 20, "a"), (21, 30, "b"), (40, 42, "a")]


def _exception(line: int | None, text: str = "Uncaught Error: boom", ctx: int = 1) -> dict:
    details = {"text": "Uncaught", "exception": {"description": text}, "executionContextId": ctx}
    if line is not None:
        details["lineNumber"] = line - 1  # CDP lines are 0-based
    return {"method": "Runtime.exceptionThrown", "params": {"exceptionDetails": details}}


def _console(value: str, kind: str = "error", ctx: int = 1) -> dict:
    return {"method": "Runtime.consoleAPICalled",
            "params": {"type": kind, "args": [{"type": "string", "value": value}], "executionContextId": ctx}}


def _log(text: str, line: int | None = None, level: str = "error") -> dict:
    entry = {"source": "security", "level": level, "text": text}
    if line is not None:
        entry["lineNumber"] = line - 1
    return {"method": "Log.entryAdded", "params": {"entry": entry}}


# ── errors_from_events ────────────────────────────────────────────────────

def test_errors_are_attributed() -> None:
    events = [
        _console("sdpm slide b: ReferenceError: x is not defined\n    at section (about:blank:25:1)"),
        _exception(41),
        _exception(None, "Uncaught TypeError: late"),
        _log("Refused to load the script 'https://example.com/x.js' because it violates the following "
             "Content Security Policy directive: \"script-src 'sha256-AAA' 'sha256-BBB' 'self'\".", 15),
    ]
    errors = errors_from_events(events, LINE_MAP, {1}, "b")
    assert [(e["slug"], e.get("line")) for e in errors] == [("b", None), ("a", 41), ("b", None), ("a", 15)]
    assert errors[0]["message"].startswith("JS error: sdpm slide b: ReferenceError")
    assert all(e["rule"] == "js-error" for e in errors)
    assert "script-src …" in errors[3]["message"] and "sha256" not in errors[3]["message"]
    assert errors[3]["message"].endswith(browser_check.CSP_FIX)
    assert not errors[1]["message"].endswith(browser_check.CSP_FIX)


def test_noise_and_other_worlds_are_dropped() -> None:
    events = [
        _exception(12, "SecurityError: Failed to execute 'replaceState' on 'History': …", ctx=1),
        _exception(12, "Error: Extension context invalidated.", ctx=1),
        _exception(12, "Uncaught Error: from an extension", ctx=7),  # not the main world
        _console("sdpm slide a: fine", kind="info"),
        _console("echarts warning", kind="error"),  # not the helper's
        _log("Failed to load resource: net::ERR_BLOCKED_BY_CLIENT"),
        _log("Refused to frame", level="warning"),
    ]
    assert errors_from_events(events, LINE_MAP, {1}, "a") == []


def test_foreign_slugs_are_dropped_unattributed_kept() -> None:
    events = [_console("sdpm slide b: Error: theirs"), _exception(12), _exception(None, "Uncaught loose")]
    errors = errors_from_events(events, LINE_MAP, None, None, slugs=["a"])
    assert [e["slug"] for e in errors] == ["a", None]


def test_error_messages_are_cut_and_deduplicated() -> None:
    errors = errors_from_events([_exception(12, "x" * 1000), _exception(12, "x" * 1000)], LINE_MAP, None, None)
    assert len(errors) == 1 and len(errors[0]["message"]) == len("JS error: ") + 400


def test_deadline() -> None:
    assert deadline_for(1) == 33 and deadline_for(10) == 60 and deadline_for(40) == 110


# ── check_deck without a browser ──────────────────────────────────────────

def _check(tmp_path: Path, slugs=("a",), **kw) -> dict:
    page = tmp_path / "output.html"
    page.write_text("<html></html>", encoding="utf-8")
    return check_deck(page, list(slugs), slide_size=(1920, 1080), line_map=LINE_MAP, layouts={},
                      decorations={}, png_dir=tmp_path / "png", **kw)


def test_disabled_check_starts_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(browser, "_registered", lambda w, h: pytest.fail("source used"))
    result = _check(tmp_path)
    assert result == {"status": "skipped", "slides": 0, "checked": [], "findings": {}, "errors": [],
                      "pngs": {}, "note": DISABLED_NOTE}


def test_failing_source_is_reported(tmp_path: Path, monkeypatch) -> None:
    @contextlib.contextmanager
    def broken(width, height):
        raise RuntimeError("no session")
        yield  # pragma: no cover

    broken.browser_name = "Fake Browser"
    monkeypatch.delenv("SDPM_BROWSER")
    monkeypatch.setattr(browser, "_registered", broken)
    result = _check(tmp_path, ["a", "b"])
    assert result["status"] == "failed" and result["browser"] == "Fake Browser"
    assert result["note"].startswith("Browser check could not run (Fake Browser): RuntimeError: no session")
    assert "0 of 2 slide(s) checked" in result["note"]
    assert not (tmp_path / "png").exists()


def test_unreachable_endpoint_is_reported(tmp_path: Path, monkeypatch) -> None:
    released = []

    @contextlib.contextmanager
    def dead(width, height):
        try:
            yield BrowserEndpoint("ws://127.0.0.1:9/devtools/browser/x", {}, "Dead")
        finally:
            released.append((width, height))

    monkeypatch.delenv("SDPM_BROWSER")
    monkeypatch.setattr(browser, "_registered", dead)
    result = _check(tmp_path)
    assert result["status"] == "failed" and "(Dead)" in result["note"] and "could not connect" in result["note"]
    assert released == [(1920, 1080)]


class _NoBlockCdp:
    """CdpConnection stand-in whose browser rejects one command (``reject``: the request block)."""

    sent: list[str] = []
    reject: str | None = "Fetch.enable"

    def __init__(self, url, headers=None, **_kw):
        self.on_event = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def take_events(self):
        return []

    def evaluate(self, session, expr, **_kw):
        pytest.fail(f"page script evaluated: {expr[:40]}")

    def send(self, method, params=None, *, session=None, timeout=15.0):
        type(self).sent.append(method)
        if method == type(self).reject:
            raise browser_check.CdpError(f"{method}: '{method}' wasn't found")
        return {"Target.getTargets": {"targetInfos": [{"type": "page", "targetId": "t1"}]},
                "Target.attachToTarget": {"sessionId": "s1"},
                "Page.getFrameTree": {"frameTree": {"frame": {"id": "f1"}}}}.get(method, {})


class _ReachableRtcCdp(_NoBlockCdp):
    """Accepts every command and loads the deck, but the egress probe still finds WebRTC."""

    reject = None

    def evaluate(self, session, expr, **_kw):
        if expr == browser_check.EGRESS_PROBE:
            type(self).sent.append("probe")
            return ["top.RTCPeerConnection"]
        if "Reveal.isReady" in expr:
            return True
        if expr.startswith(browser_check.CONFIGURE):
            return 0
        pytest.fail(f"page script evaluated: {expr[:40]}")


def _no_block_source(monkeypatch, cdp=_NoBlockCdp, reject="Fetch.enable"):
    @contextlib.contextmanager
    def source(width, height):
        yield BrowserEndpoint("ws://127.0.0.1:9/devtools/browser/x", {}, "Remote Browser")

    _NoBlockCdp.sent = []
    monkeypatch.setattr(_NoBlockCdp, "reject", reject)
    monkeypatch.delenv("SDPM_BROWSER")
    monkeypatch.setattr(browser, "_registered", source)
    monkeypatch.setattr(browser_check, "CdpConnection", cdp)


def test_rejected_network_block_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """A browser that will not block requests never loads the deck: failed, with a note."""
    _no_block_source(monkeypatch)
    result = _check(tmp_path, ["a", "b"])
    assert result["status"] == "failed" and result["network_blocked"] is False
    assert result["note"].startswith("Browser check could not run (Remote Browser): RuntimeError: could not "
                                     "block network requests, so no slide was run")
    assert "0 of 2 slide(s) checked" in result["note"] and "\n" not in result["note"]
    assert "Page.navigate" not in _NoBlockCdp.sent and "Page.setDocumentContent" not in _NoBlockCdp.sent
    assert result["pngs"] == {}


def test_rejected_network_block_is_one_warning_line_of_the_build(tmp_path: Path, monkeypatch) -> None:
    deck = _deck(tmp_path, {"a": CLEAN})
    _no_block_source(monkeypatch)
    result = api.refresh_html(deck, measure_slides=["a"])
    assert result["browser_check"]["status"] == "failed"
    [line] = [w for w in result["warnings"] if w.startswith("output.html: Browser check")]
    assert line.startswith("output.html: Browser check could not run (Remote Browser): RuntimeError: could not "
                           "block network requests")
    assert result.get("preview_files") == []


def test_rejected_egress_guard_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """A browser that will not take the WebRTC guard never loads the deck."""
    _no_block_source(monkeypatch, reject="Page.addScriptToEvaluateOnNewDocument")
    result = _check(tmp_path, ["a", "b"])
    assert result["status"] == "failed" and result["network_blocked"] is False
    assert result["note"].startswith("Browser check could not run (Remote Browser): RuntimeError: could not "
                                     "disable WebRTC, so no slide was run")
    sent = _NoBlockCdp.sent
    assert sent.index("Fetch.enable") < sent.index("Page.addScriptToEvaluateOnNewDocument")
    assert "Page.navigate" not in sent and "Page.setDocumentContent" not in sent


def test_egress_guard_is_installed_before_the_load_and_a_failed_probe_fails_closed(tmp_path: Path,
                                                                                  monkeypatch) -> None:
    """WebRTC still reachable after the load: no slide is shown, network_blocked is False."""
    _no_block_source(monkeypatch, cdp=_ReachableRtcCdp)
    result = _check(tmp_path, ["a", "b"])
    assert result["status"] == "failed" and result["network_blocked"] is False
    assert result["note"].startswith("Browser check could not run (Remote Browser): RuntimeError: could not "
                                     "disable WebRTC (top.RTCPeerConnection), so no slide was run")
    assert result["checked"] == [] and result["pngs"] == {}
    sent = _NoBlockCdp.sent
    assert sent.index("Page.addScriptToEvaluateOnNewDocument") < sent.index("Page.navigate")
    assert sent.index("Page.setDocumentContent") < sent.index("probe")
    assert "Page.captureScreenshot" not in sent


class _PostCdp:
    """Records the commands posted from the event hook."""

    def __init__(self):
        self.sent = []

    def post(self, method, params=None, *, session=None):
        self.sent.append((method, session, params))


def test_event_hook_fails_blocked_requests_closes_popups_and_blocks_frames() -> None:
    """Answered as events arrive (a paused navigation would otherwise stall an awaited reply)."""
    run = browser_check._Run(["a"], LINE_MAP, 30)
    run.session, run.target_id = "page", "t-page"
    run.cdp = _PostCdp()
    for event in [
        {"method": "Target.attachedToTarget",  # our own attachToTarget: never closed
         "params": {"sessionId": "page", "targetInfo": {"targetId": "t-page", "type": "page"}}},
        {"method": "Fetch.requestPaused", "sessionId": "page", "params": {"requestId": "r1"}},
        {"method": "Fetch.requestPaused", "sessionId": "frame", "params": {"requestId": "r2"}},
        {"method": "Target.attachedToTarget", "sessionId": "page",
         "params": {"sessionId": "popup", "targetInfo": {"targetId": "t-popup", "type": "page"}}},
        {"method": "Target.attachedToTarget", "sessionId": "page",
         "params": {"sessionId": "frame", "targetInfo": {"targetId": "t-frame", "type": "iframe"}}},
    ]:
        run.watch(event)
    sent = [(m, s) for m, s, _ in run.cdp.sent]
    assert ("Fetch.failRequest", "page") in sent and ("Fetch.failRequest", "frame") in sent
    assert ("Target.closeTarget", None) in sent
    guard = sent.index(("Page.addScriptToEvaluateOnNewDocument", "frame"))
    assert sent.index(("Fetch.enable", "frame")) < guard < sent.index(("Runtime.runIfWaitingForDebugger", "frame"))
    [params] = [p for m, s, p in run.cdp.sent if m == "Page.addScriptToEvaluateOnNewDocument"]
    assert params == {"source": browser_check.EGRESS_GUARD, "runImmediately": True}
    closed = [p for m, _, p in run.cdp.sent if m == "Target.closeTarget"]
    assert closed == [{"targetId": "t-popup"}]
    assert run.blocked_requests == 2


def test_temp_dir_failure_is_reported(tmp_path: Path, monkeypatch) -> None:
    """An unwritable temp directory degrades to a note; check_deck never raises."""
    def no_space(**_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setenv("SDPM_BROWSER", sys.executable)  # any existing file: never started
    monkeypatch.setattr(browser.tempfile, "mkdtemp", no_space)
    monkeypatch.setattr(browser.subprocess, "Popen", lambda *a, **k: pytest.fail("browser started"))
    result = _check(tmp_path)
    assert result["status"] == "failed" and "No space left on device" in result["note"]


# ── real browser (opt-in) ─────────────────────────────────────────────────

real_browser = pytest.mark.skipif(
    os.environ.get("SDPM_TEST_BROWSER") != "1" or find_browser() is None,
    reason="real-browser check: set SDPM_TEST_BROWSER=1 with Chrome or Edge installed")


@pytest.fixture
def use_browser(monkeypatch):
    """Undo conftest's SDPM_BROWSER=none: the environment's browser (or auto-detect)."""
    if _ENV_BROWSER:
        monkeypatch.setenv("SDPM_BROWSER", _ENV_BROWSER)
    else:
        monkeypatch.delenv("SDPM_BROWSER", raising=False)


def _deck(tmp_path: Path, slides: dict[str, str]) -> Path:
    deck = tmp_path / "deck"
    api.init("t", output_dir=deck, output_format="html")
    assert api.apply_style(deck, style="typographic", template="blank-light")["status"] == "ok"
    outline = "# Browser deck\n\n" + "".join(f"- [{slug}] {slug}\n" for slug in slides)
    (deck / "specs" / "outline.md").write_text(outline, encoding="utf-8")
    for slug, text in slides.items():
        (deck / "slides" / f"{slug}.html").write_text(text, encoding="utf-8")
    return deck


def _box(x: int, y: int, w: int, h: int) -> str:
    return f"position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px"


def _slide(title: str, body: str = "", layout: str = "Title Only") -> str:
    return f'<section data-layout="{layout}"><h1 data-ph="title">{title}</h1>{body}</section>'


CLEAN = _slide("Short", f'<div data-region="body" style="{_box(96, 400, 800, 300)}"><p>Fine</p></div>')
BROKEN = {
    "clean": CLEAN,
    "overlap": _slide("Overlap", f'<div data-region="a" style="{_box(96, 400, 800, 300)}">a</div>'
                                 f'<div data-region="b" style="{_box(600, 500, 800, 300)}">b</div>'),
    "long-title": _slide("A title far too long for its box " * 12),
    "tall-child": _slide("Tall", f'<div data-region="body" style="{_box(96, 400, 800, 200)}">'
                                 '<div style="height:400px">tall</div></div>'),
    "throws": _slide("Throws", "<script>\nnotDefinedFunction();\n</script>"),
    "ph-body": _slide("Body", '<div data-ph="body">x</div>', layout="Title and Content"),
}


def _warnings_of(result: dict, slug: str) -> list[str]:
    return [w for w in result["warnings"] if w.startswith(f"{slug}: ")]


def _png_size(path: str) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return image.size


@real_browser
def test_real_browser_reports_layout_and_js(tmp_path: Path, use_browser) -> None:
    deck = _deck(tmp_path, BROKEN)
    result = api.refresh_html(deck, measure_slides=list(BROKEN))
    assert result["browser_check"]["status"] == "issues", result
    assert _warnings_of(result, "clean") == []
    assert any(w.startswith('overlap: overlap: data-region="a" × data-region="b"') for w in result["warnings"])
    assert any(w.startswith('long-title: overflow: data-ph="title" content') for w in result["warnings"])
    assert any(w.startswith("tall-child: outside-region: ") for w in result["warnings"]), result["warnings"]
    assert any(w.startswith("throws: JS error: ") and "notDefinedFunction" in w for w in result["warnings"])
    assert any(w.startswith('ph-body: data-ph="body" is not a placeholder') for w in result["warnings"])
    assert len(result["preview_files"]) == len(BROKEN)
    assert all(_png_size(p) == (1280, 720) for p in result["preview_files"])
    assert result["preview_files"][0] == str(deck / "preview" / "png" / "clean.png")
    assert "preview" not in result


@real_browser
def test_real_browser_clean_deck(tmp_path: Path, use_browser) -> None:
    deck = _deck(tmp_path, {"cover": _slide("Cover", layout="Title Slide"), "clean": CLEAN})
    result = api.generate_html(deck, check_slides=["cover", "clean"])
    assert result["browser_check"]["status"] == "ok", result["warnings"]
    assert result["warnings"] == []
    assert set(result["browser_check"]["timings"]) == {"acquire", "connect", "load", "slides", "release"}
    assert result["browser_check"]["network_blocked"] is True


@real_browser
def test_real_browser_checks_only_the_requested_slugs(tmp_path: Path, use_browser) -> None:
    deck = _deck(tmp_path, {"b": _slide("B", "<script>\nnotDefinedFunction();\n</script>"), "a": CLEAN})
    result = api.refresh_html(deck, measure_slides=["a"])
    assert result["browser_check"]["status"] == "ok", result
    assert not any("JS error" in w for w in result["warnings"])
    assert [Path(p).name for p in result["preview_files"]] == ["a.png"]


@real_browser
def test_real_browser_reports_a_js_error_on_the_first_slide(tmp_path: Path, use_browser) -> None:
    """The first slide gets no ready event on the check's page; its script still runs."""
    deck = _deck(tmp_path, {"first": _slide("First", "<script>\nnotDefinedFunction();\n</script>"), "b": CLEAN})
    result = api.refresh_html(deck, measure_slides=["first"])
    assert result["browser_check"]["status"] == "issues", result
    assert any(w.startswith("first: JS error: ") and "notDefinedFunction" in w for w in result["warnings"])


@real_browser
def test_real_browser_endless_animation_does_not_hang(tmp_path: Path, use_browser) -> None:
    spin = ("<style>@keyframes sdpm-spin { to { transform: rotate(360deg); } }"
            ".spin { display: inline-block; width: 40px; height: 40px; margin: 40px;"
            " animation: sdpm-spin 1s linear infinite; }</style>"
            f'<div data-region="body" style="{_box(96, 400, 800, 300)}"><div class="spin"></div></div>'
            "<script>\n(function loop(){ requestAnimationFrame(loop); })();\n</script>")
    deck = _deck(tmp_path, {"spin": _slide("Spin", spin)})
    started = time.monotonic()
    result = api.refresh_html(deck, measure_slides=["spin"])
    assert time.monotonic() - started < 25
    assert result["browser_check"]["status"] == "ok", result


@real_browser
def test_real_browser_stops_at_navigation(tmp_path: Path, use_browser) -> None:
    deck = _deck(tmp_path, {
        "cover": CLEAN,
        "away": _slide("Away", "<script>\nlocation.href = 'https://example.com/';\n</script>"),
        "after": CLEAN,
    })
    started = time.monotonic()
    result = api.refresh_html(deck, measure_slides=["cover", "away", "after"])
    assert time.monotonic() - started < 20
    assert result["browser_check"]["status"] == "navigated", result["browser_check"]
    assert result["browser_check"]["blocked_requests"] >= 1  # the https navigation was failed
    assert any(w.startswith("output.html: Browser check stopped:") for w in result["warnings"])
    assert result["preview"]["reason"] == "browser-navigated"


@real_browser
def test_real_browser_loads_a_deck_over_10_mb(tmp_path: Path, use_browser) -> None:
    from PIL import Image

    deck = _deck(tmp_path, {"big": _slide("Big", f'<img src="images/noise.png" alt="noise" '
                                                 f'style="{_box(96, 400, 600, 400)}">')})
    (deck / "images").mkdir(exist_ok=True)
    Image.frombytes("RGB", (2000, 1400), os.urandom(2000 * 1400 * 3)).save(deck / "images" / "noise.png")
    result = api.refresh_html(deck, measure_slides=["big"])
    assert result["html_bytes"] > browser_check.DIRECT_LIMIT
    assert result["browser_check"]["status"] == "ok", result
    assert _png_size(result["preview_files"][0]) == (1280, 720)


@real_browser
@pytest.mark.skipif(sys.platform not in ("darwin", "linux") or shutil.which("lsof") is None,
                    reason="needs lsof")
def test_real_browser_devtools_listens_on_loopback_only(tmp_path: Path, use_browser, monkeypatch) -> None:
    listening: list[str] = []
    executable = find_browser()

    @contextlib.contextmanager
    def watched(width, height):
        with browser.local_browser(executable, width, height) as endpoint:
            port = re.search(r":(\d+)/", endpoint.url).group(1)
            pids = subprocess.run(["lsof", "-t", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                                  capture_output=True, text=True, check=False).stdout.split()
            assert pids, "the DevTools port is not listening"
            for pid in pids:
                out = subprocess.run(["lsof", "-nP", "-a", "-p", pid, "-iTCP", "-sTCP:LISTEN", "-Fn"],
                                     capture_output=True, text=True, check=False).stdout
                listening.extend(line[1:] for line in out.splitlines() if line.startswith("n"))
            yield endpoint

    monkeypatch.setattr(browser, "_registered", watched)
    deck = _deck(tmp_path, {"clean": CLEAN})
    result = api.refresh_html(deck, measure_slides=["clean"])
    assert result["browser_check"]["status"] == "ok", result
    assert listening and all(name.startswith("127.0.0.1:") for name in listening), listening
