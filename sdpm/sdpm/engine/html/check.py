# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Static checks for HTML decks (slides/<slug>.html and deck.css), no browser needed.

Every check returns diagnostics ``{"slug", "rule", "message"}``; callers turn them
into warnings. Nothing here blocks a build. The browser check (layout, JS errors,
PNG) lives in ``sdpm.engine.html.browser_check``; ``format_check_report`` reports both.

Rules:
    structure               not exactly one top-level ``<section>``, or a nested one
    layout-missing          the section has no ``data-layout``
    layout-unknown          ``data-layout`` names no layout of the template
    script                  ``<script src>`` and non-classic ``<script type>`` (module,
                            JSON …; inline classic scripts are allowed and run),
                            ``on*`` attributes, ``javascript:`` URLs (also
                            one item of an SVG animation ``values`` list),
                            ``<iframe>`` / ``<object>`` / ``<embed>`` (an embedded document
                            the checks cannot see), ``<meta http-equiv>`` (``refresh``
                            navigates the deck, which no CSP directive stops); inline ``<svg>`` and its
                            ``<foreignObject>`` are checked like any other markup
                            (deck.css: ``javascript:``, ``expression()``, ``</style``)
    external-url            a resource-loading reference that is not ``data:``,
                            ``assets:<source>/<name>`` or a deck-relative path, in an
                            attribute, an attribute ``url()`` (SVG ``fill`` / ``filter`` …)
                            or CSS (``<a href>`` is allowed: it loads nothing); also
                            every ``@import`` and ``<link rel=stylesheet>`` (``data:``
                            included), which are not embedded and the CSP blocks
    external-use            ``<use href>`` that is not a ``#fragment`` (another document's
                            sprite, which the deck's CSP / the browser does not load)
    data-background         reveal.js ``data-background*`` attributes
    self-chrome             slide numbers / footers drawn by the slide (the assembler draws them)
    placeholder-unknown     a ``data-ph`` key (idx or alias) that the slide's layout does not
                            have (skipped for unknown layouts, chrome and self-chrome keys)
    root-in-slide-style     ``:root`` in a slide ``<style>`` (tokens come from the style)
    root-in-deck-css        ``:root`` in deck.css
    data-slug               ``data-slug`` set by the author (the assembler sets it)
    font-size-token         a font size that does not use a ``--fs-*`` token
    font-size-unknown-token a ``var(--fs-*)`` the style does not define
    script-external         a slide script uses ``location``, ``window.open`` / ``open(``,
                            ``top.`` or an external URL (``http(s)://`` other than an XML
                            namespace URI, ``"//host``); the
                            CSP blocks fetch but not navigation or new tabs
    library-unknown         a ``data-libs`` value that is not a bundled library
    library-undeclared      a slide script uses ``echarts.`` / ``d3.`` while the section's
                            ``data-libs`` does not name it
    script-eval             a slide script calls something that needs eval (``d3.csvParse``,
                            ``tsvParse``, ``dsvFormat(…).parse``, ``eval``, ``new Function``)
    script-dom              a slide script uses ``getElementById`` / ``querySelector('#…')``
                            or waits for ``DOMContentLoaded`` / ``load``

The slide-script rules scan the text of the slide's inline classic scripts with regular
expressions (no JS parser; comments and strings are scanned too). One diagnostic per
slide per rule.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Mapping

from sdpm.engine.checks.font_size import parse_allowed_font_sizes

DECK_CSS_SLUG = "(deck.css)"

_ROOT_RE = re.compile(r":root\s*\{(?P<body>.*?)\}", re.DOTALL | re.IGNORECASE)
_FS_NAME_RE = re.compile(r"--(fs-[\w-]+)\s*:")
_FS_VAR_RE = re.compile(r"var\(\s*--(fs-[\w-]+)")
_FONT_DECL_RE = re.compile(r"(?:^|(?<=[{;\s]))(font-size|font)\s*:\s*(?P<value>[^;{}]+)", re.IGNORECASE)
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_URL_RE = re.compile(r"url\(\s*(?P<q>['\"]?)(?P<url>.*?)(?P=q)\s*\)", re.IGNORECASE | re.DOTALL)
_CSS_IMPORT_RE = re.compile(
    r"@import\s+(?:url\(\s*)?(?P<q>['\"]?)(?P<url>[^'\")\s;]*)", re.IGNORECASE)
_IMAGE_SET_RE = re.compile(r"(?<![\w-])(?:-webkit-)?image-set\(", re.IGNORECASE)
_ROOT_SEL_RE = re.compile(r":root\b", re.IGNORECASE)
_SCHEME_RE = re.compile(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*):")
_CTRL_RE = re.compile(r"[\x00-\x20]+")
_CHROME_TOKEN_RE = re.compile(r"(?:page|slide)[-_]?(?:number|num|no)|pagenum|footer", re.IGNORECASE)

# Placeholder names a slide could use for template chrome (in addition to the
# template's dt / ftr / sldNum idx keys passed as ``chrome_keys``).
_CHROME_PH_NAMES = frozenset({"dt", "ftr", "sldnum", "date", "footer", "slide-number", "slidenumber"})
# Attributes that make the browser load something.
_RESOURCE_ATTRS = ("src", "poster", "data", "xlink:href")
# Attributes whose javascript: value runs script (SVG animation sets href via to/from/values).
_JS_URL_ATTRS = frozenset({"href", "xlink:href", "src", "action", "formaction", "data", "poster",
                           "to", "from", "values"})
# Elements that embed a whole document the static checks never see.
_EMBEDDING_TAGS = frozenset({"iframe", "frame", "object", "embed"})
# SVG animation elements (lower-cased by the HTML parser); ``values`` is a ``;`` list.
_SVG_ANIMATION_TAGS = frozenset({"animate", "set", "animatemotion", "animatetransform"})

# Slide-script patterns (design §8.4). Group "tok", when present, is the token reported.
_JS_EXTERNAL_RES = tuple(re.compile(p) for p in (
    r"\blocation\b",
    r"\bwindow\s*\.\s*open\b",
    r"(?<![\w$.])open\s*\(",
    r"(?<![\w$.])top\s*\.",
    # XML namespace URIs (createElementNS) are names, not requests.
    r"(?P<tok>https?://(?!www\.w3\.org/(?:2000/svg|1999/xhtml|1999/xlink|1998/Math/MathML|"
    r"XML/1998/namespace|2000/xmlns/)[\"'`])[^\s'\"`)]*)",
    r"[\"'`](?P<tok>//[A-Za-z0-9][^\s'\"`]*)",
))
_JS_EVAL_RES = tuple(re.compile(p) for p in (
    r"\b(?:csvParse|tsvParse)\s*\(",
    r"dsvFormat\s*\([^)]*\)\s*\.\s*parse\s*\(",
    r"\beval\s*\(",
    r"\bnew\s+Function\b",
))
_JS_DOM_RES = tuple(re.compile(p) for p in (
    r"getElementById",
    r"document\s*\.\s*querySelector(?:All)?\s*\(\s*[\"'`]#",
    r"DOMContentLoaded",
    r"addEventListener\s*\(\s*[\"'`]load[\"'`]",
    r"\bonload\s*=",
))


def _diag(slug: str, rule: str, message: str) -> dict:
    return {"slug": slug, "rule": rule, "message": message}


# ── URL classification ───────────────────────────────────────────────────

def url_kind(url: str) -> str:
    """``data`` | ``assets`` | ``fragment`` | ``relative`` | ``external`` | ``javascript``."""
    value = _CTRL_RE.sub("", url or "")
    if not value or value.startswith("#"):
        return "fragment"
    if value.startswith("//") or value.startswith("\\\\"):
        return "external"
    m = _SCHEME_RE.match(value)
    if not m:
        return "relative"
    scheme = m.group("scheme").lower()
    if scheme == "data":
        return "data"
    if scheme == "assets":
        return "assets"
    if scheme == "javascript":
        return "javascript"
    return "external"


def parse_srcset(value: str) -> list[tuple[str, str]]:
    """``(url, descriptors)`` candidates of a ``srcset`` (HTML candidate parsing:
    URLs run to whitespace, so the commas of a ``data:`` URL do not split it)."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(value or "")
    while i < n:
        while i < n and (value[i].isspace() or value[i] == ","):
            i += 1
        start = i
        while i < n and not value[i].isspace():
            i += 1
        url, descriptors = value[start:i], ""
        if url.endswith(","):
            url = url.rstrip(",")
        else:
            start = i
            while i < n and value[i] != ",":
                i += 1
            descriptors = value[start:i].strip()
        if url:
            out.append((url, descriptors))
    return out


def image_set_strings(css: str) -> list[tuple[int, int, str]]:
    """``(start, end, url)`` of the string image arguments of every ``image-set()``.

    ``start:end`` covers the quoted string; ``url()`` and ``type("…")`` arguments
    (one level deeper) are not included.
    """
    out: list[tuple[int, int, str]] = []
    n = len(css)
    for m in _IMAGE_SET_RE.finditer(css):
        i, depth = m.end(), 0
        while i < n:
            c = css[i]
            if c in "\"'":
                j = i + 1
                while j < n and css[j] != c:
                    j += 2 if css[j] == "\\" else 1
                if depth == 0:
                    out.append((i, min(j + 1, n), css[i + 1:j]))
                i = j + 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    break
                depth -= 1
            i += 1
    return out


def _css_url_diags(slug: str, css: str, where: str) -> list[dict]:
    out = []
    css = _CSS_COMMENT_RE.sub("", css)
    urls = [m.group("url") for m in _CSS_URL_RE.finditer(css)]
    urls += [url for _, _, url in image_set_strings(css)]
    for url in urls:
        kind = url_kind(url)
        if kind == "javascript":
            out.append(_diag(slug, "script", f"javascript: URL in {where}; remove it (behaviour goes in a "
                             "slide script)"))
        elif kind == "external":
            out.append(_diag(slug, "external-url",
                             f"{where} loads {url[:80]!r}; embed it (data:, assets:, or a deck file)"))
    for m in _CSS_IMPORT_RE.finditer(css):
        out.append(_diag(slug, "external-url",
                         f"@import {m.group('url')[:80]!r} in {where} is not embedded (the deck's CSP "
                         "blocks it); put shared rules in deck.css"))
    return out


# ── --fs-* token lint ────────────────────────────────────────────────────

def _style_token_names(art_direction_path: Path) -> set[str] | None:
    """``--fs-*`` names of the style :root, or None when the lint is skipped."""
    if not parse_allowed_font_sizes(art_direction_path):
        return None
    text = art_direction_path.read_text(encoding="utf-8")
    root = _ROOT_RE.search(text)
    body = root.group("body") if root else text
    return set(_FS_NAME_RE.findall(body))


def _font_diags(slug: str, css: str, names: set[str], where: str) -> list[dict]:
    out = []
    css = _CSS_COMMENT_RE.sub("", css)
    for m in _FONT_DECL_RE.finditer(css):
        prop, value = m.group(1).lower(), m.group("value").strip()
        used = _FS_VAR_RE.findall(value)
        if not used:
            out.append(_diag(slug, "font-size-token",
                             f"{where}: {prop}: {value[:60]} — use calc(var(--fs-<name>) * "
                             "var(--sdpm-pt-scale)) with a token of the style"))
            continue
        unknown = sorted(set(used) - names)
        if unknown:
            out.append(_diag(slug, "font-size-unknown-token",
                             f"{where}: {prop}: {value[:60]} — the style defines no "
                             f"{', '.join('--' + u for u in unknown)} "
                             f"(tokens: {', '.join('--' + n for n in sorted(names)) or 'none'})"))
    return out


def _slide_css_parts(root) -> Iterable[tuple[str, str]]:
    """``(where, css)`` for every inline style attribute and ``<style>`` block."""
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag == "style":
            yield "<style>", el.text or ""
        style = el.get("style")
        if style:
            yield f"<{el.tag}> style", style


def check_html_font_sizes(slides: dict[str, str], art_direction_path: Path) -> list[dict]:
    """``--fs-*`` lint for slide HTML: font sizes must reference a token of the style.

    Skipped when the style defines no ``--fs-*`` tokens (same rule as the JSON lint).
    theme.css (template text styles) is not checked.
    """
    from sdpm.engine.html.assemble import parse_slide

    names = _style_token_names(Path(art_direction_path))
    if names is None:
        return []
    out: list[dict] = []
    for slug, text in slides.items():
        parsed = parse_slide(text)
        if parsed.section is None:
            continue
        for where, css in _slide_css_parts(parsed.section):
            out.extend(_font_diags(slug, css, names, where))
    return out


# ── slide checks ─────────────────────────────────────────────────────────

def _external_attr_diags(slug: str, el) -> list[dict]:
    out = []
    tag = el.tag
    if tag in _EMBEDDING_TAGS:
        out.append(_diag(slug, "script", f"<{tag}> embeds a document the checks cannot see; "
                         "use <img> for images and put the content in the slide"))
    stylesheet = tag == "link" and "stylesheet" in (el.get("rel") or "").lower().split()
    for name, value in el.attrib.items():
        lname = name.lower()
        if lname.startswith("on"):
            out.append(_diag(slug, "script", f"<{tag} {name}=…> event handler attributes do not run; listen in "
                             "a slide script: section.querySelector(…).addEventListener(…)"))
            continue
        if lname.startswith("data-background"):
            out.append(_diag(slug, "data-background",
                             f"<{tag} {name}> — remove it: the template and deck.json "
                             "defaultBackground paint the ground; draw anything else in the slide"))
            continue
        if url_kind(value) == "javascript" and lname in _JS_URL_ATTRS:
            out.append(_diag(slug, "script", f"<{tag} {name}> uses a javascript: URL; give links a real URL "
                             "and put behaviour in a slide script with addEventListener"))
            continue
        if lname == "values" and tag in _SVG_ANIMATION_TAGS and any(
                url_kind(part) == "javascript" for part in value.split(";")):
            out.append(_diag(slug, "script", f"<{tag} values> sets a javascript: URL; remove it"))
            continue
        if tag == "use" and lname in ("href", "xlink:href") and url_kind(value) != "fragment":
            out.append(_diag(slug, "external-use",
                             f"<use {name}={value[:80]!r}> loads another document's sprite; "
                             "inline the SVG"))
        if stylesheet and lname == "href":
            out.append(_diag(slug, "external-url",
                             f"<link rel=stylesheet href={value[:80]!r}> is not embedded (the deck's CSP "
                             "blocks linked stylesheets, data: ones too); put shared rules in deck.css"))
            continue
        if lname != "style" and "url(" in value.lower():
            out.extend(_css_url_diags(slug, value, f"<{tag} {name}>"))
        urls: list[str] = []
        if lname in _RESOURCE_ATTRS:
            urls = [value]
        elif lname == "href" and tag != "a":
            urls = [value]
        elif lname == "srcset":
            urls = [url for url, _ in parse_srcset(value)]
        for url in urls:
            if url_kind(url) == "external":
                out.append(_diag(slug, "external-url",
                                 f"<{tag} {name}={url[:80]!r}> loads an external resource; embed it "
                                 "(assets:<source>/<name>, a deck file, or data:)"))
    return out


def _is_chrome_ph(ph: str, chrome_keys: set[str]) -> bool:
    return ph in chrome_keys or ph.lower() in _CHROME_PH_NAMES


def _key_order(key: str) -> tuple[int, int, str]:
    """Aliases (names) first, then idx keys numerically: ``title, 0, 1``."""
    return (1, int(key), "") if key.isdigit() else (0, 0, key)


def _placeholder_diags(slug: str, el, layout: str | None, placeholders: Mapping[str, set[str]] | None,
                       chrome_keys: set[str]) -> list[dict]:
    ph = el.get("data-ph")
    if (ph is None or placeholders is None or layout not in placeholders
            or el.get("data-sdpm-chrome") is not None or _is_chrome_ph(ph, chrome_keys)):
        return []
    keys = placeholders[layout]
    if ph in keys:
        return []
    listed = ", ".join(sorted(keys, key=_key_order)) or "none"
    return [_diag(slug, "placeholder-unknown",
                  f'data-ph="{ph}" is not a placeholder of layout {layout!r} (keys: {listed}); use one of '
                  "these keys, or drop data-ph and position the element yourself")]


def _self_chrome_diags(slug: str, el, chrome_keys: set[str]) -> list[dict]:
    if el.get("data-sdpm-chrome") is not None:
        return []
    out = []
    ph = el.get("data-ph")
    if ph is not None and _is_chrome_ph(ph, chrome_keys):
        out.append(_diag(slug, "self-chrome",
                         f'data-ph="{ph}" is a date / footer / slide-number placeholder; '
                         "remove it: the assembler draws slide numbers and footers"))
    if el.tag == "footer":
        out.append(_diag(slug, "self-chrome", "<footer> — remove it (the assembler draws the template "
                         "footer) or use another element for slide content"))
    tokens = (el.get("class") or "").split() + ([el.get("id")] if el.get("id") else [])
    for token in tokens:
        if _CHROME_TOKEN_RE.fullmatch(token):
            out.append(_diag(slug, "self-chrome",
                             f"<{el.tag}> {token!r} looks like a self-drawn slide number / footer; "
                             "the assembler draws them: remove it, or rename the class for "
                             "slide content (card-footer is fine)"))
            break
    return out


def _js_tokens(code: str, patterns: Iterable[re.Pattern]) -> list[str]:
    """Distinct matched tokens (``tok`` group when the pattern has one), in pattern order."""
    out: list[str] = []
    for pattern in patterns:
        for m in pattern.finditer(code):
            token = m.group("tok") if "tok" in pattern.groupindex else m.group(0)
            token = re.sub(r"\s+", "", token)[:60]
            if token not in out:
                out.append(token)
    return out


def _token_list(tokens: list[str]) -> str:
    shown = ", ".join(repr(t) for t in tokens[:5])
    return shown + (f" (+{len(tokens) - 5} more)" if len(tokens) > 5 else "")


def _slide_script_diags(slug: str, section, code: str) -> list[dict]:
    """Rules for a slide's classic scripts (``code`` = their concatenated text, design §8.4)."""
    from sdpm.engine.html.slide_js import LIBRARIES, LIBRARY_GLOBALS, declared_libraries

    out = []
    unknown = [name for name in (section.get("data-libs") or "").split() if name.lower() not in LIBRARIES]
    if unknown:
        out.append(_diag(slug, "library-unknown",
                         f"data-libs {_token_list(unknown)} is not a bundled library "
                         f"(known: {', '.join(LIBRARIES)}); use a known one or remove it"))
    if not code:
        return out
    tokens = _js_tokens(code, _JS_EXTERNAL_RES)
    if tokens:
        out.append(_diag(slug, "script-external",
                         f"slide script uses {_token_list(tokens)}: the deck CSP blocks fetch but not "
                         "navigation or new tabs, so the deck could send data out; remove it, keep data in "
                         "the script and put links in <a href>"))
    declared = declared_libraries(section)
    undeclared = [name for name, glob in LIBRARY_GLOBALS.items()
                  if name not in declared and re.search(rf"(?<![\w$.]){glob}\s*\.", code)]
    if undeclared:
        out.append(_diag(slug, "library-undeclared",
                         f"slide script uses {', '.join(undeclared)} without declaring it; add "
                         f'data-libs="{" ".join([*declared, *undeclared])}" to the <section>'))
    tokens = _js_tokens(code, _JS_EVAL_RES)
    if tokens:
        out.append(_diag(slug, "script-eval",
                         f"slide script calls {_token_list(tokens)}, which needs eval and is blocked by "
                         "the deck CSP; use d3.csvParseRows or inline arrays"))
    tokens = _js_tokens(code, _JS_DOM_RES)
    if tokens:
        out.append(_diag(slug, "script-dom",
                         f"slide script uses {_token_list(tokens)}: find elements with "
                         "section.querySelector (the print view clones fragment pages, so ids "
                         "repeat) and do not wait for load events (they have fired)"))
    return out


def check_slide_html(
    slug: str,
    text: str,
    *,
    layouts: set[str],
    chrome_keys: set[str] = frozenset(),
    placeholders: Mapping[str, set[str]] | None = None,
) -> list[dict]:
    """Static checks for one ``slides/<slug>.html`` (see the module docstring for rules).

    ``placeholders`` maps layout name → its ``data-ph`` keys (idx keys and aliases);
    without it the ``placeholder-unknown`` rule is skipped.
    """
    from sdpm.engine.html.assemble import parse_slide
    from sdpm.engine.html.slide_js import is_slide_script

    parsed = parse_slide(text)
    out = [_diag(slug, "structure", err) for err in parsed.errors]
    section = parsed.section
    if section is None:
        return out

    layout = section.get("data-layout")
    if not layout:
        out.append(_diag(slug, "layout-missing",
                         "the <section> needs data-layout naming a template layout"))
    elif layout not in layouts:
        sample = ", ".join(repr(n) for n in sorted(layouts)[:6])
        out.append(_diag(slug, "layout-unknown",
                         f"data-layout {layout!r} is not a layout of the template; use a layout name "
                         f"from template_html (e.g. {sample})"))
    if section.get("data-slug") is not None:
        out.append(_diag(slug, "data-slug", "data-slug is set by the assembler; remove it"))

    scripts: list[str] = []
    for el in section.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag == "script":
            if is_slide_script(el):
                scripts.append(el.text or "")
            elif el.get("src") is not None:
                out.append(_diag(slug, "script", "<script src> does not run (the deck CSP allows only "
                                 "inline scripts); put the code inline"))
            else:
                out.append(_diag(slug, "script", "only classic inline scripts run; "
                                 f"type={el.get('type')[:40]!r} is blocked: write a plain "
                                 "inline <script> (data goes in its code)"))
        if el.tag == "meta" and el.get("http-equiv") is not None:
            out.append(_diag(slug, "script",
                             f"<meta http-equiv={el.get('http-equiv')[:40]!r}> is not allowed in slides "
                             "(refresh navigates the deck away, which the CSP cannot stop); "
                             "remove it"))
        out.extend(_external_attr_diags(slug, el))
        out.extend(_self_chrome_diags(slug, el, chrome_keys))
        out.extend(_placeholder_diags(slug, el, layout, placeholders, chrome_keys))
        if el.tag == "style":
            css = el.text or ""
            if _ROOT_SEL_RE.search(_CSS_COMMENT_RE.sub("", css)):
                out.append(_diag(slug, "root-in-slide-style",
                                 ":root in a slide <style> — remove it: tokens come from the style; "
                                 "scope rules to the slide's elements (& is the section)"))
            out.extend(_css_url_diags(slug, css, "<style>"))
        style = el.get("style")
        if style:
            out.extend(_css_url_diags(slug, style, f"<{el.tag}> style"))
    out.extend(_slide_script_diags(slug, section, "\n".join(scripts)))
    return out


def check_deck_css(text: str, art_direction_path: Path) -> list[dict]:
    """Checks for the deck-root ``deck.css``: ``--fs-*`` lint and forbidden constructs."""
    slug = DECK_CSS_SLUG
    css = _CSS_COMMENT_RE.sub("", text)
    out: list[dict] = []
    names = _style_token_names(Path(art_direction_path))
    if names is not None:
        out.extend(_font_diags(slug, css, names, "deck.css"))
    out.extend(_css_url_diags(slug, css, "deck.css"))
    if re.search(r"javascript\s*:", css, re.IGNORECASE) and not any(
            d["rule"] == "script" for d in out):
        out.append(_diag(slug, "script", "javascript: in deck.css; remove it"))
    if re.search(r"expression\s*\(", css, re.IGNORECASE):
        out.append(_diag(slug, "script", "expression() in deck.css; remove it"))
    if re.search(r"</\s*style", css, re.IGNORECASE):
        out.append(_diag(slug, "script", "</style in deck.css; remove it"))
    if _ROOT_SEL_RE.search(css):
        out.append(_diag(slug, "root-in-deck-css",
                         ":root in deck.css — remove the block: tokens come only from the style "
                         "(specs/art-direction.html)"))
    return out


# ── reporting ────────────────────────────────────────────────────────────

CHECK_REPORT_HEADER = "Checks:"


def not_in_deck_message(slug: str) -> str:
    """The line for a requested slug the deck does not build (never reported as OK)."""
    return (f"{slug}: not in the deck, so not checked — the outline must list [{slug}] and "
            f"slides/{slug}.html must exist")


def format_check_report(diags: list[dict], slugs: Iterable[str] | None = None, browser: dict | None = None,
                        *, not_in_deck: Iterable[str] = ()) -> str:
    """Plain-text check report (the HTML counterpart of the measure report).

    With ``slugs``, lists each of them (``OK`` when clean) plus deck.css findings;
    without, lists every slug that has findings. ``browser`` (generate_html's
    ``browser_check``) adds a ``browser:`` line under the header. ``not_in_deck``: requested
    slugs the deck does not build, listed as not checked.
    """
    not_in_deck = list(dict.fromkeys(not_in_deck))
    by_slug: dict[str, list[dict]] = {}
    for d in diags:
        by_slug.setdefault(d["slug"], []).append(d)
    order = list(slugs) if slugs is not None else [s for s in by_slug if s != DECK_CSS_SLUG]
    lines = [CHECK_REPORT_HEADER]
    if browser is not None:
        if browser.get("note"):
            lines.append(f"  browser: {browser['status']} — {browser['note']}")
        else:
            lines.append(f"  browser: {browser['status']} ({browser.get('browser', 'browser')}, "
                         f"{browser.get('seconds', 0)} s)")
    if DECK_CSS_SLUG in by_slug:
        order = [DECK_CSS_SLUG, *[s for s in order if s != DECK_CSS_SLUG]]
    order = [s for s in order if s not in not_in_deck]
    if not order and not not_in_deck:
        lines.append("  no issues")
    for slug in order:
        found = by_slug.get(slug, [])
        if not found:
            lines.append(f"{slug}: OK")
            continue
        lines.append(f"{slug}: {len(found)} issue(s)")
        lines.extend(f"  [{d['rule']}] {d['message']}" for d in found)
    lines.extend(not_in_deck_message(slug) for slug in not_in_deck)
    return "\n".join(lines)


__all__ = [
    "CHECK_REPORT_HEADER",
    "DECK_CSS_SLUG",
    "check_deck_css",
    "check_html_font_sizes",
    "check_slide_html",
    "format_check_report",
    "image_set_strings",
    "parse_srcset",
    "url_kind",
]
