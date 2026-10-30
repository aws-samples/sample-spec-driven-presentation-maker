# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Headless Chrome / Edge JS check for HTML decks (sdpm.engine.html.jscheck, design §8.5).

The real-browser tests are opt-in: ``SDPM_TEST_BROWSER=1`` (and Chrome or Edge installed;
``SDPM_BROWSER`` picks one). Everything else uses a fake browser or none.
"""

from __future__ import annotations

import http.server
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from sdpm import api
from sdpm.engine.html import jscheck
from sdpm.engine.html.jscheck import (
    DISABLED_NOTE,
    NAVIGATED_NOTE,
    SKIPPED_NOTE,
    attribute,
    check_js,
    find_browser,
    js_check_enabled,
    parse_console_log,
)

_SRC = "file:///d/output.html"
CANNED_LOG = (
    "[1:2:1030/120000.100000:INFO:CONSOLE:98] \"sdpm slide s1: ReferenceError: x is not defined\n"
    f"    at section ({_SRC}:121:1)\", source: {_SRC} (98)\n"
    "[1:2:1030/120000.200000:INFO:CONSOLE(0)] \"Refused to load the script 'https://example.com/x.js' "
    "because it violates the following Content Security Policy directive: \"script-src 'sha256-AAA' "
    f"'sha256-BBB' 'self'\".\", source: {_SRC} (0)\n"
    f"[1:2:1030/120000.300000:INFO:CONSOLE:5] \"hello\", source: {_SRC} (5)\n"
    f"[1:2:1030/120000.400000:INFO:CONSOLE:7] \"Uncaught TypeError: a is null\", source: {_SRC} (7)\n"
    f"[1:2:1030/120000.500000:INFO:CONSOLE:98] \"sdpm-check:done\", source: {_SRC} (98)\n"
    f"[1:2:1030/120000.600000:INFO:CONSOLE:7] \"Uncaught TypeError: a is null\", source: {_SRC} (7)\n"
)


def test_parse_console_log() -> None:
    found = parse_console_log(CANNED_LOG)
    assert [line for line, _ in found] == [98, 0, 7]
    assert found[0][1].startswith("sdpm slide s1: ReferenceError")
    assert "script-src …" in found[1][1] and "sha256" not in found[1][1]
    assert found[2][1] == "Uncaught TypeError: a is null"


def test_parse_console_log_truncates_long_messages() -> None:
    log = f"[1:2:3:INFO:CONSOLE:1] \"Uncaught {'x' * 1000}\", source: {_SRC} (1)\n"
    assert len(parse_console_log(log)[0][1]) == 400


def test_attribute() -> None:
    line_map = [(10, 20, "s1"), (21, 30, "s2"), (40, 42, "s1")]
    assert [attribute(n, line_map) for n in (10, 20, 25, 41, 35, 0)] == ["s1", "s1", "s2", "s1", None, None]


def test_find_browser_honours_sdpm_browser(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "chrome"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("SDPM_BROWSER", "none")
    assert find_browser() is None
    monkeypatch.setenv("SDPM_BROWSER", str(exe))
    assert find_browser() == str(exe)
    monkeypatch.setenv("SDPM_BROWSER", str(tmp_path / "missing"))
    assert find_browser() is None


@pytest.mark.parametrize("value, enabled", [("0", False), ("false", False), ("OFF", False),
                                            ("1", True), ("", True)])
def test_js_check_enabled(monkeypatch, value: str, enabled: bool) -> None:
    monkeypatch.setenv("SDPM_JS_CHECK", value)
    assert js_check_enabled() is enabled


def test_check_js_skipped_without_a_browser(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SDPM_JS_CHECK", "1")
    monkeypatch.setattr(jscheck, "find_browser", lambda: None)
    result = check_js(tmp_path / "output.html", [])
    assert result == {"status": "skipped", "errors": [], "note": SKIPPED_NOTE}


def test_check_js_skipped_when_turned_off(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(jscheck, "find_browser", lambda: pytest.fail("browser looked up"))
    result = check_js(tmp_path / "output.html", [])
    assert result == {"status": "skipped", "errors": [], "note": DISABLED_NOTE}


def test_check_js_temp_profile_failure_is_reported(monkeypatch, tmp_path: Path) -> None:
    """An unwritable temp directory degrades to a note; check_js never raises."""
    monkeypatch.setenv("SDPM_JS_CHECK", "1")
    monkeypatch.setattr(jscheck, "find_browser", lambda: "/opt/chrome")

    def no_space(**_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(jscheck.tempfile, "mkdtemp", no_space)
    monkeypatch.setattr(jscheck.subprocess, "Popen", lambda *a, **k: pytest.fail("browser started"))
    result = check_js(tmp_path / "output.html", [])
    assert result["status"] == "failed" and result["errors"] == []
    assert "No space left on device" in result["note"]


# ── fake browser (POSIX) ─────────────────────────────────────────────────

_FAKE = '''\
import os, sys, time
from urllib.parse import urlparse
from urllib.request import url2pathname

args = sys.argv[1:]
opt = lambda name: next(a.split("=", 1)[1] for a in args if a.startswith(name + "="))
url = args[-1]
line = 1
for i, text in enumerate(open(url2pathname(urlparse(url).path), encoding="utf-8"), 1):
    if '__sdpmSlide("s1"' in text:
        line = i
        break
with open(os.environ["FAKE_RECORD"], "w", encoding="utf-8") as f:
    f.write("\\n".join([str(os.getpid()), opt("--user-data-dir"), *args]))
last = "sdpm-check:navigated" if os.environ.get("FAKE_MODE") == "navigate" else "sdpm-check:done"
with open(opt("--log-file"), "a", encoding="utf-8") as f:
    f.write(f'[1:1:0101/000000.000000:INFO:CONSOLE:{line}] "Uncaught Error: boom", source: {url} ({line})\\n')
    f.write(f'[1:1:0101/000000.000001:INFO:CONSOLE:{line}] "{last}", source: {url} ({line})\\n')
time.sleep(30)
'''

posix_only = pytest.mark.skipif(os.name == "nt", reason="the fake browser is a shell script")


@pytest.fixture
def fake_browser(tmp_path: Path, monkeypatch) -> Path:
    """A browser stand-in that logs one error in s1's script and the done line (the
    navigated line with ``FAKE_MODE=navigate``), then hangs."""
    script = tmp_path / "fake_browser.py"
    script.write_text(_FAKE, encoding="utf-8")
    exe = tmp_path / "fake-chrome"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    exe.chmod(0o755)
    record = tmp_path / "record.txt"
    monkeypatch.setenv("SDPM_BROWSER", str(exe))
    monkeypatch.setenv("FAKE_RECORD", str(record))
    return record


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


@posix_only
def test_check_js_with_a_fake_browser(fake_browser: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDPM_JS_CHECK", "1")
    page = tmp_path / "output.html"
    page.write_text('<html>\n<body>\n<script>__sdpmSlide("s1",function(section){\nboom();\n});</script>\n',
                    encoding="utf-8")
    started = time.monotonic()
    result = check_js(page, [(3, 5, "s1")])
    assert time.monotonic() - started < 10
    assert result["status"] == "errors"
    assert result["errors"] == [{"slug": "s1", "line": 3, "message": "Uncaught Error: boom"}]
    pid, profile, *argv = fake_browser.read_text(encoding="utf-8").splitlines()
    assert _gone(int(pid))
    assert not Path(profile).exists()
    assert argv[-1] == page.resolve().as_uri() + "#print-pdf&sdpm-check"
    for flag in ("--headless", "--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>",
                 "--host-resolver-rules=MAP * ~NOTFOUND", "--enable-logging", "--v=0"):
        assert flag in argv
    assert not any(a.startswith("--remote-debugging") for a in argv)


@posix_only
def test_check_js_stops_when_the_page_navigates(fake_browser: Path, tmp_path: Path, monkeypatch) -> None:
    """A slide that navigates away never logs the done line: stop at the navigated line
    instead of waiting for the timeout."""
    monkeypatch.setenv("SDPM_JS_CHECK", "1")
    monkeypatch.setenv("FAKE_MODE", "navigate")
    page = tmp_path / "output.html"
    page.write_text('<script>__sdpmSlide("s1",function(section){\nlocation.href="x";\n});</script>\n',
                    encoding="utf-8")
    started = time.monotonic()
    result = check_js(page, [(1, 3, "s1")], timeout=15)
    assert time.monotonic() - started < 10
    assert result["status"] == "navigated"
    assert result["note"].startswith(NAVIGATED_NOTE)
    assert result["errors"] == [{"slug": "s1", "line": 1, "message": "Uncaught Error: boom"}]
    pid = int(fake_browser.read_text(encoding="utf-8").splitlines()[0])
    assert _gone(pid)


# ── generate_html wiring ─────────────────────────────────────────────────

def _deck(tmp_path: Path, slides: dict[str, str]) -> Path:
    deck = tmp_path / "deck"
    api.init("t", output_dir=deck, output_format="html")
    assert api.apply_style(deck, style="typographic", template="blank-light")["status"] == "ok"
    outline = "# JS deck\n\n" + "".join(f"- [{slug}] {slug}\n" for slug in slides)
    (deck / "specs" / "outline.md").write_text(outline, encoding="utf-8")
    for slug, text in slides.items():
        (deck / "slides" / f"{slug}.html").write_text(text, encoding="utf-8")
    return deck


def _slide(title: str, body: str = "", attrs: str = "") -> str:
    return f'<section data-layout="Title Only"{attrs}><h1 data-ph="title">{title}</h1>{body}</section>'


JS_SLIDES = {
    "cover": _slide("Cover"),
    "s1": _slide("S1", "<script>boom();</script>"),
}


@posix_only
def test_generate_html_reports_js_errors(fake_browser: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDPM_JS_CHECK", "1")
    deck = _deck(tmp_path, JS_SLIDES)
    result = api.generate_html(deck)
    assert result["js_check"]["status"] == "errors"
    assert set(result["js_check"]) == {"status", "browser", "seconds"}
    assert "s1: JS error: Uncaught Error: boom" in result["warnings"]

    refreshed = api.refresh_html(deck, measure_slides=["cover"])
    assert refreshed["js_check"]["status"] == "errors"
    assert not any("JS error" in w for w in refreshed["warnings"])
    refreshed = api.refresh_html(deck, measure_slides=["s1"])
    assert "s1: JS error: Uncaught Error: boom" in refreshed["warnings"]


@posix_only
def test_generate_html_warns_when_a_slide_navigates(fake_browser: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDPM_JS_CHECK", "1")
    monkeypatch.setenv("FAKE_MODE", "navigate")
    deck = _deck(tmp_path, JS_SLIDES)
    result = api.generate_html(deck)
    assert result["js_check"]["status"] == "navigated"
    assert f"output.html: {result['js_check']['note']}" in result["warnings"]


def test_generate_html_without_a_browser(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDPM_JS_CHECK", "1")
    monkeypatch.setenv("SDPM_BROWSER", "none")
    deck = _deck(tmp_path, JS_SLIDES)
    result = api.generate_html(deck)
    assert (deck / "output.html").is_file()
    assert result["js_check"] == {"status": "skipped", "note": SKIPPED_NOTE}
    assert f"output.html: {SKIPPED_NOTE}" in result["warnings"]


def test_non_js_deck_launches_no_browser(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDPM_JS_CHECK", "1")
    monkeypatch.setattr(jscheck, "find_browser", lambda: pytest.fail("browser looked up"))
    deck = _deck(tmp_path, {"cover": _slide("Cover")})
    assert "js_check" not in api.generate_html(deck)
    assert "js_check" not in api.refresh_html(deck, measure_slides=["cover"])


def test_js_check_off_launches_no_browser(tmp_path: Path, monkeypatch) -> None:
    """SDPM_JS_CHECK=0 (the cloud runtime image) runs no browser but still says, among the
    warnings, that the scripts were not checked, so the agent cannot read it as clean."""
    monkeypatch.setattr(jscheck, "find_browser", lambda: pytest.fail("browser looked up"))
    deck = _deck(tmp_path, JS_SLIDES)
    result = api.generate_html(deck)
    assert result["js_check"] == {"status": "skipped", "note": DISABLED_NOTE}
    assert f"output.html: {DISABLED_NOTE}" in result["warnings"]
    refreshed = api.refresh_html(deck, measure_slides=["cover"])
    assert f"output.html: {DISABLED_NOTE}" in refreshed["warnings"]


# ── real browser (opt-in) ────────────────────────────────────────────────

real_browser = pytest.mark.skipif(
    os.environ.get("SDPM_TEST_BROWSER") != "1" or find_browser() is None,
    reason="real-browser JS check: set SDPM_TEST_BROWSER=1 with Chrome or Edge installed")

CHART = (
    "<div class=\"c\" style=\"position:absolute;left:96px;top:220px;width:1000px;height:600px\"></div>"
    "<script>\n"
    "var chart = echarts.init(section.querySelector('.c'));\n"
    "chart.setOption({animation: !Reveal.isPrintView(), xAxis: {type: 'category', data: ['A', 'B']},"
    " yAxis: {type: 'value'}, series: [{type: 'bar', data: [3, 5]}]});\n"
    "</script>"
)
BARS = (
    "<svg class=\"v\" style=\"position:absolute;left:96px;top:220px;width:1000px;height:600px\"></svg>"
    "<script>\n"
    "var svg = d3.select(section.querySelector('.v'));\n"
    "var rows = d3.csvParseRows('A,5\\nB,20', function(r){return {k: r[0], v: +r[1]};});\n"
    "svg.selectAll('rect').data(rows).join('rect').attr('x', function(d, i){return i * 120;})"
    ".attr('y', 0).attr('width', 100).attr('height', function(d){return d.v * 10;});\n"
    "</script>"
)


@real_browser
def test_real_browser_clean_deck(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDPM_JS_CHECK", "1")
    deck = _deck(tmp_path, {
        "cover": _slide("Cover"),
        "chart": _slide("Chart", CHART, ' data-libs="echarts"'),
        "bars": _slide("Bars", BARS, ' data-libs="d3"'),
        "steps": _slide("Steps", CHART + '<p class="fragment">one</p>', ' data-libs="echarts"'),
    })
    result = api.generate_html(deck)
    assert result["js_check"]["status"] == "ok", result["warnings"]
    assert not any("JS error" in w for w in result["warnings"])


@real_browser
def test_real_browser_reports_errors_per_slide(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDPM_JS_CHECK", "1")
    deck = _deck(tmp_path, {
        "fine": _slide("Fine", CHART, ' data-libs="echarts"'),
        "throws": _slide("Throws", "<script>\nnotDefinedFunction();\n</script>"),
        "csv": _slide("CSV", "<script>\nvar rows = d3.csvParse('a,b\\n1,2');\n</script>", ' data-libs="d3"'),
        "srcjs": _slide("Src", '<script src="https://example.com/x.js"></script>'),
        "onerr": _slide("Handler", '<img src="data:image/png;base64,AAAA" onerror="window.__e=1" alt="x">'),
        "beacon": _slide("Beacon", "<script>\nfetch('https://example.com/beacon').catch(function(){});\n</script>"),
    })
    result = api.generate_html(deck)
    assert result["js_check"]["status"] == "errors"
    js = [w for w in result["warnings"] if "JS error" in w]
    by_slug = {slug for slug in ("fine", "throws", "csv", "srcjs", "onerr", "beacon")
               if any(w.startswith(f"{slug}: JS error:") for w in js)}
    assert {"throws", "csv", "beacon"} <= by_slug, js
    assert "fine" not in by_slug, js
    assert any("example.com/x.js" in w for w in js), js
    assert any("inline event handler" in w for w in js), js


@real_browser
def test_real_browser_has_no_network(tmp_path: Path, monkeypatch) -> None:
    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — http.server API
            hits.append(self.path)
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        deck = _deck(tmp_path, {
            "cover": _slide("Cover"),
            "leak": _slide("Leak", "<script>\n"
                           f"window.open('{base}/open');\n"
                           f"setTimeout(function(){{location.href = '{base}/leak';}}, 200);\n"
                           "</script>"),
        })
        api.generate_html(deck)  # SDPM_JS_CHECK=0 (autouse): build only
        monkeypatch.setenv("SDPM_JS_CHECK", "1")
        result = check_js(deck / "output.html", [], timeout=6)
        time.sleep(0.5)
    finally:
        server.shutdown()
        server.server_close()
    assert result["status"] in {"ok", "errors", "timeout", "navigated"}, result
    assert hits == []


@real_browser
def test_real_browser_stops_at_navigation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDPM_JS_CHECK", "1")
    deck = _deck(tmp_path, {
        "cover": _slide("Cover"),
        "away": _slide("Away", "<script>\nlocation.href = 'https://example.com/';\n</script>"),
    })
    started = time.monotonic()
    result = api.generate_html(deck)
    assert time.monotonic() - started < 10
    assert result["js_check"]["status"] == "navigated", result["js_check"]
    assert any(w.startswith("output.html: JS check stopped:") for w in result["warnings"])
