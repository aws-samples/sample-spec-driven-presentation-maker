# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Fake LibreOffice (``soffice``) and poppler (``pdftoppm``) for the run_python tests.

CI has neither, and the run_python post-processing shells out to both. ``install``
replaces ``subprocess.run`` (every other command still runs for real) and
``shutil.which`` so both servers and the engine find the fakes:

- ``soffice --convert-to svg`` reads the input PPTX with python-pptx and writes
  ``<outdir>/<stem>.svg`` in LibreOffice's layout: a dummy Slide group, then one
  Slide/Page group per slide with a TextShape (BoundingBox rect + SVGTextShape text
  + TextPosition tspan) per text-bearing shape, and a Graphic with a holed path
  per shape without text. The root carries ``fill-rule="evenodd"``, as LibreOffice's does.
- ``soffice --convert-to pdf`` writes ``<outdir>/<stem>.pdf`` (a JSON list of the
  slides' texts; only the fake pdftoppm reads it).
- ``pdftoppm`` writes small real PNGs, either ``<prefix>-<n>.png`` per page (padded
  to the width of the page count, like poppler) or ``<prefix>.png`` with
  ``-f/-l/-singlefile``. ``-scale-to N`` gives N px wide, ``-r DPI`` 40 px wide.

``install(monkeypatch, available=False)`` instead makes the machine look like one
without LibreOffice and poppler (not found, and running them fails as a missing
binary does).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

_EMU_PER_UNIT = 360  # LibreOffice SVG units are 1/100 mm
_FONT_SIZE = 635  # 18 pt in 1/100 mm
_HOLED_PATH = "M 0,0 L 1000,0 1000,1000 0,1000 Z M 250,250 L 750,250 750,750 250,750 Z"


@dataclass
class FakeOffice:
    """What the fakes were asked to do, for assertions."""

    calls: list[tuple[str, str]] = field(default_factory=list)  # (tool, format or "png")

    def handle(self, command) -> subprocess.CompletedProcess | None:
        if not isinstance(command, (list, tuple)) or not command:
            return None
        tool = Path(str(command[0])).name
        if tool in ("soffice", "soffice.exe", "libreoffice"):
            return self._soffice([str(c) for c in command])
        if tool == "pdftoppm":
            return self._pdftoppm([str(c) for c in command])
        return None

    def _soffice(self, cmd: list[str]) -> subprocess.CompletedProcess:
        fmt = cmd[cmd.index("--convert-to") + 1]
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        source = Path(cmd[-1])
        self.calls.append(("soffice", fmt))
        slides = _read_slides(source)
        outdir.mkdir(parents=True, exist_ok=True)
        if fmt == "svg":
            (outdir / f"{source.stem}.svg").write_text(_svg(slides), encoding="utf-8")
        elif fmt == "pdf":
            texts = [[text for _, text in shapes if text] for shapes in slides]
            (outdir / f"{source.stem}.pdf").write_text(json.dumps(texts), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def _pdftoppm(self, cmd: list[str]) -> subprocess.CompletedProcess:
        from PIL import Image

        self.calls.append(("pdftoppm", "png"))
        width = int(cmd[cmd.index("-scale-to") + 1]) if "-scale-to" in cmd else 40
        size = (width, width * 9 // 16)
        pdf, prefix = Path(cmd[-2]), Path(cmd[-1])
        pages = len(json.loads(pdf.read_text(encoding="utf-8")))
        if "-singlefile" in cmd:
            page = int(cmd[cmd.index("-f") + 1])
            if not 1 <= page <= pages:
                return subprocess.CompletedProcess(cmd, 99, "", "Wrong page range given")
            Image.new("RGB", size, (page, 0, 0)).save(prefix.with_name(prefix.name + ".png"))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        digits = len(str(pages))
        for page in range(1, pages + 1):
            Image.new("RGB", size, (page, 0, 0)).save(prefix.with_name(f"{prefix.name}-{page:0{digits}d}.png"))
        return subprocess.CompletedProcess(cmd, 0, "", "")


def _read_slides(pptx_path: Path) -> list[list[tuple[tuple[int, int, int, int], str]]]:
    """Per slide: ((x, y, w, h) in SVG units, text) of every non-placeholder shape and title."""
    from pptx import Presentation

    prs = Presentation(str(pptx_path))
    slides = []
    for slide in prs.slides:
        shapes = []
        for shape in slide.shapes:
            if shape.left is None or shape.width is None:
                continue
            text = shape.text_frame.text.strip() if shape.has_text_frame else ""
            if shape.is_placeholder and not text:
                continue
            box = tuple(int(v / _EMU_PER_UNIT) for v in (shape.left, shape.top, shape.width, shape.height))
            shapes.append((box, text))
        slides.append(shapes)
    return slides


def _svg(slides) -> str:
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:ooo="http://xml.openoffice.org/svg/export" '
        'version="1.2" viewBox="0 0 33867 19050" fill-rule="evenodd" stroke-width="28.222" '
        'stroke-linejoin="round">',
        '<defs class="ClipPathGroup"><clipPath id="presentation_clip_path"><rect x="0" y="0" '
        'width="33867" height="19050"/></clipPath></defs>',
        '<g class="DummySlide"><g><g id="dummy-slide" class="Slide"><g class="Page"/></g></g></g>',
        '<g class="SlideGroup">',
    ]
    for n, shapes in enumerate(slides, 1):
        parts.append(f'<g><g id="container-id{n}"><g id="id{n}" class="Slide"><g class="Page">')
        for i, ((x, y, w, h), text) in enumerate(shapes):
            sid = f"s{n}-{i}"
            if text:
                parts.append(
                    f'<g class="TextShape"><g id="{sid}">'
                    f'<rect class="BoundingBox" stroke="none" fill="none" x="{x}" y="{y}" width="{w}" height="{h}"/>'
                    f'<text class="SVGTextShape"><tspan class="TextParagraph">'
                    f'<tspan class="TextPosition" x="{x}" y="{y + _FONT_SIZE}">'
                    f'<tspan font-family="Arial" font-size="{_FONT_SIZE}px" fill="rgb(255,255,255)" '
                    f'textLength="{w}">{escape(text)}</tspan></tspan></tspan></text></g></g>'
                )
            else:
                parts.append(
                    f'<g class="Graphic"><g id="{sid}">'
                    f'<rect class="BoundingBox" stroke="none" fill="none" x="{x}" y="{y}" width="{w}" height="{h}"/>'
                    f'<path fill="rgb(255,153,0)" d="{_HOLED_PATH}"/></g></g>'
                )
        parts.append("</g></g></g></g>")
    parts.append("</g></svg>")
    return "".join(parts)


def install(monkeypatch, *, available: bool = True) -> FakeOffice:
    """Route soffice / pdftoppm to the fakes (``available=False``: neither is installed)."""
    from sdpm.engine.preview import environment

    office = FakeOffice()
    real_run = subprocess.run
    real_which = shutil.which

    def fake_run(command, *args, **kwargs):
        if not available and isinstance(command, (list, tuple)) and command and Path(str(command[0])).name in (
                "soffice", "soffice.exe", "libreoffice", "pdftoppm"):
            raise FileNotFoundError(2, "No such file or directory", str(command[0]))
        handled = office.handle(command) if available else None
        if handled is None:
            return real_run(command, *args, **kwargs)
        if kwargs.get("check") and handled.returncode:
            raise subprocess.CalledProcessError(handled.returncode, command)
        return handled

    def fake_which(name, *args, **kwargs):
        if name in ("soffice", "libreoffice", "pdftoppm"):
            return f"/fake/{name}" if available and name != "libreoffice" else None
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", fake_which)
    monkeypatch.setattr(environment, "_SOFFICE_CANDIDATES", ())
    return office
