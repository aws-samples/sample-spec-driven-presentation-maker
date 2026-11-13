"""Morph identities that pair with nothing on the adjacent slide.

A ``morphId`` has exactly one job: to tell PowerPoint that *this* shape and the
same-named shape on the neighbouring slide are the same object, so Morph moves
it instead of cross-fading it. An id that matches nothing therefore does
nothing — it is not a weaker pairing, it is no pairing at all, and PowerPoint
falls back to its own heuristics without saying so.

Every other ``morphId`` rule is checked **within one slide**: the identity
validator rejects a duplicate or malformed id on the slide it appears on. The
thing it cannot see is the half that lives in the next file, and that is the
half parallel composition breaks. One composer owns slide 3 and another owns
slide 4; neither can read the other's draft; a single typo
(``pricing-card`` against ``price-card``) builds cleanly and silently animates
the wrong way.

So this check is deck-level and it is the only morph rule that has to be.

It emits warnings only — it does not block generation, because an unpaired id
produces a valid package and a deck may legitimately be mid-edit.

**It costs nothing when no one uses Morph.** A deck with no Morph transition and
no ``morphId`` returns immediately, which is the ordinary case: animations and
transitions are off by default and most decks never name a morph identity.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

MORPH_EFFECT = "morph"


def _morph_ids(slide: Mapping[str, Any]) -> dict[str, str]:
    """Return ``morphId -> JSON path`` for one slide.

    Scoped exactly as the identity validator scopes it — top-level ``elements``
    plus ``placeholders`` values — so the two cannot disagree about which ids
    exist on a slide.
    """
    found: dict[str, str] = {}

    def collect(value: Any, path: str) -> None:
        if not isinstance(value, Mapping):
            return
        morph_id = value.get("morphId")
        if isinstance(morph_id, str) and morph_id and morph_id not in found:
            found[morph_id] = path

    for index, element in enumerate(slide.get("elements") or []):
        if isinstance(element, Mapping) and element.get("type") != "include":
            collect(element, f"elements[{index}]")
    placeholders = slide.get("placeholders")
    if isinstance(placeholders, Mapping):
        for key, placeholder in placeholders.items():
            collect(placeholder, f"placeholders[{key!r}]")
    return found


def _has_morph_transition(slide: Mapping[str, Any]) -> bool:
    transition = slide.get("transition")
    return isinstance(transition, Mapping) and transition.get("effect") == MORPH_EFFECT


def _label(slide: Mapping[str, Any], position: int) -> str:
    """Name a slide the way its author refers to it: by slug when it has one."""
    slug = slide.get("id")
    return f"slide {slug!r}" if isinstance(slug, str) and slug else f"slide {position + 1}"


def check_morph_pairing(slides_data: Mapping[str, Any]) -> list[str]:
    """Return a warning for every ``morphId`` that pairs with nothing."""
    slides = [s for s in (slides_data.get("slides") or []) if isinstance(s, Mapping)]
    if not slides:
        return []

    ids_per_slide = [_morph_ids(slide) for slide in slides]
    morphs = [_has_morph_transition(slide) for slide in slides]
    if not any(morphs) and not any(ids_per_slide):
        return []

    warnings: list[str] = []
    for position, (slide, ids) in enumerate(zip(slides, ids_per_slide)):
        if not ids:
            continue

        # A Morph transition describes how *its own* slide enters, so slide N's
        # transition pairs N with N-1. An id on slide N can therefore pair
        # backwards (N has the Morph) or forwards (N+1 has it), and it is only
        # idle when neither neighbour is morphing into or out of this slide.
        partners: list[tuple[int, dict[str, str]]] = []
        if morphs[position] and position > 0:
            partners.append((position - 1, ids_per_slide[position - 1]))
        if position + 1 < len(slides) and morphs[position + 1]:
            partners.append((position + 1, ids_per_slide[position + 1]))

        if not partners:
            reason = (
                "no adjacent slide has a Morph transition"
                if not morphs[position]
                else "it is the first slide, so there is nothing to morph from"
            )
            for morph_id, path in sorted(ids.items()):
                warnings.append(
                    f"{_label(slide, position)} {path}.morphId {morph_id!r} does nothing: "
                    f"{reason}. Add \"transition\": {{\"effect\": \"morph\"}} to the slide that "
                    "should morph, or drop the morphId"
                )
            continue

        partner_ids = set()
        for _, partner in partners:
            partner_ids |= set(partner)
        for morph_id, path in sorted(ids.items()):
            if morph_id in partner_ids:
                continue
            named = " or ".join(_label(slides[index], index) for index, _ in partners)
            candidates = sorted(partner_ids - set(ids)) or ["none"]
            warnings.append(
                f"{_label(slide, position)} {path}.morphId {morph_id!r} pairs with nothing on "
                f"{named}, so Morph will fall back to its own matching for this shape. "
                f"Unpaired there: {candidates}"
            )
    return warnings


def morph_pairing_summary(slides_data: Mapping[str, Any]) -> dict[str, Any]:
    """Which morph identities pair, for a caller that wants the data not the prose."""
    slides = [s for s in (slides_data.get("slides") or []) if isinstance(s, Mapping)]
    ids_per_slide: Iterable[dict[str, str]] = [_morph_ids(slide) for slide in slides]
    return {
        "slides": [
            {
                "slide": _label(slide, position),
                "morphTransition": _has_morph_transition(slide),
                "morphIds": sorted(ids),
            }
            for position, (slide, ids) in enumerate(zip(slides, ids_per_slide))
        ],
        "warnings": check_morph_pairing(slides_data),
    }
