"""Catch a text build that asks for more than one ``p:bldP`` can say.

``text.sequence`` and ``text.level`` are two names for the same PowerPoint
fact. One shape and effect group has exactly one ``p:bldP``, and both fields
write into its ``@build``/``@bldLvl`` attributes, so an effect that sets both
leaves only one of them in the file. These are the catalog's own recorded
forms:

=============================  ============================
authored                       ``p:bldP`` attributes
=============================  ============================
``sequence.byParagraph``       ``build="p"``
``level.byParagraphLevelN``    ``build="p" bldLvl="N"``
``sequence.allAtOnce``         ``build="allAtOnce"``
``level.allParagraphLevels``   ``build="allAtOnce"``
``sequence.asOneObject``       (none)
``level.asOneObject``          (none)
=============================  ============================

Two consequences, both measured by generating a package and reading it back
rather than reasoned from the table:

1. **A pair loses a field, and which one it loses depends on the values.**
   ``byParagraph`` + ``byParagraphLevel1`` comes back as the level;
   ``allAtOnce`` + ``allParagraphLevels`` comes back as the sequence;
   ``asOneObject`` + ``asOneObject`` comes back as neither. So this check does
   not predict a winner — it says the pair cannot survive and asks the author
   to mean one thing.

2. **A value that records no attributes cannot round-trip at all.**
   ``asOneObject`` writes a bare ``p:bldP``, which is indistinguishable from
   the build PowerPoint writes by default, so the whole ``text`` block is
   absent on read even when it is the only field set.

Each of the other values *does* survive on its own. The loss is irreducible
rather than a reader shortcoming: the bytes left in the package cannot
distinguish "the author wrote a level" from "the author wrote both".

The writer already **rejects** a pair that contradicts itself (``asOneObject``
against ``byParagraphLevel2``). A pair that merely agrees generates a correct
package, so these are warnings and not errors: nothing is broken, but the
author's JSON stops matching itself after an import and the quieter field
disappears without anyone being told.

**It costs nothing when no one uses a text build.** An effect with no ``text``
block is skipped, which is every effect in an ordinary deck, since animations
are off by default.
"""

from __future__ import annotations

from typing import Any, Iterator, Mapping

#: Values whose recorded ``p:bldP`` form carries no attributes at all, and so
#: cannot be told apart from PowerPoint's default build when read back.
ATTRIBUTE_FREE = ("asOneObject",)


def _effects(slide: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Yield ``(json path, effect)`` for every effect on a slide.

    Walks both sequence kinds, because an interactive sequence's effects carry
    exactly the same ``text`` block as a main-sequence one.
    """
    animations = slide.get("animations")
    if not isinstance(animations, Mapping):
        return
    for index, effect in enumerate(animations.get("mainSequence") or []):
        if isinstance(effect, Mapping):
            yield f"animations.mainSequence[{index}]", effect
    for s_index, sequence in enumerate(animations.get("interactiveSequences") or []):
        if not isinstance(sequence, Mapping):
            continue
        for index, effect in enumerate(sequence.get("effects") or []):
            if isinstance(effect, Mapping):
                yield f"animations.interactiveSequences[{s_index}].effects[{index}]", effect


def _label(slide: Mapping[str, Any], position: int) -> str:
    """Name a slide the way its author refers to it: by slug when it has one."""
    slug = slide.get("id")
    return f"slide {slug!r}" if isinstance(slug, str) and slug else f"slide {position + 1}"


def _named(effect: Mapping[str, Any], path: str) -> str:
    effect_id = effect.get("id")
    return f"effect {effect_id!r}" if isinstance(effect_id, str) and effect_id else path


def check_text_build(slides_data: Mapping[str, Any]) -> list[str]:
    """Return a warning for every text build that cannot survive a round-trip."""
    slides = [s for s in (slides_data.get("slides") or []) if isinstance(s, Mapping)]
    warnings: list[str] = []
    for position, slide in enumerate(slides):
        for path, effect in _effects(slide):
            text = effect.get("text")
            if not isinstance(text, Mapping):
                continue
            where = f"{_label(slide, position)} {_named(effect, path)}"
            sequence, level = text.get("sequence"), text.get("level")

            if sequence is not None and level is not None:
                warnings.append(
                    f"{where}: text.sequence {sequence!r} and text.level {level!r} both write "
                    f"the one p:bldP this effect has, so only one of them is in the package "
                    f"afterwards and which one depends on the values ({path}.text). Set "
                    f"whichever you mean and drop the other — each round-trips on its own."
                )

            for field, value in (("sequence", sequence), ("level", level)):
                if isinstance(value, str) and value in ATTRIBUTE_FREE:
                    warnings.append(
                        f"{where}: text.{field} {value!r} records no p:bldP attributes, so it "
                        f"cannot be told apart from the build PowerPoint writes by default and "
                        f"the whole text block will be absent when the deck is read back "
                        f"({path}.text.{field}). The animation still plays as asked; only the "
                        f"round-trip loses it."
                    )
    return warnings


def text_build_summary(slides_data: Mapping[str, Any]) -> dict[str, Any]:
    """Per-slide text-build inventory, for diagnosing a warning."""
    slides = [s for s in (slides_data.get("slides") or []) if isinstance(s, Mapping)]
    return {
        "slides": [
            {
                "slide": _label(slide, position),
                "textBuilds": [
                    {
                        "path": path,
                        "sequence": (effect.get("text") or {}).get("sequence"),
                        "level": (effect.get("text") or {}).get("level"),
                        "unit": (effect.get("text") or {}).get("unit"),
                    }
                    for path, effect in _effects(slide)
                    if isinstance(effect.get("text"), Mapping)
                ],
            }
            for position, slide in enumerate(slides)
        ],
        "warnings": check_text_build(slides_data),
    }
