# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Content-Security-Policy for HTML decks.

``output.html`` carries a ``<meta http-equiv="Content-Security-Policy">`` right after
``<meta charset>``: scripts run only when their sha256 is listed (the engine scripts,
the libraries the slides declare, the slide helper and each wrapped slide script, all
emitted by the assembler, plus the speaker view the notes plugin ``document.write()``s
into its popup, which inherits the policy), styles stay inline, every other resource is
``data:`` only (``connect-src 'none'``), and ``frame-src 'self'`` lets the speaker view
load the deck itself as its current / next slide frames. The static per-slide previews
run no script at all.
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Iterable

_WRITE_OPEN = ".document.write(`"
_SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
_ESCAPE_RE = re.compile(r"\\(x[0-9A-Fa-f]{2}|u\{[0-9A-Fa-f]+\}|u[0-9A-Fa-f]{4}|\r\n|[\s\S])")
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def script_hash(text: str) -> str:
    """CSP hash source (without quotes) of an inline script's text: ``sha256-<base64>``.

    Line breaks are normalised to LF first, as the HTML parser does before the
    browser hashes the element's content.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def _cook(raw: str) -> str:
    """Runtime value of a JS template-literal body that has no ``${…}`` substitution."""

    def repl(m: re.Match) -> str:
        esc = m.group(1)
        if len(esc) > 1 and esc[0] == "x":
            return chr(int(esc[1:], 16))
        if len(esc) > 1 and esc[0] == "u":
            return chr(int(esc[2:-1] if esc[1] == "{" else esc[1:], 16))
        if esc in _SIMPLE_ESCAPES:
            return _SIMPLE_ESCAPES[esc]
        if esc in ("\n", "\r", "\r\n", "\u2028", "\u2029"):  # line continuation
            return ""
        return esc  # \\ \/ \` \$ and every other identity escape

    return _ESCAPE_RE.sub(repl, raw)


def speaker_view_script(notes_js: str) -> str:
    """Body of the one ``<script>`` in the speaker view that reveal.js' notes plugin writes.

    The plugin opens ``about:blank`` and ``document.write()``s a template literal; the
    popup inherits the deck's CSP, so its script needs a hash in ``script-src``.

    Raises:
        ValueError: notes.js does not have the expected shape (exactly one
            ``.document.write(`` template literal, no ``${`` in it, exactly one
            ``<script>`` in its value).
    """
    if notes_js.count(_WRITE_OPEN) != 1:
        raise ValueError(f"notes.js: expected exactly one {_WRITE_OPEN!r}, "
                         f"found {notes_js.count(_WRITE_OPEN)}")
    start = notes_js.index(_WRITE_OPEN) + len(_WRITE_OPEN)
    i, n = start, len(notes_js)
    while i < n and notes_js[i] != "`":
        i += 2 if notes_js[i] == "\\" else 1
    if i >= n:
        raise ValueError("notes.js: the speaker-view template literal is not closed")
    raw = notes_js[start:i]
    if "${" in raw:
        raise ValueError("notes.js: the speaker-view template literal has a ${…} substitution")
    scripts = _SCRIPT_RE.findall(_cook(raw))
    if len(scripts) != 1:
        raise ValueError(f"notes.js: expected exactly one <script> in the speaker view, found {len(scripts)}")
    return scripts[0]


def _policy(script_src: str, frame_src: str) -> str:
    return "; ".join([
        "default-src 'none'",
        f"script-src {script_src}",
        "style-src 'unsafe-inline'",
        "img-src data:",
        "font-src data:",
        "media-src data:",
        "connect-src 'none'",
        f"frame-src {frame_src}",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    ])


def deck_csp(hashes: Iterable[str]) -> str:
    """The ``output.html`` policy; ``hashes`` are ``script_hash`` results (unquoted)."""
    sources = [f"'{h}'" for h in dict.fromkeys(hashes)]
    if not sources or any(not h.startswith("'sha256-") for h in sources):
        raise ValueError("deck_csp needs sha256 hash sources")
    return _policy(" ".join(sources), "'self'")


# Static per-slide previews (preview/<slug>.html): no script, no frames.
PREVIEW_CSP = _policy("'none'", "'none'")


def csp_meta(policy: str) -> str:
    """``<meta http-equiv="Content-Security-Policy">`` element for ``policy``."""
    return f'<meta http-equiv="Content-Security-Policy" content="{policy}">'


REFERRER_META = '<meta name="referrer" content="no-referrer">'


__all__ = ["PREVIEW_CSP", "REFERRER_META", "csp_meta", "deck_csp", "script_hash", "speaker_view_script"]
