# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Reference: unified access to design patterns and example datasets.

Reference data is used to guide AI-generated slide content.
See docs/internal/DATASET_COMPLIANCE.md for dataset provenance.

Reference: unified access to design patterns, components, schemas, rules, and reviews."""
import re
from collections.abc import Iterable
from pathlib import Path, PureWindowsPath
from typing import Any

from sdpm.config import REFERENCES_DIR, get_state
from sdpm.knowledge.reference.providers import FileProvider, ReferenceProvider  # noqa: F401

# Package-bundled styles directory (for user-local style search fallback).
BUNDLED_STYLES_DIR = REFERENCES_DIR / "examples" / "styles"

# Package-bundled guide directories, searched after the user's own ones.
BUNDLED_STRUCTURES_DIR = REFERENCES_DIR / "examples" / "structure"
BUNDLED_WRITINGS_DIR = REFERENCES_DIR / "examples" / "writing"

_HTML_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE)


def html_title(html: str) -> str:
    """Return the stripped ``<title>`` text of an HTML document, or "" when it has none.

    A style's description is its ``<title>``. Pure function, so the cloud listings
    (S3 bodies) use the same rule as the filesystem listing.
    """
    m = _HTML_TITLE_RE.search(html)
    return m.group(1).strip() if m else ""


_SLIDE_START_RE = re.compile(r'<div class="slide[\s"]')
_HEAD_RE = re.compile(r"<head[^>]*>([\s\S]*?)</head>", re.IGNORECASE)
_BODY_OPEN_RE = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
_SVG_RE = re.compile(r"<svg\b[^>]*>[\s\S]*?</svg>", re.IGNORECASE)
_TRAILING_CLOSES_RE = re.compile(r"(</div>\s*)+\Z")
_SYMBOL_RE = re.compile(r"<symbol\b", re.IGNORECASE)


def is_style_name(name: Any) -> bool:
    """Whether ``name`` names a file directly inside a styles directory.

    The local store's rule: any single path component (``社内標準`` and ``acme.v2`` too),
    never a separator, a drive, ``.`` or ``..``, so a name never walks out of the directory.
    The remote's S3 keys keep the narrower ``shared.user_library.is_valid_style_name``.
    """
    return (
        isinstance(name, str)
        and name not in ("", ".", "..")
        and "\x00" not in name
        and PureWindowsPath(name).name == name  # Windows rules also catch "/" and "C:"
    )


def style_display_parts(html: str) -> dict[str, Any]:
    """Cut a style document into the parts a viewer needs to show it one slide at a time.

    Returns ``{"head", "prelude", "slides"}``: the inner ``<head>`` (the CSS, carried once),
    the icon sprites between ``<body>`` and the first slide, and each slide's markup. A
    document without slide markers comes back whole (``"whole": True``). The same cut as
    the Web UI's ``splitStyleSlides``. Pure function.
    """
    starts = [m.start() for m in _SLIDE_START_RE.finditer(html)]
    if not starts:
        return {"head": "", "prelude": "", "slides": [html], "whole": True}
    head = _HEAD_RE.search(html)
    end = html.find("</body>")
    end = end if end != -1 else len(html)
    body = _BODY_OPEN_RE.search(html)
    before = html[body.end() if body else 0:starts[0]]
    prelude = "".join(svg for svg in _SVG_RE.findall(before) if _SYMBOL_RE.search(svg))
    slides = [
        _TRAILING_CLOSES_RE.sub("", html[start:starts[i + 1] if i + 1 < len(starts) else end])
        for i, start in enumerate(starts)
    ]
    return {"head": head.group(1) if head else "", "prelude": prelude, "slides": slides}


def _get_description(path: Path) -> str:
    """Extract description from first non-empty line of md or pptx speaker notes."""
    if path.suffix == '.pptx':
        try:
            from pptx import Presentation
            prs = Presentation(str(path))
            if prs.slides:
                slide = prs.slides[0]
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                    text = slide.notes_slide.notes_text_frame.text.replace('\x0B', '\n')
                    for line in text.splitlines():
                        if line.strip():
                            return line.strip()
        except Exception:
            pass
        return ""
    # md / html
    try:
        text = path.read_text(encoding="utf-8")
        # HTML — extract <title>
        if path.suffix == '.html':
            return html_title(text)
        lines = text.splitlines()
        # Parse YAML frontmatter for description
        if lines and lines[0].strip() == '---':
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == '---':
                    # Extract description from frontmatter
                    for fm_line in lines[1:i]:
                        if fm_line.startswith('description:'):
                            val = fm_line[len('description:'):].strip().strip('"').strip("'")
                            if val:
                                return val
                    # No description in frontmatter — fall through to first content line
                    lines = lines[i + 1:]
                    break
        for line in lines:
            if line.strip():
                return line.strip()
    except Exception:
        pass
    return ""


def list_pptx_descriptions(pptx_path):
    """List all slide descriptions (speaker notes line 1) from a pptx file."""
    from pptx import Presentation

    prs = Presentation(str(pptx_path))
    descriptions = []
    for slide_idx, slide in enumerate(prs.slides):
        desc = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            text = slide.notes_slide.notes_text_frame.text.replace('\x0B', '\n')
            for line in text.splitlines():
                if line.strip():
                    desc = line.strip()
                    break
        descriptions.append((slide_idx + 1, desc or f"(slide {slide_idx + 1})"))
    return descriptions


def get_pptx_notes(pptx_path, pages=None):
    """Extract speaker notes from pptx slides.

    Args:
        pptx_path: Path to the pptx file.
        pages: Optional list of 1-based page numbers. None = all pages.
    Returns:
        List of (page_number, notes_text) tuples.
    """
    from pptx import Presentation

    prs = Presentation(str(pptx_path))
    results = []
    for slide_idx, slide in enumerate(prs.slides):
        page_num = slide_idx + 1
        if pages and page_num not in pages:
            continue
        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes = slide.notes_slide.notes_text_frame.text.strip().replace('\x0B', '\n')
        if notes:
            results.append((page_num, notes))
    return results


# ---------------------------------------------------------------------------
# High-level reference helpers (local filesystem)
# ---------------------------------------------------------------------------


def _collect_files(directory: Path) -> dict[str, Path]:
    """Collect md/pptx files in directory. md takes priority over pptx for same stem."""
    files: dict[str, Path] = {}
    for f in sorted(directory.glob("*.pptx")):
        files[f.stem] = f
    for f in sorted(directory.glob("*.md")):
        files[f.stem] = f  # md overwrites pptx
    return files


def _strip_frontmatter(text: str) -> str:
    """Strip YAML frontmatter from markdown text."""
    lines = text.splitlines(True)
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                return "".join(lines[i + 1:]).lstrip("\n")
    return text


def list_category(category_dir: Path) -> list[dict[str, str]]:
    """List documents in a category directory with descriptions.

    Supports flat and subdirectory layouts (matching CLI _list_or_show).
    md takes priority over pptx for same stem.
    """
    if not category_dir.exists():
        return []
    subdirs = sorted(d for d in category_dir.iterdir() if d.is_dir())
    flat = not subdirs
    items: list[dict[str, str]] = []
    if flat:
        for stem, f in sorted(_collect_files(category_dir).items()):
            items.append({"name": stem, "description": _get_description(f)})
    else:
        for sd in subdirs:
            for stem, f in sorted(_collect_files(sd).items()):
                items.append({"name": f"{sd.name}/{stem}", "description": _get_description(f)})
    return items


def read_docs(category_dir: Path, names: list[str]) -> list[dict]:
    """Read documents by name from a category directory.

    Supports .md (with frontmatter strip), .pptx (notes via get_pptx_notes).
    Names can include page specifiers for pptx: "name/3" or "name/all".
    """
    results = []
    for name in names:
        pages = None
        has_page_specifier = False
        parts = name.rsplit("/", 1)
        file_name = name
        if len(parts) == 2 and (parts[1].isdigit() or parts[1] == "all"):
            file_name = parts[0]
            has_page_specifier = True
            pages = None if parts[1] == "all" else [int(parts[1])]

        md_path = category_dir / f"{file_name}.md"
        pptx_path = category_dir / f"{file_name}.pptx"

        if md_path.exists():
            text = _strip_frontmatter(md_path.read_text(encoding="utf-8"))
            results.append({"name": file_name, "content": text})
        elif pptx_path.exists():
            if not has_page_specifier:
                descriptions = list_pptx_descriptions(str(pptx_path))
                content = "\n".join(f"  {page:>3}  {desc}" for page, desc in descriptions)
            else:
                notes = get_pptx_notes(pptx_path, pages=pages)
                content = "\n".join(f"## Page {pn}\n\n{text}\n" for pn, text in notes)
            results.append({"name": name, "content": content})
        else:
            # Collect available names for error message
            available = sorted(_collect_files(category_dir).keys())
            raise FileNotFoundError(
                f"'{file_name}' not found in {category_dir.name}/. Available: {', '.join(available)}"
            )
    return results


def list_styles(styles_dir: Path) -> list[dict[str, str]]:
    """List available styles from HTML files in a styles directory.

    Returns list of dicts with name and description.
    """
    if not styles_dir.exists():
        return []
    styles: list[dict[str, str]] = []
    for f in sorted(styles_dir.iterdir()):
        if f.suffix != ".html" or f.name.startswith("."):
            continue
        desc = _get_description(f)
        styles.append({"name": f.stem, "description": desc})
    return styles


def list_guides_in(guides_dir: Path) -> list[dict[str, str]]:
    """List guide documents (``.md``) in one directory, with their descriptions.

    The structure and writing stores hold Markdown, so the description comes from
    the frontmatter rather than a ``<title>``. Same shadowing rule as styles:
    :func:`merge_style_lists` keeps the first occurrence of each name.
    """
    if not guides_dir.exists():
        return []
    guides: list[dict[str, str]] = []
    for f in sorted(guides_dir.iterdir()):
        if f.suffix != ".md" or f.name.startswith("."):
            continue
        guides.append({"name": f.stem, "description": _get_description(f)})
    return guides


def list_guides_merged(guides_dirs: list[Path]) -> list[dict[str, str]]:
    """List guides across directories, the user's own first (they shadow bundled ones)."""
    return merge_style_lists(*(list_guides_in(d) for d in guides_dirs))


