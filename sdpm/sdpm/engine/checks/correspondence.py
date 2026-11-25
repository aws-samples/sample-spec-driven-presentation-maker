# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Facts about how a slide's forms correspond to its meaning.

Unlike the other checks in this package, this one reaches no pass-or-fail judgement:
it returns numbers, strings and lists, and never a boolean or a decision key. Whether
two same-shaped regions of different size are a defect depends on the deck, so the
call belongs to the reviewer reading the writing and structure guides, and a user who
replaces those guides must be able to overrule it. Deciding here would make this the
one rule they could not reach.

What a reviewer does with these facts is in `verify.md`.
"""

from __future__ import annotations

import html as _html
import re

# Kept identical to the expression the built-in style contract has always used, so
# a slide's count means the same thing as the density a style declares.
_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[\w%$€£¥+−-]+")
_DENSITY_RE = re.compile(r"<!--\s*Density:\s*(\d+)\s*-->")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# A region takes part in a prefix group only when its name ends in -<number>:
# "col-1" and "col-2" are two of a kind, "media" is one of a kind.
_INDEXED_NAME_RE = re.compile(r"^(.*)-(\d+)$")


def count_visible_words(text: str) -> int:
    """Count the words a viewer sees, in slide text or in a fragment of style HTML.

    Tags are dropped and entities resolved first, so the same function serves a
    slide's plain text and a style's sample markup.

    This counts space-delimited tokens, which is what a style's density marker is
    calibrated against. An unspaced script counts far lower for the same amount of
    reading, so :func:`count_visible_characters` is what carries the signal there.
    """
    return len(_WORD_RE.findall(_html.unescape(_TAG_RE.sub(" ", text))))


def count_visible_characters(text: str) -> int:
    """Count the visible characters a viewer sees, ignoring whitespace.

    Script-independent, so it stays comparable where the word count does not: a
    Japanese sentence and its English translation differ by an order of magnitude in
    words and by far less in characters.
    """
    stripped = _html.unescape(_TAG_RE.sub(" ", text))
    return len("".join(stripped.split()))


def density_limit(art_direction: str) -> int | None:
    """The word budget a style declares, or None when it declares none."""
    found = _DENSITY_RE.search(art_direction)
    return int(found.group(1)) if found else None


def density_sample_characters(art_direction: str) -> int | None:
    """Visible characters on the fullest of the style's own sample slides.

    The declared limit counts space-delimited words, so it says nothing usable about a
    language that does not space them. The style's samples are the same content drawn
    the way the style intends, so their character count is a reference a slide in any
    script can be held against. None when the style has no sample slides.
    """
    body = _COMMENT_RE.sub("", art_direction.split("<body", 1)[-1])
    slides = re.split(r'<div class="slide[\s"]', body)[1:]
    counts = [count_visible_characters(slide) for slide in slides]
    return max(counts) if counts else None


def _box(element: dict) -> tuple[float, float, float, float] | None:
    """An element's rectangle, accepting both the w/h and the width/height spelling."""
    x, y = element.get("x"), element.get("y")
    w = element.get("w", element.get("width"))
    h = element.get("h", element.get("height"))
    values = (x, y, w, h)
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in values):
        return None
    return values


def _overlap_area(a: tuple[float, float, float, float], b: dict) -> float:
    ax, ay, aw, ah = a
    wide = min(ax + aw, b["x"] + b["w"]) - max(ax, b["x"])
    tall = min(ay + ah, b["y"] + b["h"]) - max(ay, b["y"])
    return wide * tall if wide > 0 and tall > 0 else 0.0


def _owning_region(box: tuple[float, float, float, float], regions: list[dict]) -> dict | None:
    """The region an element belongs to: the one it overlaps most (REQ-11.4).

    None means it overlaps no region at all, which is a worse placement error than
    overflowing one — so a caller must report that case rather than skip it.
    """
    overlapping = [(r, _overlap_area(box, r)) for r in regions]
    best = max(overlapping, key=lambda pair: pair[1], default=(None, 0.0))
    return best[0] if best[1] > 0 else None


def _element_text(element: dict) -> str:
    """An element's text, whether it is a string or a list of paragraphs."""
    text = element.get("text")
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        parts = [
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in text
        ]
        return " ".join(p for p in parts if isinstance(p, str))
    return ""


def _overflow(box: tuple[float, float, float, float], region: dict) -> dict[str, float]:
    """How far an element sticks out of its region, per edge, omitting edges inside it."""
    x, y, w, h = box
    edges = {
        "left": region["x"] - x,
        "top": region["y"] - y,
        "right": (x + w) - (region["x"] + region["w"]),
        "bottom": (y + h) - (region["y"] + region["h"]),
    }
    return {edge: round(amount, 2) for edge, amount in edges.items() if amount > 0}


