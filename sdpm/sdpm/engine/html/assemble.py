# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Assemble slides/<slug>.html sections into one offline reveal.js ``output.html``.

Everything is inlined: reveal.js (``sdpm.config.VENDOR_DIR``), the style ``:root``,
theme.css, the decoration SVG of each used layout (once, as a CSS background), the
deck-root ``deck.css``, each slide's scoped ``<style>``, ``assets:`` icons (inline
SVG) and every other file (data URIs — deck SVGs too, so their scripts never run).
``<link rel=stylesheet>`` is not embedded (shared rules belong in deck.css). The
result loads nothing from the network.

Head order: reset.css + reveal.css → style :root (``#sdpm-style-root``) → theme.css
(``#sdpm-theme``) → deck rules (``#sdpm-deck``) → deck.css (``#sdpm-deck-css``) →
slide styles nested under ``section[data-slug="…"]`` (``#sdpm-slides``). At-rules that
cannot be nested (``@keyframes``, ``@font-face``, ``@property``…) are emitted unscoped
just before their slide's rules, keyframes renamed ``sdpm-<slug>-<name>``.
"""

from __future__ import annotations

import base64
import html as _html
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from lxml import etree
from lxml import html as lxml_html

from sdpm.engine.html.check import image_set_strings, parse_srcset, url_kind
from sdpm.engine.html.template import TemplateHtml, css_string

_ROOT_RE = re.compile(r":root\s*\{(?P<body>.*?)\}", re.DOTALL | re.IGNORECASE)
_CSS_URL_RE = re.compile(r"url\(\s*(?P<q>['\"]?)(?P<url>.*?)(?P=q)\s*\)", re.IGNORECASE | re.DOTALL)
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_JUSTIFY = {"top": "flex-start", "middle": "center", "bottom": "flex-end"}
# <img> attributes that do not carry over to an inlined <svg>.
_IMG_ONLY_ATTRS = frozenset({"src", "alt", "srcset", "sizes", "loading", "decoding",
                             "crossorigin", "referrerpolicy", "fetchpriority"})
_INLINE_TAG = "sdpm-inline-svg"
# Resource-loading attributes embedded as data URIs, per tag (others: src, poster).
# <link> is left alone: a linked stylesheet is not embedded (check.py warns).
_EMBED_ATTRS = {
    "object": ("data",),
    "link": (),
    "image": ("href", "xlink:href"),
    "feimage": ("href", "xlink:href"),
}
# Size warnings (everything is base64-embedded into one file).
MAX_EMBEDDED_FILE_BYTES = 5 * 1024 * 1024
MAX_OUTPUT_HTML_BYTES = 25 * 1024 * 1024


def _mb(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"


@dataclass
class ParsedSlide:
    """One slide file: its ``<section>`` (None when unusable) and what it contains."""

    section: Any | None
    layout: str | None = None
    has_notes: bool = False
    styles: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class AssembleResult:
    """Assembled deck: the HTML text and what went into it."""

    html: str
    bytes: int
    layouts_used: list[str]
    warnings: list[str]
    slugs: list[str] = field(default_factory=list)  # slides actually included, in order


def style_root_css(art_direction_html: str) -> str:
    """The style's ``:root{…}`` block (same match as ``sdpm.api.merge_style_metadata``), or ''."""
    m = _ROOT_RE.search(art_direction_html or "")
    return f":root{{{m.group('body')}}}" if m else ""


def parse_slide(text: str) -> ParsedSlide:
    """Parse a slide file; ``errors`` lists structure problems (exactly one top-level section)."""
    try:
        fragments = lxml_html.fragments_fromstring(text or "")
    except (etree.ParserError, ValueError) as exc:
        return ParsedSlide(None, errors=[f"cannot parse the slide HTML ({exc})"])
    sections = []
    errors = []
    for frag in fragments:
        if isinstance(frag, str):
            if frag.strip():
                errors.append("text outside the <section>")
            continue
        if not isinstance(frag.tag, str):  # comment / processing instruction
            continue
        if frag.tag == "section":
            sections.append(frag)
        else:
            errors.append(f"top-level <{frag.tag}> outside the <section>")
        if frag.tail and frag.tail.strip():
            errors.append("text outside the <section>")
    if len(sections) != 1:
        errors.insert(0, f"expected exactly one top-level <section>, found {len(sections)}")
        return ParsedSlide(sections[0] if len(sections) > 1 else None, errors=errors)
    section = sections[0]
    if any(el.tag == "section" for el in section.iterdescendants() if isinstance(el.tag, str)):
        errors.append("nested <section> (vertical slides) is not supported")
    styles = [el.text or "" for el in section.iter("style")]
    has_notes = any("notes" in (el.get("class") or "").split() for el in section.iter("aside"))
    return ParsedSlide(section, section.get("data-layout"), has_notes, styles, errors)


# ── small helpers ────────────────────────────────────────────────────────

def _escape_css_text(css: str) -> str:
    """Keep embedded CSS from closing its ``<style>`` element."""
    return re.sub(r"</", r"<\\/", css)


def inline_js(code: str) -> str:
    """Escape JS for an inline ``<script>`` (``</script`` and ``<!--`` cannot appear)."""
    code = re.sub(r"</(script)", r"<\\/\1", code, flags=re.IGNORECASE)
    return code.replace("<!--", "<\\!--")


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0]
    if path.suffix.lower() == ".svg":
        mime = "image/svg+xml"
    mime = mime or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _is_dark(color: str | None) -> bool:
    if not color or not _HEX_RE.match(color.strip()):
        return False
    value = color.strip()[1:]
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.5


def _num(value: float) -> str:
    return format(round(float(value), 4), "g")


class _Resolver:
    """Turns ``assets:`` refs and deck-relative paths into files, collecting warnings."""

    def __init__(self, deck_dir: Path, theme: str, warn: Callable[[str], None]):
        self.deck_dir = deck_dir.resolve()
        self.theme = theme
        self.warn = warn
        self._sized: set[Path] = set()

    def path(self, ref: str, where: str) -> Path | None:
        target = self._path(ref, where)
        if target is not None and target not in self._sized:
            self._sized.add(target)
            size = target.stat().st_size
            if size > MAX_EMBEDDED_FILE_BYTES:
                self.warn(f"{where}: {ref} is {_mb(size)} (over {_mb(MAX_EMBEDDED_FILE_BYTES)}) and is "
                          "embedded in output.html; compress or shrink it")
        return target

    def _path(self, ref: str, where: str) -> Path | None:
        kind = url_kind(ref)
        if kind == "assets":
            from sdpm.knowledge.assets import resolve_asset_path

            try:
                return resolve_asset_path(ref.strip(), theme=self.theme)
            except FileNotFoundError:
                self.warn(f"{where}: asset not found: {ref}")
                return None
        if kind == "relative":
            target = (self.deck_dir / ref.strip().split("#", 1)[0].split("?", 1)[0]).resolve()
            if not target.is_relative_to(self.deck_dir):
                self.warn(f"{where}: {ref} is outside the deck directory — not embedded")
                return None
            if not target.is_file():
                self.warn(f"{where}: file not found: {ref}")
                return None
            return target
        return None

    def css(self, css: str, where: str) -> str:
        def repl(m: re.Match) -> str:
            url = m.group("url")
            path = self.path(url, where)
            if path is None:
                return m.group(0)
            return f'url("{_data_uri(path)}")'

        for start, end, url in reversed(image_set_strings(css)):
            path = self.path(url, where)
            if path is not None:
                css = f'{css[:start]}"{_data_uri(path)}"{css[end:]}'
        return _CSS_URL_RE.sub(repl, css)


# ── slide CSS: at-rules that cannot be nested ────────────────────────────

# CSS nesting admits only conditional group rules inside a style rule; these are
# emitted unscoped instead of inside ``section[data-slug="…"]{…}``.
_HOISTED_AT_RULES = frozenset({"keyframes", "-webkit-keyframes", "font-face", "property",
                               "counter-style", "font-feature-values", "font-palette-values"})
_AT_NAME_RE = re.compile(r"@([\w-]+)")
_IDENT_RE = re.compile(r"\s+(-?[_a-zA-Z][\w-]*)")
_ANIMATION_DECL_RE = re.compile(r"(?<![\w-])((?:-webkit-)?animation(?:-name)?\s*:\s*)([^;{}]+)",
                                re.IGNORECASE)
_NON_IDENT_RE = re.compile(r"[^A-Za-z0-9_-]")


def _leading_at_keyword(chunk: str) -> re.Match[str] | None:
    """Match the at-keyword (``@name``) a CSS statement starts with, after whitespace and comments.

    A linear scan rather than one regex: ``(?:/\\*.*?\\*/\\s*)*@`` backtracks exponentially
    on input such as ``/*`` followed by many ``*//*`` with no ``@``.
    """
    i, n = 0, len(chunk)
    while True:
        while i < n and chunk[i].isspace():
            i += 1
        if not chunk.startswith("/*", i):
            break
        end = chunk.find("*/", i + 2)
        if end < 0:
            return None
        i = end + 2
    return _AT_NAME_RE.match(chunk, i)


def _top_level_chunks(css: str) -> list[str]:
    """Split CSS into top-level statements (rules and at-rules), skipping strings and comments."""
    chunks: list[str] = []
    depth, start, i, n = 0, 0, 0, len(css)
    while i < n:
        c = css[i]
        if css.startswith("/*", i):
            end = css.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if c in "\"'":
            j = i + 1
            while j < n and css[j] not in (c, "\n"):
                j += 2 if css[j] == "\\" else 1
            i = j + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(depth - 1, 0)
        if (c == "}" and depth == 0) or (c == ";" and depth == 0):
            chunks.append(css[start:i + 1])
            start = i + 1
        i += 1
    if css[start:].strip():
        chunks.append(css[start:])
    return chunks


def _split_slide_css(css: str, slug: str) -> tuple[list[str], str, dict[str, str]]:
    """``(hoisted at-rules, CSS to nest, keyframes renames)`` for one slide ``<style>``.

    Keyframes are renamed ``sdpm-<slug>-<name>`` so slides written in parallel
    cannot collide; ``_rename_animations`` updates the references.
    """
    hoisted: list[str] = []
    kept: list[str] = []
    names: dict[str, str] = {}
    prefix = f"sdpm-{_NON_IDENT_RE.sub('_', slug)}-"
    for chunk in _top_level_chunks(css):
        m = _leading_at_keyword(chunk)
        keyword = m.group(1).lower() if m else ""
        if keyword not in _HOISTED_AT_RULES:
            kept.append(chunk)
            continue
        if keyword.endswith("keyframes"):
            name = _IDENT_RE.match(chunk, m.end())
            if name:
                names[name.group(1)] = prefix + name.group(1)
                chunk = chunk[:name.start(1)] + names[name.group(1)] + chunk[name.end(1):]
        hoisted.append(chunk.strip())
    if not hoisted:
        return [], css, {}
    return hoisted, "".join(kept), names


def _rename_animations(css: str, names: dict[str, str]) -> str:
    """Point ``animation`` / ``animation-name`` values at the renamed keyframes."""
    if not names or "animation" not in css.lower():
        return css
    word = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, names)) + r")(?![\w-])")
    return _ANIMATION_DECL_RE.sub(
        lambda m: m.group(1) + word.sub(lambda w: names[w.group(1)], m.group(2)), css)


