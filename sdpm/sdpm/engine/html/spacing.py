# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""CJK↔Latin auto spacing for HTML slides — the same typography the PPTX builder applies.

``space_section(section)`` rewrites the text nodes of one parsed ``<section>`` in place
with ``sdpm.utils.text.normalize_spacing`` and adds the space at the boundary between
inline elements too (``<strong>AWS</strong>の`` → ``AWS`` and ``の`` apart), as the PPTX
builder does across styled segments. Only text changes; attribute values never do.

A run of text continues through inline elements and stops at any other element (block
elements, ``<br>``, images): no space is added across such a boundary. Code and
preformatted text (``pre`` ``code`` ``kbd`` ``samp``), ``script`` ``style`` ``textarea``
and inline ``svg`` / ``math`` keep their text as written; they also end a run.
"""
from __future__ import annotations

from sdpm.utils.text import is_cjk_punctuation, is_fullwidth, normalize_spacing

# Text inside these is left verbatim (code, raw text, drawn text whose width is fixed).
VERBATIM_TAGS = frozenset({"pre", "code", "kbd", "samp", "script", "style", "textarea", "svg", "math"})

# Text runs continue through these; every other element ends the run.
INLINE_TAGS = frozenset({
    "a", "abbr", "b", "bdi", "bdo", "cite", "data", "del", "dfn", "em", "font", "i", "ins",
    "label", "mark", "q", "ruby", "rb", "rp", "rt", "s", "small", "span", "strong", "sub",
    "sup", "time", "u", "var",
})


def _is_ascii(c: str) -> bool:
    return "\x21" <= c <= "\x7e"


def _is_wide(c: str) -> bool:
    return is_fullwidth(c) and not is_cjk_punctuation(c)


def _needs_space(last: str, first: str) -> bool:
    return (_is_ascii(last) and _is_wide(first)) or (_is_wide(last) and _is_ascii(first))


class _Run:
    """The text slots of the current run, so a boundary space can go on the previous one."""

    def __init__(self) -> None:
        self.prev: tuple[object, str] | None = None  # (element, "text" | "tail")

    def end(self) -> None:
        self.prev = None

    def add(self, el, attr: str) -> None:
        value = getattr(el, attr)
        if not value:
            return
        value = normalize_spacing(value)
        setattr(el, attr, value)
        if self.prev is not None:
            prev_el, prev_attr = self.prev
            prev_value = getattr(prev_el, prev_attr)
            if _needs_space(prev_value[-1], value[0]):
                setattr(prev_el, prev_attr, prev_value + " ")
        self.prev = (el, attr)


def _walk(el, run: _Run) -> None:
    tag = el.tag if isinstance(el.tag, str) else None  # None: comment / processing instruction
    if tag is not None:
        name = tag.split("}")[-1].lower()
        inline = name in INLINE_TAGS
        if not inline:
            run.end()
        if name in VERBATIM_TAGS:
            run.end()
        else:
            run.add(el, "text")
            for child in el:
                _walk(child, run)
            if not inline:
                run.end()
    if el.tail:
        run.add(el, "tail")


def space_section(section) -> None:
    """Insert CJK↔Latin spaces into the text of ``section`` (an lxml element), in place."""
    run = _Run()
    run.add(section, "text")
    for child in section:
        _walk(child, run)
