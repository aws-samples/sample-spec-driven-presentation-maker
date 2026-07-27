# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Slide diff: compare two slide JSONs/PPTXs and show changes."""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


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
    e1 = [e for e in s1.get("elements", []) if "_comment" not in e]
    e2 = [e for e in s2.get("elements", []) if "_comment" not in e]
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


def _load_deck_as_roundtrip(deck_dir: Path) -> dict:
    """Load deck-structure output (deck.json + slides/*.json) as a single roundtrip dict.

    Restores the legacy {slides: [...], fonts, defaultTextColor} shape that the diff
    algorithms expect. Slides are ordered by filename (slide-01, slide-02, ...).
    """
    deck_json = deck_dir / "deck.json"
    slides_dir = deck_dir / "slides"
    data: dict = {}
    if deck_json.exists():
        with open(deck_json) as f:
            data = json.load(f)
    slides: list = []
    if slides_dir.is_dir():
        for slide_file in sorted(slides_dir.glob("slide-*.json")):
            with open(slide_file) as f:
                slides.append(json.load(f))
    data["slides"] = slides
    return data


def load_slides_json_or_pptx(path):
    """Load roundtrip slides JSON from a deck directory, .json, or .pptx."""
    path_obj = Path(path)
    if path_obj.is_dir():
        # Deck-structure directory (deck.json + slides/*.json + specs/outline.md):
        # build via the canonical pipeline (outline.md ordering, includes,
        # overrides), then roundtrip the built PPTX so both sides of the diff
        # compare in roundtrip shape.
        from sdpm.api import generate
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_pptx = Path(tmpdir) / "baseline.pptx"
            generate(path_obj, output_path=tmp_pptx)
            rt_dir = Path(tmpdir) / "rt"
            subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                [sys.executable, str(Path(__file__).resolve().parent.parent.parent / 'scripts' / 'pptx_to_json.py'), str(tmp_pptx), '-o', str(rt_dir)],
                capture_output=True, text=True, check=True
            )
            return _load_deck_as_roundtrip(rt_dir)
    if str(path).endswith('.pptx'):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                [sys.executable, str(Path(__file__).resolve().parent.parent.parent / 'scripts' / 'pptx_to_json.py'), path, '-o', tmpdir],
                capture_output=True, text=True, check=True
            )
            # New deck-structure output: deck.json + slides/slide-NN.json
            return _load_deck_as_roundtrip(Path(tmpdir))
    with open(path) as f:
        data = json.load(f)
    # Check if this is a source JSON (not already a roundtrip JSON) by looking
    # for builder-specific keys in any slide's elements
    is_source = any(
        any(k in el for k in ("text", "src", "chartData", "include"))
        for s in data.get("slides", [])
        for el in s.get("elements", [])
        if not isinstance(el, str) and "_comment" not in el
    )
    # Also treat as source if slides have layout/title but no elements (title, agenda, section, etc.)
    if not is_source:
        is_source = any(
            s.get("layout") in ("title", "agenda", "section", "subsection", "thankyou")
            and not s.get("elements")
            for s in data.get("slides", [])
        )
    if is_source:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_pptx = Path(tmpdir) / "tmp.pptx"
            from sdpm.api import _find_template_in_dirs, get_templates_dirs
            from sdpm.builder import PPTXBuilder, resolve_override
            tpl_name = data.get("template")
            if not tpl_name:
                raise ValueError("No \"template\" specified in JSON. Cannot build for diff.")
            template = Path(path).parent / tpl_name
            if not template.exists():
                named = _find_template_in_dirs(tpl_name, get_templates_dirs())
                if named is not None:
                    template = named
                else:
                    raise FileNotFoundError(f"Template not found: '{tpl_name}'. Use list_templates to see available templates.")
            builder = PPTXBuilder(template, fonts=data.get("fonts"), base_dir=Path(path).parent,
                                  default_text_color=data.get("defaultTextColor", "#FFFFFF"))
            id_map = {s["id"]: s for s in data.get("slides", []) if "id" in s}
            for slide_def in data.get("slides", []):
                builder.add_slide(resolve_override(slide_def, id_map))
            builder.save(tmp_pptx)
            subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                [sys.executable, str(Path(__file__).resolve().parent.parent.parent / 'scripts' / 'pptx_to_json.py'), str(tmp_pptx), '-o', tmpdir],
                capture_output=True, text=True, check=True
            )
            return _load_deck_as_roundtrip(Path(tmpdir))
    return data


def diff_report(baseline, edited) -> dict:
    """Compare two decks/JSONs/PPTXs and return a hand-edit diff report.

    The canonical implementation behind ``pptx_builder.py diff`` and the
    MCP ``diff_pptx`` tool.

    Args:
        baseline: Deck directory, slides JSON, or PPTX (the original).
        edited: Deck directory, slides JSON, or PPTX (the hand-edited one).

    Returns:
        Dict with ``has_diff`` (bool) and ``report`` (human-readable text,
        one section per changed/added/removed slide).
    """
    base = load_slides_json_or_pptx(str(baseline))
    edit = load_slides_json_or_pptx(str(edited))

    base_slides = base.get("slides", [])
    edit_slides = edit.get("slides", [])
    skip_keys = {"masterIndex", "_comment"}
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

        b_elems = [e for e in bs.get("elements", []) if "_comment" not in e]
        e_elems = [e for e in es.get("elements", []) if "_comment" not in e]

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
        if slide_diffs or elem_diffs or moved:
            title = bs.get("title", es.get("title", ""))
            if isinstance(title, dict):
                title = title.get("text", "")
            moved_str = f" (moved: #{bi + 1}→#{ei + 1})" if moved else ""
            lines.append(f'\n=== Slide (baseline #{bi + 1} ↔ edited #{ei + 1}) "{title[:40]}"{moved_str} ===')
            for d in slide_diffs:
                lines.append(f"  {d}")
            for d in elem_diffs:
                lines.append(d)

    has_diff = bool(lines)
    if not has_diff:
        lines.append("No differences found.")
    return {"has_diff": has_diff, "report": "\n".join(lines).lstrip("\n")}
