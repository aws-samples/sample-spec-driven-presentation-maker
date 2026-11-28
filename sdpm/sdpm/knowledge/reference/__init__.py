# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Reference: unified access to design patterns and example datasets.

Reference data is used to guide AI-generated slide content.
See docs/internal/DATASET_COMPLIANCE.md for dataset provenance.

Reference: unified access to design patterns, components, schemas, rules, and reviews."""
import json
import re
from collections.abc import Iterable
from pathlib import Path, PureWindowsPath
from typing import Any

from sdpm.config import REFERENCES_DIR
from sdpm.knowledge.reference.providers import FileProvider, ReferenceProvider  # noqa: F401

# Package-bundled styles directory (for user-local style search fallback).
BUNDLED_STYLES_DIR = REFERENCES_DIR / "examples" / "styles"

# Package-bundled guides directory: the guide collection's last source.
BUNDLED_GUIDES_DIR = REFERENCES_DIR / "guides"

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


# ---------------------------------------------------------------------------
# Guides: one collection, classified by role tags
# ---------------------------------------------------------------------------

#: Every role tag a guide may carry, and the whole vocabulary. Closed on purpose: a tag
#: outside it is reported as invalid metadata instead of silently matching nothing.
TAGS = (
    "orchestrator",
    "composer",
    "composer-pptx",
    "composer-html",
    "style",
    "translate",
    "management",
)

#: Cap on one ``read_guides`` result. Kiro CLI V3 moves a tool result of 30,000+
#: characters to a file and shows the model only its ends; Claude Code caps MCP output
#: too. 25,000 leaves room for a larger group. ``tests/test_entry_tools.py`` measures
#: every surface's entry payload against this same number.
GUIDE_RESULT_BUDGET = 25_000

#: Cap on one guide's text, derived from the budget rather than chosen: a guide nobody
#: can read in one call would be reported as valid and then arrive truncated. The 1,000
#: covers the JSON framing and the heading (measured: 513 for the largest bundled guide).
#: UTF-8 bytes are never fewer than characters, so a byte cap bounds the character count.
#: The largest bundled guide is 22,375 bytes.
GUIDE_MAX_BYTES = GUIDE_RESULT_BUDGET - 1_000

#: Cap on one guide's description and on a guide name. Every description rides in every
#: listing, and a listing rides in every ``start_*`` return, so an unbounded description
#: inflates that payload as surely as a body would. The longest bundled one is 193.
GUIDE_DESCRIPTION_MAX = 400
GUIDE_NAME_MAX = 100

_GUIDE_KEYS = ("description", "tags", "always")
_FM_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(.*)$")


def is_guide_name(name: Any) -> bool:
    """Whether ``name`` names one guide.

    Stricter than :func:`is_style_name`, which deliberately admits ``acme.v2``: a guide
    name is also a key in ``start_*``'s ``guides`` map, so it carries no ``.`` at all.
    Pure — a bad name is rejected before it ever becomes a path or an S3 key.
    """
    return (
        isinstance(name, str)
        and name.strip() == name != ""
        and len(name) <= GUIDE_NAME_MAX
        and "." not in name
        and not any(ord(ch) < 32 or ord(ch) == 127 for ch in name)
        and PureWindowsPath(name).name == name  # Windows rules also catch "/" and "C:"
    )


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str] | str:
    """Split a guide into its frontmatter entries and its body, or name the failure.

    Returns ``({key: value}, body)``, where a block sequence arrives as ``list[str]``
    and everything else as the raw scalar, so the per-key checks stay in one place.
    Returns the string ``"frontmatter"`` when the block itself is outside the grammar:
    missing, unterminated, commented, indented, duplicated, or carrying a null value.

    A blank line inside the block is allowed and carries nothing; it is the one form
    the grammar neither spells out nor excludes, and rejecting it would only produce a
    confusing diagnostic for a harmless authoring habit.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "frontmatter"
    close = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if close is None:
        return "frontmatter"

    entries: dict[str, Any] = {}
    sequence: list[str] | None = None
    for raw in lines[1:close]:
        if not raw.strip():
            continue
        if raw.lstrip().startswith("- "):
            if sequence is None:
                return "frontmatter"
            sequence.append(raw.lstrip()[2:].strip().strip('"'))
            continue
        if raw != raw.lstrip():
            return "frontmatter"  # indented and not a sequence item: nested map or folded scalar
        match = _FM_KEY_RE.match(raw)
        if match is None:
            return "frontmatter"  # a comment, a bare word, anything that is not `key: value`
        key, value = match.group(1), match.group(2).strip()
        if key in entries:
            return "frontmatter"  # duplicate key
        if value:
            sequence = None
            entries[key] = value
        elif key == "tags":
            sequence = []
            entries[key] = sequence
        else:
            return "frontmatter"  # a null value
    return entries, _strip_frontmatter(text)


