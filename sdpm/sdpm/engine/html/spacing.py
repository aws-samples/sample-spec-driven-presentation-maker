# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""CJK↔Latin auto spacing for HTML slides — the same typography the PPTX builder applies.

``space_section(section)`` rewrites the text nodes of one parsed ``<section>`` in place
with ``sdpm.utils.text.spacing_points``, computed over each run of text joined up, so
inline elements get the same spaces as the PPTX builder gives styled segments
(``<strong>AWS</strong>の`` → ``AWS`` and ``の`` apart). A space at a boundary goes at
the end of the text before it. Only text changes; attribute values never do.

A run of text continues through inline elements and stops at any other element (block
elements, ``<br>``, images): no space is added across such a boundary. Code and
preformatted text (``pre`` ``code`` ``kbd`` ``samp``), ``script`` ``style`` ``textarea``,
inline ``svg`` / ``math``, superscript and subscript (``sup`` ``sub``) and ruby text
(``rt`` ``rp``) keep their text as written; they also end a run.
"""
from __future__ import annotations

from sdpm.utils.text import spacing_points

# Text inside these is left verbatim (code, raw text, drawn text whose width is fixed).
VERBATIM_TAGS = frozenset({
    "pre", "code", "kbd", "samp", "script", "style", "textarea", "svg", "math", "sup", "sub", "rt", "rp",
})

# Text runs continue through these; every other element ends the run.
INLINE_TAGS = frozenset({
    "a", "abbr", "b", "bdi", "bdo", "cite", "data", "del", "dfn", "em", "font", "i", "ins",
    "label", "mark", "q", "ruby", "rb", "s", "small", "span", "strong", "time", "u", "var",
})


class _Run:
    """The text slots of the current run; spaced together when the run ends."""

    def __init__(self) -> None:
        self.slots: list[tuple[object, str]] = []  # (element, "text" | "tail")

    def add(self, el, attr: str) -> None:
        if getattr(el, attr):
            self.slots.append((el, attr))

    def end(self) -> None:
        slots, self.slots = self.slots, []
        if not slots:
            return
        values = [getattr(el, attr) for el, attr in slots]
        owner, start = [], []
        for idx, value in enumerate(values):
            start.append(len(owner))
            owner.extend([idx] * len(value))
        inserts: dict[int, list[int]] = {}
        for p in spacing_points("".join(values)):
            inserts.setdefault(owner[p], []).append(p - start[owner[p]] + 1)
        for idx, cuts in inserts.items():
            value = values[idx]
            for cut in sorted(cuts, reverse=True):
                value = value[:cut] + " " + value[cut:]
            el, attr = slots[idx]
            setattr(el, attr, value)


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
    run.end()