# ── inline SVG ───────────────────────────────────────────────────────────

_SVG_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True,
                              remove_pis=True, huge_tree=False)
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"


def _inline_svg_text(path: Path, img, prefix: str) -> str | None:
    try:
        root = etree.fromstring(path.read_bytes(), _SVG_PARSER)
    except etree.XMLSyntaxError:
        return None
    if not isinstance(root.tag, str) or etree.QName(root).localname != "svg":
        return None
    ids = {el.get("id") for el in root.iter() if isinstance(el.tag, str) and el.get("id")}
    if ids:
        mapping = {old: prefix + old for old in ids}

        def fix_urls(value: str) -> str:
            return re.sub(r"url\(\s*(['\"]?)#([^)'\"]+)\1\s*\)",
                          lambda m: f"url(#{mapping.get(m.group(2), m.group(2))})", value)

        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            if el.get("id") in mapping:
                el.set("id", mapping[el.get("id")])
            for name, value in list(el.attrib.items()):
                if name in ("href", _XLINK_HREF) and value.startswith("#") and value[1:] in mapping:
                    el.set(name, "#" + mapping[value[1:]])
                elif "url(" in value:
                    el.set(name, fix_urls(value))
            if etree.QName(el).localname == "style" and el.text:
                el.text = fix_urls(el.text)
    for name, value in img.attrib.items():
        if name in _IMG_ONLY_ATTRS or ":" in name:
            continue
        root.set(name, value)
    alt = img.get("alt")
    if alt:
        root.set("role", "img")
        root.set("aria-label", alt)
    return etree.tostring(root, encoding="unicode")