def _parse_tags(raw: Any) -> list[str] | None:
    """Tag values from a flow or block sequence, or ``None`` when the value is neither."""
    if isinstance(raw, list):
        return raw
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [item.strip().strip('"') for item in inner.split(",")] if inner else []
    return None


def guide_meta(name: str, text: str) -> dict[str, Any]:
    """One guide's metadata, or the category under which it is invalid.

    Returns ``{"name", "description", "tags", "always", "body"}`` for a valid guide, and
    ``{"name", "category"}`` for an invalid one, naming the first failed check in this
    order: ``name``, ``frontmatter``, ``unknown-key``, ``description``, ``tags``,
    ``tag-value``, ``always``, ``size``. A guide breaking several is reported once, so a
    caller gets one actionable cause rather than a list.

    ``body`` is the frontmatter-stripped text, so this one parse serves both the listing
    and the automatic hand-over and the two cannot disagree about what the text is.

    Takes the text, not a path: the remote passes an S3 body and the local a file read.
    """
    def invalid(category: str) -> dict[str, Any]:
        return {"name": name, "category": category}

    if not is_guide_name(name):
        return invalid("name")

    parsed = _parse_frontmatter(text)
    if isinstance(parsed, str):
        return invalid(parsed)
    entries, body = parsed

    if any(key not in _GUIDE_KEYS for key in entries):
        return invalid("unknown-key")

    description = entries.get("description")
    if not isinstance(description, str) or not description.strip('"').strip():
        return invalid("description")
    if len(description.strip('"').strip()) > GUIDE_DESCRIPTION_MAX:
        return invalid("description")

    raw_tags = entries.get("tags")
    if raw_tags is None:
        return invalid("tags")
    tags = _parse_tags(raw_tags)
    if not tags:
        return invalid("tags")
    if any(tag not in TAGS for tag in tags):
        return invalid("tag-value")

    always = entries.get("always", "false")
    if always not in ("true", "false"):
        return invalid("always")

    if len(text.encode("utf-8")) > GUIDE_MAX_BYTES:
        return invalid("size")

    return {
        "name": name,
        "description": description.strip('"').strip(),
        "tags": tags,
        "always": always == "true",
        "body": body,
    }


def build_collection(sources: list[tuple[str, list[dict[str, str]]]]) -> dict[str, Any]:
    """Merge labelled guide groups into the one collection every guide surface reads.

    Each group is ``(source, entries)`` — ``source`` being ``"user"`` or ``"builtin"``,
    each entry ``{"name", "location", "text"}``. Pass the user's group first: the first
    valid entry of each name wins, so a user guide shadows the bundled guide of that name
    for listing, read-by-name and automatic hand-over alike.

    Returns ``{"valid": {name: meta}, "invalid": [{"path", "category"}], "warnings":
    [{"name", "warning"}]}``. An invalid entry never wins a name — resolution continues to
    the next source — and never fails the call: the valid guides beside it are still
    listed, read and handed over.

    An entry whose name a previous group already won is parsed only to compare: shadowing
    is the one way to make a role lose a guide it was handed automatically, and a reader
    who takes a bundled name without its ``always`` or its tags gets no error anywhere
    else. What the shadowed guide no longer gives any role becomes a warning. Its own
    metadata is not reported otherwise, and a shadowed entry that is itself invalid is
    passed over: nothing can be said about what it would have given.

    Pure function. The caller supplies the groups, which is what lets the remote merge S3
    bodies and the local merge file reads through this same rule.
    """
    valid: dict[str, dict[str, Any]] = {}
    invalid: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for source, entries in sources:
        for entry in entries:
            name = entry["name"]
            if name in valid:
                lost = _shadowing_loss(valid[name], guide_meta(name, entry["text"]), source)
                if lost:
                    warnings.append({"name": name, "warning": lost})
                continue
            meta = guide_meta(name, entry["text"])
            if "category" in meta:
                invalid.append({"path": entry["location"], "category": meta["category"]})
                continue
            valid[name] = {**meta, "source": source}
    return {"valid": valid, "invalid": invalid, "warnings": warnings}


