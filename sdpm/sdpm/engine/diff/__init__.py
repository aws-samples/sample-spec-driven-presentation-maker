# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Slide diff: pure comparison of two loaded slide structures.

This module is core engine logic — it operates only on already-loaded
dicts. Loading/building the inputs (deck directories, source JSONs, PPTX
roundtrips) is facade orchestration and lives in :func:`sdpm.api.diff_report`.
"""
import json
import re

from sdpm.engine.schema.regions import is_comment_element


def _elem_x(elem):
    return elem.get("x1", elem.get("x", 0)) if elem.get("type") == "line" else elem.get("x", 0)


def _elem_y(elem):
    return elem.get("y1", elem.get("y", 0)) if elem.get("type") == "line" else elem.get("y", 0)


def _elem_id(elem):
    """Short identifier for an element."""
    t = elem.get("type", "?")
    x, y = _elem_x(elem), _elem_y(elem)
    shape = elem.get("shape", "")
    label = f" shape={shape}" if shape else ""
    return f"{t}{label} at ({x},{y})"


def _diff_value(key, old, new):
    """Format a single value diff."""
    if isinstance(old, str) and len(old) > 60:
        old = old[:57] + "..."
    if isinstance(new, str) and len(new) > 60:
        new = new[:57] + "..."
    return f'{key}: {json.dumps(old, ensure_ascii=False)} → {json.dumps(new, ensure_ascii=False)}'


def _elem_text(elem):
    """Extract text content from element for similarity comparison."""
    t = elem.get("text", "")
    if not t and elem.get("paragraphs"):
        t = " ".join(p.get("text", "") for p in elem["paragraphs"])
    if not t and elem.get("items"):
        t = " ".join(elem["items"])
    return re.sub(r'\{\{[^:}]*:', '', t).replace('}}', '')


def match_elements(base_elems, edit_elems):
    """Match elements between baseline and edited by type, position, and text similarity."""
    used = set()
    pairs = []
    for bi, be in enumerate(base_elems):
        best_j, best_score = None, -1
        bt = _elem_text(be)
        for ej, ee in enumerate(edit_elems):
            if ej in used:
                continue
            if be.get("type") != ee.get("type"):
                continue
            dx = abs(_elem_x(be) - _elem_x(ee))
            dy = abs(_elem_y(be) - _elem_y(ee))
            pos_score = max(0, 1 - (dx + dy) / 1000)
            et = _elem_text(ee)
            text_score = 0
            if bt and et:
                common = sum(1 for c in bt if c in et)
                text_score = common / max(len(bt), len(et)) if max(len(bt), len(et)) > 0 else 0
            score = pos_score * 0.4 + text_score * 0.6
            if not bt and not et:
                score = pos_score
            if score > best_score:
                best_score = score
                best_j = ej
        if best_j is not None and best_score > 0.2:
            pairs.append((bi, best_j))
            used.add(best_j)
        else:
            pairs.append((bi, None))
    added = [ej for ej in range(len(edit_elems)) if ej not in used]
    return pairs, added


def slide_similarity(s1, s2):
    """Compute similarity score (0-1) between two slides."""
    e1 = [e for e in s1.get("elements", []) if not is_comment_element(e)]
    e2 = [e for e in s2.get("elements", []) if not is_comment_element(e)]
    layout_match = s1.get("layout") == s2.get("layout")
    if not e1 and not e2:
        return 0.8 if layout_match else 0.0
    if not e1 or not e2:
        return 0.0
    pairs, _ = match_elements(e1, e2)
    matched = sum(1 for _, ej in pairs if ej is not None)
    elem_sim = matched / max(len(e1), len(e2))
    if elem_sim > 0:
        return elem_sim
    return 0.15 if layout_match else 0.0


def align_slides(base_slides, edit_slides, threshold=0.1):
    """Greedy best-match slide alignment. Handles reordering, insertion, deletion."""
    n, m = len(base_slides), len(edit_slides)
    scores = []
    for i in range(n):
        for j in range(m):
            sim = slide_similarity(base_slides[i], edit_slides[j])
            if sim >= threshold:
                scores.append((sim, i, j))
    scores.sort(reverse=True)
    b_used, e_used = set(), set()
    matched = {}
    for sim, bi, ei in scores:
        if bi in b_used or ei in e_used:
            continue
        matched[bi] = ei
        b_used.add(bi)
        e_used.add(ei)
    result = []
    reported_base = set()
    for ei in range(m):
        bi_match = None
        for bi, ej in matched.items():
            if ej == ei:
                bi_match = bi
                break
        if bi_match is not None:
            result.append((bi_match, ei))
            reported_base.add(bi_match)
        else:
            result.append((None, ei))
    for bi in range(n):
        if bi not in reported_base:
            result.append((bi, None))
    return result


# ---------------------------------------------------------------------------
# Motion: transitions, animation timelines, preserved raw fallback
# ---------------------------------------------------------------------------
def _effect_target(effect: dict) -> str:
    target = effect.get("target")
    return str(target.get("element", "?")) if isinstance(target, dict) else "?"


def _effect_label(effect: dict) -> str:
    """One short line naming what an effect does, for the diff report."""
    preset = effect.get("preset")
    if isinstance(preset, dict):
        parts = [
            str(preset[key]) for key in ("category", "effect")
            if preset.get(key) is not None
        ]
        options = preset.get("options")
        if isinstance(options, dict) and options:
            # Named in the line because a changed direction is a changed
            # animation, and a diff that showed only "entrance/flyIn" on both
            # sides would report no difference where the reader sees one.
            parts.append(
                ",".join(f"{setting}={value}" for setting, value in sorted(options.items()))
            )
        name = "/".join(parts)
    else:
        behaviors = effect.get("behaviors")
        kinds = [
            str(b.get("type", "?")) for b in behaviors if isinstance(b, dict)
        ] if isinstance(behaviors, list) else []
        name = f"behaviors({','.join(kinds)})"
    return f"{name or '?'} on {_effect_target(effect)}"


def _effect_entries(sequence: str, effects) -> list[tuple[str, dict]]:
    """Return ``(stable id, effect)`` in sequence order.

    An effect that carries no explicit ``id`` gets the same deterministic
    fingerprint the writer and the importer derive, so the two sides of a diff
    compare by the identity REQ-2.5 makes stable rather than by array index.
    """
    from sdpm.engine.timing.identity import EffectIdAllocator

    allocator = EffectIdAllocator()
    entries: list[tuple[str, dict]] = []
    for effect in effects if isinstance(effects, list) else []:
        if not isinstance(effect, dict):
            continue
        entries.append((
            allocator.allocate(sequence=sequence, target=_effect_target(effect), effect=effect),
            effect,
        ))
    return entries


def _diff_properties(base: dict, edit: dict, *, skip=("id",)) -> list[str]:
    changes = []
    for key in sorted((set(base) | set(edit)) - set(skip)):
        if base.get(key) != edit.get(key):
            changes.append(_diff_value(key, base.get(key), edit.get(key)))
    return changes


def _diff_sequence(label: str, sequence: str, base_effects, edit_effects) -> list[str]:
    """Compare one animation sequence by stable effect ID and order."""
    base_entries = _effect_entries(sequence, base_effects)
    edit_entries = _effect_entries(sequence, edit_effects)
    base_at = {eid: i for i, (eid, _) in enumerate(base_entries)}
    edit_at = {eid: i for i, (eid, _) in enumerate(edit_entries)}
    edit_by_id = dict(edit_entries)
    lines: list[str] = []

    for position, (eid, effect) in enumerate(base_entries):
        if eid not in edit_at:
            lines.append(f"  animation REMOVED {label}[{position}] {eid}: {_effect_label(effect)}")
    for position, (eid, effect) in enumerate(edit_entries):
        if eid not in base_at:
            lines.append(f"  animation ADDED {label}[{position}] {eid}: {_effect_label(effect)}")
    for position, (eid, effect) in enumerate(base_entries):
        if eid not in edit_at:
            continue
        edited = edit_by_id[eid]
        if edit_at[eid] != position:
            lines.append(
                f"  animation MOVED {label}[{position}] → [{edit_at[eid]}] {eid}: "
                f"{_effect_label(effect)}"
            )
        changes = _diff_properties(effect, edited)
        if changes:
            lines.append(f"  animation {label}[{edit_at[eid]}] {eid} ({_effect_label(effect)}):")
            lines.extend(f"    {change}" for change in changes)
    return lines


def _diff_animations(base_slide: dict, edit_slide: dict) -> list[str]:
    base = base_slide.get("animations") if isinstance(base_slide.get("animations"), dict) else {}
    edit = edit_slide.get("animations") if isinstance(edit_slide.get("animations"), dict) else {}
    if not base and not edit:
        return []
    lines = _diff_sequence(
        "mainSequence", "mainSequence", base.get("mainSequence"), edit.get("mainSequence"),
    )

    def by_id(value) -> dict[str, dict]:
        return {
            str(item.get("id")): item
            for item in (value if isinstance(value, list) else [])
            if isinstance(item, dict)
        }

    base_sequences = by_id(base.get("interactiveSequences"))
    edit_sequences = by_id(edit.get("interactiveSequences"))
    for sequence_id in sorted(set(base_sequences) | set(edit_sequences)):
        label = f"interactive[{sequence_id}]"
        before, after = base_sequences.get(sequence_id), edit_sequences.get(sequence_id)
        if before is None:
            lines.append(f"  animation ADDED sequence {label}")
            after = after or {}
        elif after is None:
            lines.append(f"  animation REMOVED sequence {label}")
            before = before or {}
        if before and after and before.get("trigger") != after.get("trigger"):
            lines.append(f"  {_diff_value(f'{label}.trigger', before.get('trigger'), after.get('trigger'))}")
        lines.extend(_diff_sequence(
            label, "interactiveSequences",
            (before or {}).get("effects"), (after or {}).get("effects"),
        ))
    return lines


def _diff_transition(base_slide: dict, edit_slide: dict) -> list[str]:
    before, after = base_slide.get("transition"), edit_slide.get("transition")
    if before == after:
        return []
    if not isinstance(before, dict):
        name = after.get("effect", "?") if isinstance(after, dict) else after
        return [f"  transition ADDED: {name}"]
    if not isinstance(after, dict):
        return [f"  transition REMOVED: {before.get('effect', '?')}"]
    return [f"  transition.{change}" for change in _diff_properties(before, after, skip=())]


def _raw_targets(manifest, sidecar: str) -> list[str]:
    """Return the logical element names one preserved sidecar animates."""
    for record in (manifest or {}).get("sidecars") or []:
        if isinstance(record, dict) and record.get("path") == sidecar:
            mappings = record.get("shapeMappings")
            return sorted(set(mappings.values())) if isinstance(mappings, dict) else []
    return []


def _raw_summary(reference: dict, manifest) -> str:
    """Summarize a preserved fragment by digest and affected targets.

    Never the XML itself: a raw sidecar is a whole timing tree, and dumping it
    into a hand-edit report would bury the one line a reader needs (REQ-8.4).
    """
    digest = str(reference.get("sha256", ""))[:12] or "(no digest)"
    targets = _raw_targets(manifest, str(reference.get("sidecar", "")))
    suffix = f", targets: {', '.join(targets)}" if targets else ""
    return f"{digest}{suffix}"


def _diff_raw(base_slide: dict, edit_slide: dict, base_manifest, edit_manifest) -> list[str]:
    lines: list[str] = []
    for key, feature in (("_rawTiming", "timing"), ("_rawTransition", "transition")):
        before = base_slide.get(key) if isinstance(base_slide.get(key), dict) else None
        after = edit_slide.get(key) if isinstance(edit_slide.get(key), dict) else None
        if before is None and after is None:
            continue
        if before is None:
            lines.append(f"  raw {feature} ADDED: {_raw_summary(after, edit_manifest)}")
        elif after is None:
            lines.append(f"  raw {feature} REMOVED: {_raw_summary(before, base_manifest)}")
        elif before.get("sha256") != after.get("sha256"):
            lines.append(
                f"  raw {feature} CHANGED: {_raw_summary(before, base_manifest)} → "
                f"{_raw_summary(after, edit_manifest)}"
            )
    return lines


def diff_slides(base: dict, edit: dict) -> dict:
    """Compare two loaded slide structures and return a hand-edit diff report.

    Pure comparison — both arguments are roundtrip-shaped dicts
    (``{"slides": [...], ...}``). To diff paths (deck directory, JSON, or
    PPTX), use :func:`sdpm.api.diff_report`, which loads/builds the inputs
    and delegates here.

    Returns:
        Dict with ``has_diff`` (bool) and ``report`` (human-readable text,
        one section per changed/added/removed slide).
    """
    base_slides = base.get("slides", [])
    edit_slides = edit.get("slides", [])
    skip_keys = {"masterIndex", "_comment"}
    # Attached by the loader (sdpm.api) while the converted deck still exists;
    # it is what turns a raw sidecar digest into the target names it animates.
    base_manifest = base.get("_rawManifest")
    edit_manifest = edit.get("_rawManifest")
    lines: list[str] = []

    alignment = align_slides(base_slides, edit_slides)

    for bi, ei in alignment:
        if bi is None:
            es = edit_slides[ei]
            title = es.get("title", "")
            if isinstance(title, dict):
                title = title.get("text", "")
            lines.append(f'\n=== ADDED slide (edited #{ei + 1}) "{title[:40]}" ===')
            lines.append(f"  layout: {es.get('layout')}, elements: {len(es.get('elements', []))}")
            continue
        if ei is None:
            bs = base_slides[bi]
            title = bs.get("title", "")
            if isinstance(title, dict):
                title = title.get("text", "")
            lines.append(f'\n=== REMOVED slide (baseline #{bi + 1}) "{title[:40]}" ===')
            continue

        bs, es = base_slides[bi], edit_slides[ei]
        slide_diffs = []

        for key in ("layout", "title", "notes"):
            bv, ev = bs.get(key), es.get(key)
            if bv != ev and (bv or ev):
                slide_diffs.append(_diff_value(key, bv, ev))

        motion_diffs = (
            _diff_transition(bs, es)
            + _diff_animations(bs, es)
            + _diff_raw(bs, es, base_manifest, edit_manifest)
        )

        # Compare placeholders (title/body text captured by idx) — hand-edits
        # to titles land here, not in elements.
        b_ph = bs.get("placeholders") or {}
        e_ph = es.get("placeholders") or {}
        for idx in sorted(set(b_ph) | set(e_ph)):
            bv, ev = b_ph.get(idx), e_ph.get(idx)
            if bv == ev:
                continue
            b_txt = bv.get("text") if isinstance(bv, dict) else bv
            e_txt = ev.get("text") if isinstance(ev, dict) else ev
            if b_txt != e_txt:
                slide_diffs.append(_diff_value(f"placeholder[{idx}]", b_txt, e_txt))
            elif bv != ev:
                slide_diffs.append(_diff_value(f"placeholder[{idx}] (format/position)",
                                               json.dumps(bv, ensure_ascii=False)[:60],
                                               json.dumps(ev, ensure_ascii=False)[:60]))

        b_elems = [e for e in bs.get("elements", []) if not is_comment_element(e)]
        e_elems = [e for e in es.get("elements", []) if not is_comment_element(e)]

        pairs, added = match_elements(b_elems, e_elems)
        elem_diffs = []

        for bj, ej in pairs:
            be = b_elems[bj]
            if ej is None:
                elem_diffs.append(f"  REMOVED [{bj}] {_elem_id(be)}")
                continue
            ee = e_elems[ej]
            all_keys = sorted(set(list(be.keys()) + list(ee.keys())) - skip_keys)
            changes = []
            for key in all_keys:
                bv, ev = be.get(key), ee.get(key)
                if bv == ev:
                    continue
                if bv is None:
                    changes.append(f"+{key}={json.dumps(ev, ensure_ascii=False)[:40]}")
                elif ev is None:
                    changes.append(f"-{key}")
                else:
                    if isinstance(bv, (int, float)) and isinstance(ev, (int, float)) and abs(bv - ev) <= 2:
                        continue
                    changes.append(_diff_value(key, bv, ev))
            if changes:
                elem_diffs.append(f"  [{bj}] {_elem_id(be)}:")
                for c in changes:
                    elem_diffs.append(f"    {c}")

        for ej in added:
            ee = e_elems[ej]
            elem_diffs.append(f"  ADDED {_elem_id(ee)}:")
            elem_diffs.append(f"    {json.dumps(ee, ensure_ascii=False)[:300]}")

        moved = bi != ei
        if slide_diffs or elem_diffs or motion_diffs or moved:
            title = bs.get("title", es.get("title", ""))
            if isinstance(title, dict):
                title = title.get("text", "")
            moved_str = f" (moved: #{bi + 1}→#{ei + 1})" if moved else ""
            lines.append(f'\n=== Slide (baseline #{bi + 1} ↔ edited #{ei + 1}) "{title[:40]}"{moved_str} ===')
            for d in slide_diffs:
                lines.append(f"  {d}")
            for d in motion_diffs:
                lines.append(d)
            for d in elem_diffs:
                lines.append(d)

    has_diff = bool(lines)
    if not has_diff:
        lines.append("No differences found.")
    return {"has_diff": has_diff, "report": "\n".join(lines).lstrip("\n")}