# ── section processing ───────────────────────────────────────────────────

def _process_media(section, slide_index: int, resolver: _Resolver, where: str,
                   inline: dict[str, str]) -> None:
    n = 0
    for el in list(section.iter()):
        if not isinstance(el.tag, str):
            continue
        tag = el.tag
        style = el.get("style")
        if style and ("url(" in style or "image-set(" in style):
            el.set("style", resolver.css(style, where))
        srcset = el.get("srcset")
        if srcset:
            candidates = []
            for url, descriptors in parse_srcset(srcset):
                path = resolver.path(url, where) if url_kind(url) in ("assets", "relative") else None
                candidates.append(f"{_data_uri(path) if path else url} {descriptors}".strip())
            el.set("srcset", ", ".join(candidates))
        for attr in _EMBED_ATTRS.get(tag, ("src", "poster")):
            ref = el.get(attr)
            if ref is None or url_kind(ref) not in ("assets", "relative"):
                continue
            path = resolver.path(ref, where)
            if path is None:
                continue
            # Only catalog icons are inlined; a deck SVG stays an image (inert, offline).
            if (tag == "img" and attr == "src" and url_kind(ref) == "assets"
                    and path.suffix.lower() == ".svg"):
                n += 1
                svg = _inline_svg_text(path, el, f"s{slide_index}i{n}-")
                if svg is not None:
                    key = str(len(inline))
                    inline[key] = svg
                    holder = lxml_html.Element(_INLINE_TAG, {"data-k": key})
                    holder.tail = el.tail
                    el.getparent().replace(el, holder)
                    break
                resolver.warn(f"{where}: {ref} is not a valid SVG — embedded as an image")
            el.set(attr, _data_uri(path))