def list_styles_merged(styles_dirs: list[Path]) -> list[dict[str, str]]:
    """List styles from multiple directories, user-local first (shadows bundled).

    For each style name (file stem), only the first occurrence across the
    given directories is kept. Typically callers pass the result of
    ``api.get_styles_dirs()`` which orders env-overrides → user-local → bundled.
    """
    return merge_style_lists(*(list_styles(d) for d in styles_dirs))


def merge_style_lists(*groups: Iterable[dict]) -> list[dict]:
    """Merge style lists in priority order: the first style of each name wins.

    Pure function — the one shadowing rule for every style listing. Pass the
    user's styles before the bundled ones so a user style replaces the bundled
    style of the same name (filesystem: :func:`list_styles_merged`; cloud: S3
    listings in ``shared.user_library``).
    """
    seen: set[str] = set()
    result: list[dict] = []
    for group in groups:
        for item in group:
            if item["name"] not in seen:
                seen.add(item["name"])
                result.append(item)
    return result


def filter_styles(
    styles: list[dict],
    pinned_names: list[str],
    include_all: bool = False,
    default_name: str = "",
) -> list[dict]:
    """Add pinned/default/source metadata and optionally filter a resource listing.

    Pure function — no I/O. Reads only ``name`` and ``source``, so it serves styles,
    structure guides and writing guides alike. Usable by both MCP Local (filesystem)
    and MCP Server (S3) since retrieval is the caller's responsibility.

    Args:
        styles: List of resource dicts. Each must have ``name``. May already
            have ``source``; defaults to ``"builtin"`` if absent.
        pinned_names: List of pinned names.
        include_all: If True, return everything. If False, return only
            pinned + user items (all when there are no pins, or when the
            pins match nothing and there are no user items).
        default_name: The name set as the default for this kind, or "" when
            none is set. The matching item gets ``default: True``.

    Returns:
        Items with ``pinned: bool``, ``default: bool`` and
        ``source: "builtin"|"user"`` added.
    """
    pin_set = set(pinned_names)
    result = []
    for s in styles:
        enriched = {**s, "pinned": s["name"] in pin_set, "default": s["name"] == default_name}
        if "source" not in enriched:
            enriched["source"] = "builtin"
        result.append(enriched)

    if include_all or not pin_set:
        return result

    # Pins whose styles no longer exist pin nothing, so they fall back to all as well.
    # A default that is not pinned stays visible, so switching pins never hides it.
    return [s for s in result if s["pinned"] or s["default"] or s["source"] == "user"] or result