def _prefix_sizes(regions: list[dict]) -> dict[str, list[dict]]:
    """Per prefix, the w and h of each region sharing it."""
    sizes: dict[str, list[dict]] = {}
    for region in regions:
        found = _INDEXED_NAME_RE.match(region["name"])
        if not found:
            continue
        sizes.setdefault(found.group(1), []).append(
            {"name": region["name"], "w": region["w"], "h": region["h"]}
        )
    return {prefix: entries for prefix, entries in sizes.items() if len(entries) > 1}


def _stacked_groups(regions: list[dict]) -> list[dict]:
    """Regions whose y ranges overlap are one row; rows come in y order (REQ-11.4)."""
    groups: list[list[dict]] = []
    for region in sorted(regions, key=lambda r: r["y"]):
        for group in groups:
            if any(region["y"] < g["y"] + g["h"] and g["y"] < region["y"] + region["h"] for g in group):
                group.append(region)
                break
        else:
            groups.append([region])
    return [
        {"y": group[0]["y"], "regions": len(group), "names": [g["name"] for g in group]}
        for group in groups
    ]


def _repeated_text(elements: list[dict], regions: list[dict]) -> list[dict]:
    """Strings that appear more than once on one slide, and where (REQ-11.4)."""
    seen: dict[str, list[str | None]] = {}
    for element in elements:
        if "type" not in element:
            continue
        text = _element_text(element).strip()
        if not text:
            continue
        box = _box(element)
        region = _owning_region(box, regions) if box else None
        seen.setdefault(text, []).append(region["name"] if region else None)
    return [
        {"text": text, "regions": places}
        for text, places in seen.items()
        if len(places) > 1
    ]


def correspondence_facts(slides_data: dict, art_direction: str = "") -> dict:
    """Facts about each slide's forms, for a reviewer to judge.

    PPTX decks only (REQ-11.9): an HTML deck marks its regions with a data-region
    attribute inside the slide HTML, so the slides JSON carries no coordinates to
    compare and there is nothing here to measure.

    Args:
        slides_data: The deck's slides JSON, as the build path reads it.
        art_direction: The deck's specs/art-direction.html, for its density marker.

    Returns:
        ``{"density_limit", "density_sample_characters", "slides"}`` for a PPTX deck.
        For an HTML deck, ``{"slides": [], "note": ...}`` saying what it applies to.
    """
    from sdpm.engine.schema import deck_output_format
    from sdpm.engine.schema.regions import extract_regions

    if deck_output_format(slides_data) == "html":
        return {
            "slides": [],
            "note": "Correspondence facts cover PPTX decks: an HTML deck keeps its "
            "regions in the slide HTML, so the slides JSON has no coordinates.",
        }

    facts = []
    for number, slide in enumerate(slides_data.get("slides", []), start=1):
        if not isinstance(slide, dict):
            continue
        elements = [e for e in slide.get("elements") or [] if isinstance(e, dict)]
        regions = extract_regions(slide)
        slug = slide.get("id", "")
        slide_text = " ".join(_element_text(e) for e in elements if "type" in e)
        outside = []
        for index, element in enumerate(elements):
            box = _box(element) if "type" in element else None
            if box is None:
                continue
            region = _owning_region(box, regions)
            if region is None:
                # Not an overflow but a placement with no home at all. Reported with
                # region null, because skipping it made the worst case read as clean.
                if regions:
                    outside.append(
                        {
                            "element": {"index": index, "type": element.get("type", "")},
                            "region": None,
                            "overflow": {},
                        }
                    )
                continue
            over = _overflow(box, region)
            if over:
                outside.append(
                    {
                        "element": {"index": index, "type": element.get("type", "")},
                        "region": region["name"],
                        "overflow": over,
                    }
                )
        facts.append(
            {
                "slide": f"page{number:02d}({slug})" if slug else f"page{number:02d}",
                "visible_words": count_visible_words(slide_text),
                "visible_characters": count_visible_characters(slide_text),
                "outside_regions": outside,
                "region_sizes_by_prefix": _prefix_sizes(regions),
                "stacked_region_groups": _stacked_groups(regions),
                "repeated_text": _repeated_text(elements, regions),
            }
        )
    return {
        "density_limit": density_limit(art_direction),
        "density_sample_characters": density_sample_characters(art_direction),
        "slides": facts,
    }