def _chrome_html(chrome: dict, kind: str, text: str) -> str:
    bbox = chrome["bbox"]
    style = chrome.get("text", {})
    level = (style.get("levels") or [{}])[0]
    insets = style.get("insets", {})
    decls = [
        f"left:{bbox['x']}px", f"top:{bbox['y']}px", f"width:{bbox['w']}px", f"height:{bbox['h']}px",
        "box-sizing:border-box", "margin:0", "display:flex", "flex-direction:column",
        f"justify-content:{_JUSTIFY.get(style.get('anchor'), 'flex-start')}",
    ]
    if insets:
        decls.append(f"padding:{_num(insets.get('top', 0))}px {_num(insets.get('right', 0))}px "
                     f"{_num(insets.get('bottom', 0))}px {_num(insets.get('left', 0))}px")
    font = level.get("fontRef")
    if font in ("major", "minor"):
        decls.append(f"font-family:var(--font-family, var(--sdpm-font-{font})), var(--sdpm-font-{font})")
    elif level.get("font"):
        decls.append(f"font-family:var(--font-family, {css_string(level['font'])}), {css_string(level['font'])}")
    if "sizePt" in level:
        decls.append(f"font-size:calc({_num(level['sizePt'])}pt * var(--sdpm-pt-scale))")
    if level.get("color"):
        decls.append(f"color:{level['color']}")
    if level.get("align"):
        decls.append(f"text-align:{level['align']}")
    style_attr = _html.escape(";".join(decls), quote=True)
    return (f'<div data-sdpm-chrome="{kind}" style="{style_attr}">'
            f"<span>{_html.escape(text)}</span></div>")