HIDDEN_STYLES_HINT = (
    "Styles listed in other_styles exist too but were left out because they are "
    "neither pinned nor user-created. When the user names one of them, use it "
    "directly (apply_style accepts any name here) — do not report it as missing. "
    "Call list_styles(include_all=True) to see their descriptions."
)


def build_styles_listing(
    styles: list[dict],
    pinned_names: list[str],
    include_all: bool = False,
    default_name: str = "",
) -> dict[str, Any]:
    """Build the ``list_styles`` tool payload.

    Pure function shared by MCP Local and MCP Remote. Wraps
    :func:`filter_styles` and, whenever the pin filter actually dropped
    something, also returns the dropped names plus a hint so the agent
    never mistakes a hidden style for a non-existent one.

    Returns:
        ``{"styles": [...]}``; when styles were hidden, additionally
        ``"other_styles": [names]`` and ``"hint": str``.
    """
    shown = filter_styles(styles, pinned_names, include_all, default_name)
    shown_names = {s["name"] for s in shown}
    hidden = [s["name"] for s in styles if s["name"] not in shown_names]
    payload: dict[str, Any] = {"styles": shown}
    if hidden:
        payload["other_styles"] = hidden
        payload["hint"] = HIDDEN_STYLES_HINT
    return payload


# The file extension and the bundled fallback of each resource kind. A style has no
# bundled fallback: picking one of the eighteen would impose its rhetoric on every deck.
_KIND_SUFFIX = {"style": ".html", "structure": ".md", "writing": ".md"}
_BUNDLED_FALLBACK = {"structure": "by-audience"}