def _shadowing_loss(winner: dict[str, Any], shadowed: dict[str, Any], shadowed_source: str) -> str:
    """What no role gets any more because ``winner`` took ``shadowed``'s name, or "".

    Only a loss is worth a warning. Taking the name of a guide to say the same thing
    differently is the point of shadowing; dropping its ``always`` or one of its tags is
    not, because the role that was handed it keeps asking and no longer receives it.
    """
    if "category" in shadowed:
        return ""
    losses = []
    if shadowed["always"] and not winner["always"]:
        losses.append("it was handed over automatically and yours is not (no always: true)")
    missing = [tag for tag in shadowed["tags"] if tag not in winner["tags"]]
    if missing:
        losses.append(f"it was tagged {', '.join(missing)} and yours is not")
    if not losses:
        return ""
    return f"shadows the {shadowed_source} guide of this name, but " + "; ".join(losses)


#: What a listing shows about a guide. The body is deliberately absent: the listing rides
#: inside every ``start_*`` return, so carrying 31 bodies there would duplicate the prompt.
_LISTING_FIELDS = ("name", "description", "source", "tags", "always")


def _selected(collection: dict[str, Any], tags: set[str]) -> list[dict[str, Any]]:
    """Entries whose tags intersect ``tags``, by name. An empty set selects everything."""
    return [
        meta
        for name, meta in sorted(collection["valid"].items())
        if not tags or set(meta["tags"]) & tags
    ]


def select_guides(collection: dict[str, Any], tags: set[str]) -> list[dict[str, Any]]:
    """What a caller carrying ``tags`` can see, in ascending name order.

    A guide is selected when its tags intersect the call's tag set, so a guide tagged for
    one composer mode only still appears in that mode's listing. An empty set — a listing
    request with no role — selects every guide.
    """
    return [{key: meta[key] for key in _LISTING_FIELDS} for meta in _selected(collection, tags)]


def always_guides(collection: dict[str, Any], tags: set[str]) -> dict[str, str]:
    """``name -> body`` for the selected guides a caller carrying ``tags`` is handed.

    The same selection as :func:`select_guides`, narrowed to the guides whose frontmatter
    claims ``always``. That claim applies to every tag the guide carries; there is no
    per-tag variant. Ascending name order, so the map and its joined form agree.
    """
    return {
        meta["name"]: meta["body"]
        for meta in _selected(collection, tags)
        if meta["always"]
    }


def guides_by_name(collection: dict[str, Any], names: Iterable[str]) -> dict[str, str]:
    """``name -> body`` for each requested guide.

    The only way to address a guide: a caller passes back the identifier a listing showed
    or a ``start_*`` named as mandatory. A user's guide resolves here exactly as a bundled
    one does, so shadowing holds for reading as well as for listing.

    Raises ``FileNotFoundError`` naming what the collection does hold — the same failure
    the bundled reader gives, with the merged names instead of one directory's.
    """
    valid = collection["valid"]
    bodies: dict[str, str] = {}
    for name in names:
        if name not in valid:
            available = ", ".join(sorted(valid))
            raise FileNotFoundError(f"'{name}' is not a guide. Available: {available}")
        bodies[name] = valid[name]["body"]
    return bodies


def guides_listing(collection: dict[str, Any], role: str = "") -> dict[str, Any]:
    """The ``list_guides`` payload: what a role can see, or everything when ``role`` is "".

    An unknown role is an error rather than an empty list: a typo that silently returned
    nothing would read as "this role has no guides".
    """
    if role and role not in TAGS:
        return {"error": f"role must be one of {list(TAGS)}, got '{role}'"}
    payload: dict[str, Any] = {
        "guides": select_guides(collection, {role} if role else set()),
        "role": role,
    }
    if collection["invalid"]:
        payload["invalid"] = collection["invalid"]
    if collection.get("warnings"):
        payload["warnings"] = collection["warnings"]
    return payload