def _serialize_section(section, slug: str, number: int, layout_info: dict | None,
                       inline: dict[str, str]) -> str:
    section.set("data-slug", slug)
    chrome = (layout_info or {}).get("chrome") or {}
    if chrome.get("slideNumber"):
        section.append(lxml_html.Element("i", {"data-sdpm-placeholder": "slide-number"}))
    if chrome.get("footer", {}).get("value"):
        section.append(lxml_html.Element("i", {"data-sdpm-placeholder": "footer"}))
    text = lxml_html.tostring(section, encoding="unicode", method="html", with_tail=False)
    if chrome.get("slideNumber"):
        text = text.replace('<i data-sdpm-placeholder="slide-number"></i>',
                            _chrome_html(chrome["slideNumber"], "slide-number", str(number)), 1)
    if chrome.get("footer", {}).get("value"):
        text = text.replace('<i data-sdpm-placeholder="footer"></i>',
                            _chrome_html(chrome["footer"], "footer", chrome["footer"]["value"]), 1)
    for key, svg in inline.items():
        text = text.replace(f'<{_INLINE_TAG} data-k="{key}"></{_INLINE_TAG}>', svg, 1)
    return text


# ── deck ─────────────────────────────────────────────────────────────────

def _vendor_text(name: str) -> str:
    from sdpm.config import VENDOR_DIR

    return (VENDOR_DIR / "revealjs" / name).read_text(encoding="utf-8")


def _deck_rules(template: TemplateHtml, layouts_used: list[str], default_background: str | None,
                default_text_color: str | None) -> str:
    ground = default_background or "var(--sdpm-template-bg)"
    color = default_text_color or "var(--color-text)"
    rules = [
        ".reveal .slides > section{"
        "width:var(--sdpm-canvas-w);height:var(--sdpm-canvas-h);padding:0;box-sizing:border-box;"
        "text-align:left;"
        "font-family:var(--font-family, var(--sdpm-font-minor)), var(--sdpm-font-minor);"
        f"color:{color};"
        f"--sdpm-ground:{ground};"
        "background-color:var(--sdpm-ground);background-size:100% 100%;background-repeat:no-repeat;"
        "-webkit-print-color-adjust:exact;print-color-adjust:exact}",
        f":root{{--sdpm-ground:{ground}}}",
    ]
    for name in layouts_used:
        svg = None
        if not default_background:
            svg = template.ground_svg_paths.get(name)
        svg = svg or template.svg_paths.get(name)
        if svg is None or not svg.is_file():
            continue
        b64 = base64.b64encode(svg.read_bytes()).decode("ascii")
        rules.append(f"section[data-layout={css_string(name)}]"
                     f'{{background-image:url("data:image/svg+xml;base64,{b64}")}}')
    rules.append("[data-sdpm-chrome],[data-region]{position:absolute}")
    rules.append(".reveal-viewport{background:var(--sdpm-ground)}")
    return "\n".join(rules)


