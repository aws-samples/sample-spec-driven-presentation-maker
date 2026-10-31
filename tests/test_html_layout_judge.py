# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layout rules over measured HTML slide boxes (sdpm.engine.html.layout_judge)."""

from __future__ import annotations

from sdpm.engine.html.layout_judge import MAX_FINDINGS, TOLERANCE_PX, judge_slide


def _el(kind: str, label: str, box, scroll=None, region=None) -> dict:
    w, h = box[2], box[3]
    el = {"kind": kind, "label": label, "box": list(box), "scroll": list(scroll or (w, h, w, h))}
    if region is not None:
        el["region"] = region
    return el


def _judge(*elements, decorations=None) -> list[dict]:
    return judge_slide("s", {"width": 1920, "height": 1080, "elements": list(elements)}, decorations)


def _rules(*elements, decorations=None) -> list[str]:
    return [d["rule"] for d in _judge(*elements, decorations=decorations)]


TITLE = _el("ph", 'data-ph="title"', (96, 60, 1720, 120))


def test_clean_slide() -> None:
    assert _judge(TITLE, _el("region", 'data-region="body"', (96, 210, 1720, 700))) == []


def test_overlap_between_top_level_blocks() -> None:
    body = _el("region", 'data-region="body"', (96, 142, 1720, 700))
    diags = _judge(TITLE, body)
    assert [d["message"] for d in diags] == ['overlap: data-ph="title" × data-region="body" (1720×38 px); '
                                           'move or resize one so each has its own space']
    assert diags[0]["slug"] == "s" and diags[0]["rule"] == "overlap"


def test_overlap_tolerance_edge() -> None:
    assert _rules(TITLE, _el("free", "<p>", (96, 180 - 3, 500, 100))) == []
    assert _rules(TITLE, _el("free", "<p>", (96, 180 - 5, 500, 100))) == ["overlap"]
    assert TOLERANCE_PX == 4


def test_containment_is_not_overlap() -> None:
    region = _el("region", 'data-region="body"', (100, 200, 800, 600))
    inner = _el("region", 'data-region="card"', (120, 220, 300, 300))  # nested, but measured top-level
    assert _rules(region, inner) == []


def test_overlap_between_children_of_a_region() -> None:
    region = _el("region", 'data-region="body"', (100, 200, 800, 600))
    a = _el("child", '<div class="a">', (100, 200, 400, 300), region=0)
    b = _el("child", '<div class="b">', (300, 400, 400, 300), region=0)
    assert _rules(region, a, b) == ["overlap"]
    # a child is never compared with a top-level block
    other = _el("free", "<img>", (450, 450, 200, 200))
    assert _rules(region, a, other) == []


def test_overflow_content_past_its_box() -> None:
    title = _el("ph", 'data-ph="title"', (96, 60, 1679, 232), scroll=(1820, 260, 1679, 232))
    assert [d["message"] for d in _judge(title)] == [
        'overflow: data-ph="title" content 1820×260 px exceeds its box 1679×232 px; shorten the content, '
        'use a smaller --fs-* token or enlarge the box, leaving a little room (fonts differ between machines)']
    within = _el("ph", 'data-ph="title"', (96, 60, 1679, 232), scroll=(1679, 236, 1679, 232))
    assert _judge(within) == []
    inline = _el("child", "<span>", (96, 60, 100, 20), scroll=(0, 0, 0, 0), region=None)
    assert _judge(inline) == []  # no client box: nothing to compare


def test_overflow_of_a_free_positioned_block() -> None:
    free = _el("free", '<div class="x">', (96, 300, 400, 50), scroll=(400, 200, 400, 50))
    assert _rules(free) == ["overflow"]


def test_overflow_past_the_slide_edge() -> None:
    wide = _el("free", '<p> "Long text…"', (1800, 500, 300, 50))
    assert [d["message"] for d in _judge(wide)] == [
        "overflow: <p> \"Long text…\" extends 180 px past the slide's right edge; keep it inside the canvas"]
    assert _judge(_el("free", "<p>", (1800, 500, 123, 50))) == []  # 3 px past: tolerated


def test_outside_region() -> None:
    region = _el("region", 'data-region="body"', (96, 210, 1720, 640))
    child = _el("child", '<p> "Long text…"', (96, 700, 1720, 192), region=0)
    diags = _judge(region, child)
    assert [d["message"] for d in diags] == [
        'outside-region: <p> "Long text…" extends 42 px below data-region="body"; '
        'fit it inside the region, or move or resize the region']


def test_decoration_overlap() -> None:
    logo = {"name": "Logo", "source": "layout", "bbox": {"x": 1700, "y": 980, "w": 200, "h": 80}, "kind": "obstacle"}
    body = _el("region", 'data-region="body"', (96, 210, 1668, 790))
    assert [d["message"] for d in _judge(body, decorations=[logo])] == [
        "decoration-overlap: data-region=\"body\" covers the template's \"Logo\" (obstacle) by 64×20 px; "
        "move it clear of that box (template_html decorations)"]


def test_decoration_exemptions() -> None:
    band = {"name": "Band", "source": "layout", "bbox": {"x": 0, "y": 0, "w": 1920, "h": 200}, "kind": "band"}
    ground = {"name": "Ground", "source": "master", "bbox": {"x": 0, "y": 0, "w": 1920, "h": 1080}, "kind": "ground"}
    assert _rules(TITLE, decorations=[band, ground]) == []  # a ph over a band; ground ignored
    free = _el("free", "<img>", (96, 100, 200, 200))
    assert _rules(free, decorations=[band]) == ["decoration-overlap"]
    region = _el("region", 'data-region="r"', (96, 100, 400, 200))
    child = _el("child", "<p>", (96, 100, 400, 100), region=0)
    assert _rules(region, child, decorations=[band]) == ["decoration-overlap"]  # the region only


def test_findings_are_capped() -> None:
    blocks = [_el("free", f"<p{i}>", (i * 10, 100, 100, 100)) for i in range(8)]
    diags = _judge(*blocks)
    assert len(diags) == MAX_FINDINGS
    total = sum(1 for i in range(8) for j in range(i + 1, 8) if (j - i) * 10 < 96)
    assert diags[-1]["message"] == f"… and {total - (MAX_FINDINGS - 1)} more"
