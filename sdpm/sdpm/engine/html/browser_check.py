# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Browser check for HTML decks: load, render, measure, JS errors, PNG (design §9).

``check_deck`` opens the built ``output.html`` in a browser from
``sdpm.engine.html.browser.resolve_browser`` (local headless Chrome / Edge, or the source
an adapter registered) over the DevTools protocol (``sdpm.engine.html.cdp``):

1. attach to the page; enable Page / Runtime / Log; block http(s) / ws(s) requests (if
   the browser rejects the block, the check fails before the deck loads) and close pages
   the deck opens;
   set the viewport to the deck size;
2. load the deck: up to ``DIRECT_LIMIT`` UTF-8 bytes with ``Page.setDocumentContent`` on
   ``about:blank#sdpm-check``, larger in chunks into a ``blob:`` URL (CDP drops messages
   around 10–12 MB); wait for ``Reveal.isReady()``; turn margins, controls, transitions
   and the URL hash off;
3. per requested slug, in deck order: ``Reveal.slide(i, 0, 999)`` (every fragment
   shown), settle (1 frame → ``finish()`` every running animation → 2 frames; the slide
   helper makes ``Reveal.isPrintView()`` true while slide code runs under
   ``#sdpm-check``), measure the placeholders, regions and blocks
   (``layout_judge.judge_slide``), and capture a PNG 1280 px on the long edge;
4. collect JS errors (``errors_from_events``): uncaught exceptions of the page, the slide
   helper's ``sdpm slide <slug>: …`` console errors, CSP violations.

A slide that navigates the page away stops the check (``navigated``); the whole check has
a deadline (``min(30 + 3 × slides, 110)`` s, below AgentCore Browser's 120 s session).
``check_deck`` never raises; every status but ``ok`` / ``issues`` carries a ``note``.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sdpm.engine.html.browser import resolve_browser
from sdpm.engine.html.cdp import CdpConnection, CdpError, CdpTimeout
from sdpm.engine.html.layout_judge import judge_slide

logger = logging.getLogger(__name__)

DIRECT_LIMIT = 10_000_000  # UTF-8 bytes loaded with Page.setDocumentContent
CHUNK = 2_000_000  # characters per blob chunk
READY_TIMEOUT = 30.0
PNG_LONG_EDGE = 1280
NAVIGATED_MARK = "sdpm-check:navigated"
_MAX_MESSAGE = 400
_BLOCKED = ["http://*", "https://*", "ws://*", "wss://*"]
_HELPER_SLUG_RE = re.compile(r"sdpm slide (\S+?): ")
_HASHES_RE = re.compile(r"script-src(?: 'sha256-[^']+')+")
_CSP_HINTS = ("Content Security Policy", "Refused to")

RAF1 = "new Promise(function(r){requestAnimationFrame(function(){r(1);});})"
RAF2 = "new Promise(function(r){requestAnimationFrame(function(){requestAnimationFrame(function(){r(1);});});})"
FINISH = ("(function(){var n=0;document.getAnimations().forEach(function(a){try{a.finish();n++;}catch(e){}});"
          "return n;})()")
CONFIGURE = "Reveal.configure({margin:0,controls:false,progress:false,transition:'none',hash:false})"
SLUGS = "Array.prototype.map.call(Reveal.getSlides(),function(s){return s.getAttribute('data-slug');})"

MEASURE = r"""(function(){
var s=Reveal.getCurrentSlide();if(!s)return null;
var r0=s.getBoundingClientRect();var f=r0.width?s.offsetWidth/r0.width:1;
var out=[],idx=new Map();
function skip(el){return el.matches('aside.notes,script,style,[data-sdpm-chrome]')||!!el.closest('[data-sdpm-chrome]');}
function text(el){var t=(el.textContent||'').replace(/\s+/g,' ').trim();return t.length>24?t.slice(0,24)+'…':t;}
function label(el,kind){
 if(kind==='ph')return 'data-ph="'+el.getAttribute('data-ph')+'"';
 if(kind==='region')return 'data-region="'+el.getAttribute('data-region')+'"';
 var tag='<'+el.tagName.toLowerCase()+'>',t=text(el);
 if(t)return tag+' "'+t+'"';
 var c=(el.getAttribute('class')||'').trim().split(/\s+/)[0];
 return c?'<'+el.tagName.toLowerCase()+' class="'+c+'">':tag;}
function regionOf(el){var p=el.parentElement&&el.parentElement.closest('[data-region]');
 return p&&s.contains(p)&&idx.has(p)?idx.get(p):undefined;}
function add(el,kind,region){
 if(idx.has(el)||skip(el))return;
 if(getComputedStyle(el).display==='none')return;
 var r=el.getBoundingClientRect();if(!r.width||!r.height)return;
 var e={kind:kind,label:label(el,kind),box:[(r.left-r0.left)*f,(r.top-r0.top)*f,r.width*f,r.height*f],
  scroll:[el.scrollWidth,el.scrollHeight,el.clientWidth,el.clientHeight]};
 if(region!==undefined)e.region=region;
 idx.set(el,out.length);out.push(e);}
s.querySelectorAll('[data-region]').forEach(function(el){add(el,'region',regionOf(el));});
s.querySelectorAll('[data-ph]').forEach(function(el){add(el,'ph',regionOf(el));});
s.querySelectorAll('[data-region]').forEach(function(reg){if(!idx.has(reg))return;
 Array.prototype.forEach.call(reg.children,function(el){add(el,'child',idx.get(reg));});});
Array.prototype.forEach.call(s.children,function(el){add(el,'free');});
return {width:s.offsetWidth,height:s.offsetHeight,elements:out};
})()"""

_NOISE = (
    re.compile(r"replaceState.*SecurityError|SecurityError.*replaceState", re.DOTALL),
    re.compile(r"Extension context invalidated\."),
)


def deadline_for(slide_count: int) -> float:
    """The whole check's time budget in seconds."""
    return float(min(30 + 3 * slide_count, 110))


# ── JS errors (pure) ──────────────────────────────────────────────────────

def _slug_for_line(line: int | None, line_map) -> str | None:
    if line is None:
        return None
    for first, last, slug in line_map:
        if first <= line <= last:
            return slug
    return None


def _is_noise(message: str) -> bool:
    return any(p.search(message) for p in _NOISE)


def errors_from_events(events: Iterable[dict], line_map, main_contexts: set[int] | None,
                       current_slug: str | None, *, slugs: Iterable[str] | None = None) -> list[dict]:
    """JS errors of CDP events as diagnostics ``{slug, rule: "js-error", message, line?}``.

    Sources: main-world ``Runtime.exceptionThrown`` and helper console errors
    (``sdpm slide <slug>: …``) — ``main_contexts`` (None: any context) — and CSP violations
    from ``Log.entryAdded``. A slug comes from the helper prefix, else the line
    (``lineNumber + 1``) in ``line_map``, else ``current_slug``. With ``slugs``, errors of
    other slugs are dropped; unattributed ones are kept with slug None.
    """
    known = {slug for _, _, slug in line_map}
    wanted = set(slugs) if slugs is not None else None
    out: list[dict] = []

    def add(message: str, line: int | None) -> None:
        message = message.strip()
        if not message or _is_noise(message):
            return
        m = _HELPER_SLUG_RE.match(message)
        slug = m.group(1) if m and (m.group(1) in known or not known) else None
        slug = slug or _slug_for_line(line, line_map) or current_slug
        if wanted is not None and slug is not None and slug not in wanted:
            return
        diag: dict[str, Any] = {"slug": slug, "rule": "js-error",
                                "message": f"JS error: {_HASHES_RE.sub('script-src …', message)[:_MAX_MESSAGE]}"}
        if line is not None:
            diag["line"] = line
        if not any(d["slug"] == diag["slug"] and d["message"] == diag["message"] for d in out):
            out.append(diag)

    def in_main(context_id) -> bool:
        return main_contexts is None or context_id is None or context_id in main_contexts

    for event in events:
        method, params = event.get("method"), event.get("params") or {}
        if method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails") or {}
            if not in_main(details.get("executionContextId")):
                continue
            text = (details.get("exception") or {}).get("description") or details.get("text") or ""
            line = details.get("lineNumber")
            add(text, line + 1 if isinstance(line, int) else None)
        elif method == "Runtime.consoleAPICalled":
            if params.get("type") != "error" or not in_main(params.get("executionContextId")):
                continue
            args = params.get("args") or []
            text = str((args[0] if args else {}).get("value", ""))
            if not text.startswith("sdpm slide "):
                continue
            frames = (params.get("stackTrace") or {}).get("callFrames") or []
            line = frames[0].get("lineNumber") if frames else None
            add(text, line + 1 if isinstance(line, int) else None)
        elif method == "Log.entryAdded":
            entry = params.get("entry") or {}
            text = entry.get("text") or ""
            if entry.get("level") != "error" or not any(h in text for h in _CSP_HINTS):
                continue
            line = entry.get("lineNumber")
            add(text, line + 1 if isinstance(line, int) else None)
    return out


# ── the check ─────────────────────────────────────────────────────────────

class _Navigated(Exception):
    pass


class _Deadline(Exception):
    pass


class _Run:
    """State of one check: the connection, events, timings and results."""

    def __init__(self, slugs: Sequence[str], line_map, limit: float) -> None:
        self.slugs = list(slugs)
        self.line_map = line_map
        self.started = time.monotonic()
        self.limit = limit
        self.end = self.started + limit
        self.cdp: CdpConnection | None = None
        self.session: str | None = None
        self.target_id: str | None = None
        self.frame_id: str | None = None
        self.loaded = False
        self.current: str | None = None
        self.main_contexts: set[int] = set()
        self.errors: list[dict] = []
        self.checked: list[str] = []
        self.findings: dict[str, list[dict]] = {}
        self.pngs: dict[str, str] = {}
        self.timings: dict[str, float] = {}
        self.navigated_at: str | None = None
        self.network_blocked: bool | None = None

    # time
    def left(self) -> float:
        return self.end - time.monotonic()

    def budget(self, timeout: float) -> float:
        left = self.left()
        if left <= 0:
            raise _Deadline()
        return max(min(timeout, left), 0.1)

    # CDP with the deadline and event pumping
    def send(self, method: str, params: dict | None = None, *, page: bool = True, timeout: float = 15.0) -> dict:
        assert self.cdp is not None
        try:
            return self.cdp.send(method, params, session=self.session if page else None,
                                 timeout=self.budget(timeout))
        finally:
            self.pump()

    def js(self, expr: str, *, await_promise: bool = False, timeout: float = 15.0) -> Any:
        assert self.cdp is not None
        try:
            return self.cdp.evaluate(self.session, expr, await_promise=await_promise,
                                     timeout=self.budget(timeout))
        finally:
            self.pump()

    def is_navigation(self, event: dict) -> bool:
        """True for an event that says the deck page navigated away."""
        method, params = event.get("method"), event.get("params") or {}
        if event.get("sessionId") not in (None, self.session):
            return False
        if method == "Page.frameNavigated":
            frame = params.get("frame") or {}
            if frame.get("parentId") is None and (self.frame_id is None or frame.get("id") == self.frame_id):
                url = frame.get("url") or ""
                return self.loaded or not (url.startswith("blob:") or url.startswith("about:blank"))
        elif method == "Runtime.executionContextsCleared":
            return self.loaded
        elif method == "Runtime.consoleAPICalled":
            args = params.get("args") or []
            return bool(args) and args[0].get("value") == NAVIGATED_MARK
        return False

    def watch(self, event: dict) -> None:
        """``CdpConnection.on_event``: stop at once when the page navigates away."""
        if self.navigated_at is None and self.is_navigation(event):
            self.navigated_at = self.current or ""
            raise _Navigated()

    def pump(self) -> None:
        """Process events read so far: contexts, popups, navigation, JS errors."""
        if self.cdp is None:
            return
        events = self.cdp.take_events()
        if not events:
            return
        popups = []
        navigated = False
        for event in events:
            method, params = event.get("method"), event.get("params") or {}
            if event.get("sessionId") not in (None, self.session):
                continue
            navigated = navigated or self.is_navigation(event)
            if method == "Runtime.executionContextCreated":
                ctx = params.get("context") or {}
                aux = ctx.get("auxData") or {}
                if aux.get("isDefault") and (self.frame_id is None or aux.get("frameId") == self.frame_id):
                    self.main_contexts.add(ctx.get("id"))
            elif method == "Target.targetCreated":
                info = params.get("targetInfo") or {}
                if info.get("openerId") == self.target_id and info.get("targetId") != self.target_id:
                    popups.append(info.get("targetId"))
        self.errors.extend(e for e in errors_from_events(events, self.line_map, self.main_contexts or None,
                                                         self.current, slugs=self.slugs)
                           if not any(e["slug"] == d["slug"] and e["message"] == d["message"]
                                      for d in self.errors))
        for target in popups:
            try:
                self.cdp.send("Target.closeTarget", {"targetId": target}, timeout=5)
            except CdpError as exc:
                logger.info("browser check: could not close a page the deck opened: %s", exc)
        if navigated and self.navigated_at is None:
            self.navigated_at = self.current or ""
            raise _Navigated()


def _page_setup(run: _Run, width: int, height: int) -> None:
    targets = run.send("Target.getTargets", page=False)["targetInfos"]
    page = next(t for t in targets if t.get("type") == "page")
    run.target_id = page["targetId"]
    run.session = run.send("Target.attachToTarget", {"targetId": page["targetId"], "flatten": True},
                           page=False)["sessionId"]
    for domain in ("Page.enable", "Runtime.enable", "Log.enable"):
        run.send(domain)
    run.frame_id = run.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
    try:
        run.send("Target.setDiscoverTargets", {"discover": True}, page=False)
    except CdpError as exc:
        logger.info("browser check: target discovery unavailable: %s", exc)
    try:
        run.send("Network.enable")
        try:
            run.send("Network.setBlockedURLs", {"urls": _BLOCKED})
        except CdpError:
            run.send("Network.setBlockedURLs",
                     {"urlPatterns": [{"urlPattern": p, "block": True} for p in _BLOCKED]})
        run.network_blocked = True
    except CdpError as exc:
        # Fail closed: slide code never runs in a browser that may reach the network
        # (AgentCore Browser has internet access); the check fails with a note.
        run.network_blocked = False
        logger.warning("browser check: could not block network requests: %s", exc)
        raise RuntimeError(f"could not block network requests, so no slide was run ({exc})") from exc
    run.send("Emulation.setDeviceMetricsOverride",
             {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})


def _load(run: _Run, html: str) -> None:
    if len(html.encode("utf-8")) <= DIRECT_LIMIT:
        run.send("Page.navigate", {"url": "about:blank#sdpm-check"})
        time.sleep(0.1)
        run.send("Page.setDocumentContent", {"frameId": run.frame_id, "html": html}, timeout=60)
    else:
        run.send("Page.navigate", {"url": "about:blank"})
        time.sleep(0.1)
        run.js("window.__sdpmChunks=[];0")
        for i in range(0, len(html), CHUNK):
            run.js(f"window.__sdpmChunks.push({json.dumps(html[i:i + CHUNK], ensure_ascii=False)});0", timeout=60)
        run.js("location.href=URL.createObjectURL(new Blob(window.__sdpmChunks,"
               "{type:'text/html;charset=utf-8'}))+'#sdpm-check';0")
    ready_by = time.monotonic() + READY_TIMEOUT
    while True:
        try:
            if run.js("!!(window.Reveal&&Reveal.isReady&&Reveal.isReady())", timeout=5):
                break
        except CdpError:
            pass  # the document is being replaced
        if time.monotonic() > ready_by:
            raise CdpError(f"the deck did not become ready within {READY_TIMEOUT:g} s")
        time.sleep(0.05)
    run.loaded = True
    run.js(CONFIGURE + ";0")


def _slide(run: _Run, slug: str, index: int, *, width: int, height: int, decorations: list[dict],
           png_dir: Path | None) -> None:
    run.current = slug
    # __sdpmCheckRun: the slide shown first gets no ready / slidechanged event here.
    run.js(f"Reveal.slide({index},0,999);window.__sdpmCheckRun&&window.__sdpmCheckRun();0")
    run.js(RAF1, await_promise=True, timeout=10)
    run.js(FINISH)
    run.js(RAF2, await_promise=True, timeout=10)
    measured = run.js(MEASURE)
    findings = judge_slide(slug, measured or {}, decorations)
    if png_dir is not None:
        clip = {"x": 0, "y": 0, "width": width, "height": height, "scale": PNG_LONG_EDGE / max(width, height)}
        data = run.send("Page.captureScreenshot", {"format": "png", "clip": clip}, timeout=30)["data"]
        png_dir.mkdir(parents=True, exist_ok=True)
        path = png_dir / f"{slug}.png"
        path.write_bytes(base64.b64decode(data))
        run.pngs[slug] = str(path)
    run.checked.append(slug)
    if findings:
        run.findings[slug] = findings


def _rest_note(run: _Run) -> str:
    return (f"{len(run.checked)} of {len(run.slugs)} slide(s) checked; layout, JS errors and PNG "
            "previews of the rest are unknown")


def check_deck(
    output_html: str | Path,
    slugs: Sequence[str],
    *,
    slide_size: tuple[int, int],
    line_map,
    layouts: Mapping[str, str],
    decorations: Mapping[str, list[dict]],
    png_dir: str | Path | None = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Check ``slugs`` of a built deck in a browser. Never raises.

    Args:
        slide_size: canvas ``(width, height)`` in px (template.json ``slideSize``).
        line_map: the assembler's ``(first, last, slug)`` line ranges.
        layouts: slug → its ``data-layout``; decorations: layout → template decorations.
        png_dir: where ``<slug>.png`` goes (None: skip the PNG).
        deadline: the time budget in seconds (default ``deadline_for(len(slugs))``).

    Returns:
        ``{status, browser?, seconds?, slides, checked, findings: {slug: [diag]},
        errors: [diag], pngs: {slug: path}, timings?, network_blocked?, note?}``; status ``ok`` / ``issues``
        / ``skipped`` / ``navigated`` / ``timeout`` / ``failed``.
    """
    slugs = list(dict.fromkeys(slugs))
    base: dict[str, Any] = {"slides": 0, "checked": [], "findings": {}, "errors": [], "pngs": {}}
    source, skip_note = resolve_browser()
    if source is None:
        return {"status": "skipped", **base, "note": skip_note}
    width, height = int(slide_size[0]), int(slide_size[1])
    limit = float(deadline) if deadline is not None else deadline_for(len(slugs))
    run = _Run(slugs, line_map, limit)
    name = getattr(source, "browser_name", "browser")
    status, note = "ok", None
    png_path = Path(png_dir) if png_dir is not None else None
    released = None
    try:
        html = Path(output_html).read_text(encoding="utf-8")
        t0 = time.monotonic()
        with source(width, height) as endpoint:
            name = endpoint.name
            run.timings["acquire"] = round(time.monotonic() - t0, 3)
            try:
                t1 = time.monotonic()
                with CdpConnection(endpoint.url, endpoint.headers) as cdp:
                    run.cdp = cdp
                    cdp.on_event = run.watch
                    _page_setup(run, width, height)
                    run.timings["connect"] = round(time.monotonic() - t1, 3)
                    t2 = time.monotonic()
                    _load(run, html)
                    run.timings["load"] = round(time.monotonic() - t2, 3)
                    order = run.js(SLUGS) or []
                    index = {}
                    for i, slug in enumerate(order):
                        index.setdefault(slug, i)
                    t3 = time.monotonic()
                    for slug in sorted((s for s in slugs if s in index), key=index.get):
                        _slide(run, slug, index[slug], width=width, height=height,
                               decorations=decorations.get(layouts.get(slug, ""), []), png_dir=png_path)
                    run.current = None
                    time.sleep(0.1)
                    run.send("Runtime.evaluate", {"expression": "0"})  # read the last events
                    run.timings["slides"] = round(time.monotonic() - t3, 3)
            except _Navigated:
                status = "navigated"
                where = f" while {run.navigated_at} was shown" if run.navigated_at else ""
                note = (f"Browser check stopped: a slide script navigated the page away{where} (location, "
                        f"reload, form submit…); {_rest_note(run)}. Remove the navigation (see the "
                        "script-external warning).")
            except (_Deadline, CdpTimeout):
                status = "timeout"
                note = (f"Browser check did not finish within {limit:g} s; {_rest_note(run)}. A slide "
                        "script that never returns can cause this.")
            finally:
                run.cdp = None
                released = time.monotonic()
        run.timings["release"] = round(time.monotonic() - released, 3)
    except Exception as exc:  # acquisition / connection / CDP failure: reported, never raised
        status = "failed"
        note = (f"Browser check could not run ({name}): {type(exc).__name__}: {str(exc)[:300]}; "
                f"{_rest_note(run)}.")
        if released is not None:
            run.timings.setdefault("release", round(time.monotonic() - released, 3))
    if status == "ok" and (run.findings or run.errors):
        status = "issues"
    result: dict[str, Any] = {
        "status": status, "browser": name, "seconds": round(time.monotonic() - run.started, 1),
        "slides": len(run.checked), "checked": run.checked, "findings": run.findings,
        "errors": run.errors, "pngs": run.pngs, "timings": run.timings,
    }
    if run.network_blocked is not None:
        result["network_blocked"] = run.network_blocked
    if note:
        result["note"] = note
    return result


__all__ = ["CHUNK", "DIRECT_LIMIT", "PNG_LONG_EDGE", "check_deck", "deadline_for", "errors_from_events"]