def assemble_deck(
    *,
    slides: list[tuple[str, str]],
    template: TemplateHtml,
    art_direction_html: str,
    default_background: str | None,
    default_text_color: str | None,
    title: str,
    deck_dir: Path,
    deck_css: str | None = None,
    lang: str | None = None,
) -> AssembleResult:
    """Build the single-file reveal.js deck.

    Args:
        slides: ``(slug, slide file text)`` in deck order. Unparseable slides are
            skipped with a warning (``check_slide_html`` reports why).
        template: ``load_template_html`` result.
        art_direction_html: specs/art-direction.html text ('' when the deck has no style).
        default_background: deck.json ``defaultBackground`` (replaces the template ground,
            and selects the plain decoration SVG over the baked-ground one).
        default_text_color: deck.json ``defaultTextColor`` (else the style ``--color-text``).
        title: document title.
        deck_dir: deck root; deck-relative image paths resolve against it.
        deck_css: deck-root deck.css text, embedded once, unscoped.
        lang: ``<html lang>`` (omitted when None).

    Returns:
        AssembleResult(html, bytes, layouts_used, warnings, slugs) — warnings are
        ``"<slug>: …"`` / ``"deck.css: …"`` / ``"output.html: …"`` strings (the last one
        when the file passes ``MAX_OUTPUT_HTML_BYTES``; an embedded file over
        ``MAX_EMBEDDED_FILE_BYTES`` is warned under its slide); slugs are the included slides.
    """
    warnings: list[str] = []
    ground = default_background or template.info.get("ground")
    resolver = _Resolver(Path(deck_dir), "dark" if _is_dark(ground) else "light", warnings.append)
    layouts_by_name = {layout["name"]: layout for layout in template.info.get("layouts", [])}

    sections: list[str] = []
    included: list[str] = []
    slide_css: list[str] = []
    layouts_used: list[str] = []
    for slug, text in slides:
        parsed = parse_slide(text)
        if parsed.section is None or parsed.errors:
            warnings.append(f"{slug}: slide skipped — {'; '.join(parsed.errors) or 'no <section>'}")
            continue
        section = parsed.section
        number = len(sections) + 1
        parts = []
        for style_el in list(section.iter("style")):
            parts.append(_split_slide_css(resolver.css(style_el.text or "", slug), slug))
            style_el.drop_tree()
        renames = {old: new for _, _, found in parts for old, new in found.items()}
        for hoisted, nested, _ in parts:
            slide_css.extend(hoisted)
            nested = _rename_animations(nested, renames)
            if nested.strip():
                slide_css.append(f"section[data-slug={css_string(slug)}]{{\n{nested}\n}}")
        if renames:
            for el in section.iter():
                if isinstance(el.tag, str) and el.get("style"):
                    el.set("style", _rename_animations(el.get("style"), renames))
        inline: dict[str, str] = {}
        _process_media(section, number, resolver, slug, inline)
        layout = parsed.layout
        if layout and layout in layouts_by_name and layout not in layouts_used:
            layouts_used.append(layout)
        sections.append(_serialize_section(section, slug, number, layouts_by_name.get(layout), inline))
        included.append(slug)

    size = template.info.get("slideSize", {})
    width, height = int(size.get("width", 1920)), int(size.get("height", 1080))
    deck_css_text = resolver.css(deck_css, "deck.css") if deck_css else ""

    head = [
        "<!doctype html>",
        f'<html lang="{_html.escape(lang, quote=True)}">' if lang else "<html>",
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_html.escape(title)}</title>",
        f"<style>{_escape_css_text(_vendor_text('reset.css'))}\n{_escape_css_text(_vendor_text('reveal.css'))}</style>",
        f'<style id="sdpm-style-root">{_escape_css_text(style_root_css(art_direction_html))}</style>',
        f'<style id="sdpm-theme">{_escape_css_text(template.theme_css)}</style>',
        f'<style id="sdpm-deck">{_escape_css_text(_deck_rules(template, layouts_used, default_background, default_text_color))}</style>',
    ]
    if deck_css_text:
        head.append(f'<style id="sdpm-deck-css">{_escape_css_text(deck_css_text)}</style>')
    head.append(f'<style id="sdpm-slides">{_escape_css_text(chr(10).join(slide_css))}</style>')
    head.append("</head>")
    config = (f"Reveal.initialize({{width:{width},height:{height},margin:0.04,center:false,"
              "hash:true,plugins:[RevealNotes]});")
    body = [
        "<body>",
        '<div class="reveal"><div class="slides">',
        *sections,
        "</div></div>",
        f"<script>{inline_js(_vendor_text('reveal.js'))}</script>",
        f"<script>{inline_js(_vendor_text('plugin/notes.js'))}</script>",
        f"<script>{config}</script>",
        "</body>",
        "</html>",
    ]
    text = "\n".join(head + body) + "\n"
    total = len(text.encode("utf-8"))
    if total > MAX_OUTPUT_HTML_BYTES:
        warnings.append(f"output.html: {_mb(total)} (over {_mb(MAX_OUTPUT_HTML_BYTES)}) — it opens "
                        "slowly; compress or shrink the embedded images")
    return AssembleResult(html=text, bytes=total, layouts_used=layouts_used,
                          warnings=warnings, slugs=included)


__all__ = ["AssembleResult", "MAX_EMBEDDED_FILE_BYTES", "MAX_OUTPUT_HTML_BYTES", "ParsedSlide",
           "assemble_deck", "inline_js", "parse_slide", "style_root_css"]
