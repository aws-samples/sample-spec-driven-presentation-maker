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


def load_slides_json_or_pptx(path):
    """Load roundtrip slides JSON from .json or .pptx."""
    if path.endswith('.pptx'):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
                [sys.executable, str(Path(__file__).resolve().parent.parent.parent / 'scripts' / 'pptx_to_json.py'), path, '-o', tmpdir],
                capture_output=True, text=True, check=True
            )
            with open(Path(tmpdir) / 'slides.json') as f:
                return json.load(f)
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
            from sdpm.builder import PPTXBuilder, resolve_override
            templates_dir = Path(__file__).resolve().parent.parent.parent / "templates"
            tpl_name = data.get("template")
            if not tpl_name:
                raise ValueError("No \"template\" specified in JSON. Cannot build for diff.")
            template = Path(path).parent / tpl_name
            if not template.exists():
                named = templates_dir / (tpl_name if tpl_name.endswith(".pptx") else tpl_name + ".pptx")
                if named.exists():
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
            with open(Path(tmpdir) / 'slides.json') as f:
                return json.load(f)
    return data
