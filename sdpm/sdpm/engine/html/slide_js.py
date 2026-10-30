# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Slide scripts and vendored libraries for HTML decks (design §8.2, §8.3).

A slide may carry inline classic ``<script>`` elements (no ``src``; ``type`` absent,
``text/javascript`` or ``application/javascript``). The assembler moves each one out
of its ``<section>`` and emits it after the notes plugin as
``__sdpmSlide("<slug>",function(section){ … });`` (``wrap_slide_script``), so the code
only registers a function while the page parses.

``SLIDE_HELPER`` defines ``__sdpmSlide`` and runs each slide's functions once per
``<section>`` element, with ``this`` and the ``section`` argument both set to that
element, the first time the slide is laid out:

* ``ready`` — the current slide (not in the print view);
* ``slidechanged`` — the slide just shown;
* ``overviewshown`` — every slide the overview lays out (``offsetWidth > 0``);
* ``pdf-ready`` — every ``section[data-slug]`` of the print view (fragment clones included).

When the URL fragment carries ``sdpm-check`` (the browser check), ``Reveal.isPrintView()``
returns true while a slide function runs, so slides that follow the print-view rule draw
their final state at once (no entry animation in the PNG), the helper logs
``sdpm-check:navigated`` on ``pagehide``, so the check stops at once when a slide script
navigates the page away, and ``__sdpmCheckRun()`` runs the current slide's functions if
no event has: on the check's ``about:blank`` / ``blob:`` page reveal.js's ``replaceState``
throws during start-up, so ``ready`` never fires and the first slide would go unchecked.

An exception is caught and logged as ``console.error('sdpm slide <slug>: <stack>')`` so
one broken slide does not stop the others.

Libraries a slide names in ``<section data-libs="echarts d3">`` (``LIBRARIES``) are
embedded once per deck, in ``LIBRARIES`` order, each preceded by a ``/*! … */`` comment
holding its license files (``library_script``). Paths are relative to
``sdpm.config.VENDOR_DIR``.
"""

from __future__ import annotations

import json

# name -> (library script, license / notice files…), in embedding order.
LIBRARIES: dict[str, tuple[str, ...]] = {
    "echarts": ("echarts/echarts.min.js", "echarts/LICENSE", "echarts/NOTICE",
                "echarts/licenses/LICENSE-d3"),
    "d3": ("d3/d3.min.js", "d3/LICENSE"),
}
# The global each library defines.
LIBRARY_GLOBALS: dict[str, str] = {"echarts": "echarts", "d3": "d3"}

_CLASSIC_TYPES = frozenset({"", "text/javascript", "application/javascript"})

SLIDE_HELPER = r"""(function(){
var fns={};
var check=/(^#|&)sdpm-check(&|$)/.test(location.hash);
window.__sdpmSlide=function(slug,fn){(fns[slug]=fns[slug]||[]).push(fn);};
function fail(slug,e){console.error('sdpm slide '+slug+': '+(e&&e.stack||e));}
function call(section,fn){if(!check)return fn.call(section,section);var p=Reveal.isPrintView;Reveal.isPrintView=function(){return true;};try{return fn.call(section,section);}finally{Reveal.isPrintView=p;}}
function run(section){
 if(!section||section.__sdpmRan)return;
 section.__sdpmRan=true;
 (fns[section.getAttribute('data-slug')]||[]).forEach(function(fn){try{call(section,fn);}catch(e){fail(section.getAttribute('data-slug'),e);}});
}
if(check){window.addEventListener('pagehide',function(){console.info('sdpm-check:navigated');});
 window.__sdpmCheckRun=function(){run(Reveal.getCurrentSlide());};}
Reveal.on('ready',function(e){if(!Reveal.isPrintView())run(e.currentSlide);});
Reveal.on('slidechanged',function(e){run(e.currentSlide);});
Reveal.on('overviewshown',function(){document.querySelectorAll('.reveal .slides section[data-slug]').forEach(function(s){if(s.offsetWidth)run(s);});});
Reveal.on('pdf-ready',function(){document.querySelectorAll('.reveal .slides section[data-slug]').forEach(run);});
})();"""


def declared_libraries(section) -> list[str]:
    """Known library names in the section's ``data-libs`` (lower-cased, deduplicated, in order)."""
    names: list[str] = []
    for name in (section.get("data-libs") or "").lower().split():
        if name in LIBRARIES and name not in names:
            names.append(name)
    return names


def is_slide_script(el) -> bool:
    """True for an inline classic script (the kind the assembler wraps and runs)."""
    if el.tag != "script" or el.get("src") is not None:
        return False
    return (el.get("type") or "").strip().lower() in _CLASSIC_TYPES


def wrap_slide_script(slug: str, code: str) -> str:
    """The registration call emitted for one slide script (before ``inline_js``)."""
    return f"__sdpmSlide({json.dumps(slug)},function(section){{\n{code}\n}});"


def library_script(name: str) -> str:
    """The library's license comment followed by its vendored text (read at call time)."""
    from sdpm.config import VENDOR_DIR

    script, *notices = LIBRARIES[name]
    texts = [(VENDOR_DIR / path).read_text(encoding="utf-8").strip() for path in notices]
    for path, text in zip(notices, texts):
        if "*/" in text:
            raise ValueError(f"{path} contains '*/' and cannot go in a comment")
    notice = "\n\n".join(texts)
    return f"/*!\n{notice}\n*/\n" + (VENDOR_DIR / script).read_text(encoding="utf-8")


__all__ = ["LIBRARIES", "LIBRARY_GLOBALS", "SLIDE_HELPER", "declared_libraries", "is_slide_script",
           "library_script", "wrap_slide_script"]