# Writing guides are per language, so the fallback is chosen by the deck's language
# rather than fixed. Keyed by the primary subtag of a BCP 47 tag.
_BUNDLED_WRITING_BY_LANGUAGE = {"ja": "ja"}


def _exists_in(name: str, dirs: Iterable[Path], suffix: str) -> bool:
    return any((d / f"{name}{suffix}").exists() for d in dirs)


def resolve_default(
    kind: str,
    explicit: str,
    dirs: list[Path],
    language: str = "",
) -> tuple[str, str, list[str]]:
    """Decide which guide or style to use, and say where the decision came from.

    One place for the whole precedence chain, so ``apply_style`` and ``apply_guides``
    cannot drift apart. Reads the pins and the ``default_<kind>`` out of ``state.json``
    itself; see design.md for the decision table this implements.

    Args:
        kind: ``"style"``, ``"structure"`` or ``"writing"``.
        explicit: The name the caller was given, or "" when it was given none.
        dirs: Ordered search directories, as ``get_<kind>s_dirs()`` returns them.
        language: The deck's BCP 47 language tag. Selects the bundled writing guide
            and is ignored for the other kinds.

    Returns:
        ``(name, origin, notices)``. ``origin`` is ``"argument"``, ``"default"``,
        ``"default-missing"`` or ``"unset"``. An empty ``name`` means "apply nothing",
        except with origin ``"argument"``, where it means the name the caller asked
        for does not exist and the caller must return an error without writing
        anything (REQ-3.6). A style resolving to "" is likewise an error, since there
        is no bundled style to fall back to.
    """
    suffix = _KIND_SUFFIX[kind]
    if explicit:
        # "" here is not "apply nothing" but "the caller named something absent".
        return (explicit if _exists_in(explicit, dirs, suffix) else "", "argument", [])

    if kind == "writing":
        fallback = _BUNDLED_WRITING_BY_LANGUAGE.get(language.split("-")[0].lower(), "")
    else:
        fallback = _BUNDLED_FALLBACK.get(kind, "")

    state = get_state()
    configured = state.get(f"default_{kind}", "")
    if not configured:
        notices = []
        if kind == "writing" and not language:
            notices.append(
                "deck.json has no language, so no writing guide was applied. "
                "Set it before apply_style, or name a writing guide."
            )
        return (fallback, "unset", notices)

    pinned = state.get(f"pinned_{kind}s", [])
    if _exists_in(configured, dirs, suffix):
        notices = []
        if pinned and configured not in pinned:
            notices.append(f"The default {kind} {configured!r} is not among the pinned ones.")
        return (configured, "default", notices)

    return (
        fallback,
        "default-missing",
        [f"The default {kind} {configured!r} no longer exists."],
    )