def join_guides(guides: dict[str, str]) -> str:
    """One text carrying every handed-over guide, titled and in ascending name order.

    Byte-identical for equal input: the order is the sorted names and each body is
    normalised to one trailing newline, so a prompt built from it is reproducible.
    """
    return "\n".join(f"# Guide: {name}\n\n{guides[name].rstrip()}\n" for name in sorted(guides))


def _spec_first(collection: dict[str, Any], name: str) -> tuple[bool, str]:
    """Sort key putting the guides a role cannot work without at the front.

    A bundled guide claiming ``always`` is the format spec and the checks — a composer
    that loses ``slide-json-spec`` cannot produce a valid slide at all, while a guide of
    the user's own carries a preference. So when a result has to shed something, this
    order decides what, and the spec is never what goes.
    """
    meta = collection["valid"][name]
    return (not (meta["always"] and meta["source"] != "user"), name)


def guides_result(
    collection: dict[str, Any],
    names: Iterable[str],
    budget: int = GUIDE_RESULT_BUDGET,
) -> dict[str, Any]:
    """The ``read_guides`` payload: the guides that fit one result, and what did not.

    A result past the budget is filed away by the client, which hands the model the ends
    of a guide it was told to read and says nothing. So the result is filled to the budget
    instead, in :func:`_spec_first` order, and whatever did not fit is named. A caller
    that can see what it is missing can act; a silently truncated one cannot.

    What was left out is said **twice**: under ``not_included`` for a caller reading the
    keys, and at the end of ``guides_text`` itself. A surface that composes a system prompt
    keeps only the text (``agent/modes`` picks ``guides_text``), so a note living only in a
    key would reach that model as nothing at all — the same silence this function exists to
    end. Carrying it in the text means it travels wherever the text does.

    ``GUIDE_MAX_BYTES`` is derived from this budget, so one guide always fits and the
    fill never returns nothing. A guide whose JSON escaping alone crosses the budget is
    still returned, with the note naming it — being told is better than being cut.

    Every guide surface routes its read through here, so one rule covers the local tools,
    the CLI and the remote server rather than three.
    """
    bodies = guides_by_name(collection, names)
    ordered = sorted(bodies, key=lambda name: _spec_first(collection, name))
    kept = list(ordered)
    while True:
        text = join_guides({name: bodies[name] for name in kept})
        left = ordered[len(kept):]
        payload: dict[str, Any] = {}
        if left:
            note = (
                f"{len(left)} guide(s) did not fit this result's {budget:,}-character budget: "
                f"{', '.join(left)}. Call read_guides again with those names to read them."
            )
            payload = {"guides_text": f"{text}\n# Not included\n\n{note}\n",
                       "not_included": left, "note": note}
        else:
            payload = {"guides_text": text}
        if len(kept) <= 1 or len(json.dumps(payload, ensure_ascii=False)) <= budget:
            return payload
        kept.pop()


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
) -> list[dict]:
    """Add pinned/source metadata and optionally filter styles.

    Pure function — no I/O. Usable by both MCP Local (filesystem) and
    MCP Server (S3) since style retrieval is the caller's responsibility.

    Args:
        styles: List of style dicts. Each must have ``name``. May already
            have ``source``; defaults to ``"builtin"`` if absent.
        pinned_names: List of pinned style names.
        include_all: If True, return all styles. If False, return only
            pinned + user styles (all when there are no pins, or when the
            pins match no style and there are no user styles).

    Returns:
        Styles with ``pinned: bool`` and ``source: "builtin"|"user"`` added.
    """
    pin_set = set(pinned_names)
    result = []
    for s in styles:
        enriched = {**s, "pinned": s["name"] in pin_set}
        if "source" not in enriched:
            enriched["source"] = "builtin"
        result.append(enriched)

    if include_all or not pin_set:
        return result

    # Pins whose styles no longer exist pin nothing, so they fall back to all as well.
    return [s for s in result if s["pinned"] or s["source"] == "user"] or result


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
    shown = filter_styles(styles, pinned_names, include_all)
    shown_names = {s["name"] for s in shown}
    hidden = [s["name"] for s in styles if s["name"] not in shown_names]
    payload: dict[str, Any] = {"styles": shown}
    if hidden:
        payload["other_styles"] = hidden
        payload["hint"] = HIDDEN_STYLES_HINT
    return payload
