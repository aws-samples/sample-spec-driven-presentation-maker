# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Test configuration — add servers/remote/ and sdpm/ to sys.path, and keep every test away
from the user's real deck root."""

import os
import sys
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Emu

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_root / "servers" / "remote"))
sys.path.insert(0, str(_root / "sdpm"))

# Standard slide dimensions in EMU
_W_16X9 = 12192000
_H_16X9 = 6858000
_W_4X3 = 9144000
_H_4X3 = 6858000


# The deck roots a test must never write to: the default, and the one this environment
# resolves to before any fixture runs (SDPM_DECK_ROOT / SDPM_OUTPUT_DIR / output_dir in
# config.json). Snapshotted at session start, compared at session end.
_guarded_deck_roots: dict[Path, dict[str, int] | None] = {}


def _snapshot(root: Path) -> dict[str, int] | None:
    """Every entry under root (relative path → mtime_ns); None when root does not exist."""
    if not root.is_dir():
        return None
    entries: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            try:
                entries[str(path.relative_to(root))] = path.lstat().st_mtime_ns
            except OSError:
                pass
    return entries


def pytest_sessionstart(session):
    from sdpm.api import _get_output_base_dir

    for root in (Path.home() / "Documents" / "SDPM-Presentations", _get_output_base_dir()):
        root = root.expanduser().resolve()
        _guarded_deck_roots[root] = _snapshot(root)


def pytest_sessionfinish(session, exitstatus):
    """Fail the run when a test created or changed anything under a real deck root."""
    found: list[str] = []
    for root, before in _guarded_deck_roots.items():
        after = _snapshot(root)
        if after is None:
            continue
        if before is None:
            found.append(f"{root} (created)")
            before = {}
        changed = sorted(p for p, mtime in after.items() if before.get(p) != mtime)
        found += [str(root / p) for p in changed[:20]]
        if len(changed) > 20:
            found.append(f"… and {len(changed) - 20} more under {root}")
    if found:
        lines = ["Tests wrote under the real deck root (see _isolated_deck_root in tests/conftest.py):", *found]
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            reporter.ensure_newline()
            reporter.write_line("\n".join(lines), red=True, bold=True)
        else:
            print("\n".join(lines), file=sys.stderr)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True)
def _isolated_deck_root(tmp_path_factory, monkeypatch):
    """Each test gets its own deck root and user config dir, so nothing it creates through
    the deck-root order (sdpm.api._get_output_base_dir, web-ui deck-paths.ts resolveDeckRoot)
    lands in ~/Documents/SDPM-Presentations or the user's configured output_dir."""
    monkeypatch.setenv("SDPM_DECK_ROOT", str(tmp_path_factory.mktemp("deck-root")))
    monkeypatch.delenv("SDPM_OUTPUT_DIR", raising=False)
    config = tmp_path_factory.mktemp("user-config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("APPDATA", str(config))


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch):
    """No test starts a browser for the HTML browser check unless it sets SDPM_BROWSER
    (or registers a source) itself."""
    from sdpm.engine.html import browser

    monkeypatch.setenv("SDPM_BROWSER", "none")
    monkeypatch.setattr(browser, "_registered", None)


@pytest.fixture(autouse=True)
def _no_soffice_warm_up(monkeypatch):
    """No test starts the remote server's LibreOffice warm-up unless it removes the switch itself."""
    monkeypatch.setenv("SDPM_SKIP_SOFFICE_WARMUP", "1")


@pytest.fixture(autouse=True)
def _isolated_template_html_cache(tmp_path_factory, monkeypatch):
    """HTML template conversions go to a per-session temp cache, not the checkout's .cache."""
    import sdpm.config

    monkeypatch.setattr(sdpm.config, "CACHE_DIR", tmp_path_factory.getbasetemp() / "sdpm-cache")


@pytest.fixture()
def template_16x9() -> Path:
    """Path to the bundled 16:9 blank-dark template (no copy needed)."""
    return _root / "sdpm" / "templates" / "blank-dark.pptx"


@pytest.fixture()
def template_4x3(tmp_path: Path) -> Path:
    """Generate a 4:3 template from blank-dark.pptx by resizing slide dimensions.

    The roundtrip depends on layout name "Blank" existing in the template,
    so we cannot use a bare Presentation() — we must base it on blank-dark.pptx.
    """
    src = _root / "sdpm" / "templates" / "blank-dark.pptx"
    prs = Presentation(str(src))
    prs.slide_width = Emu(_W_4X3)
    prs.slide_height = Emu(_H_4X3)
    out = tmp_path / "blank-dark-4x3.pptx"
    prs.save(str(out))
    return out


# Geometry of the decorated_template fixture, in px on the 1920-wide canvas.
DECORATED_LOGO_PX = (1800, 1020, 64, 32)
DECORATED_COPYRIGHT_PX = (40, 1040, 400, 30)
DECORATED_BAND_RGB = (0xFF, 0x99, 0x00)


@pytest.fixture(scope="session")
def decorated_template(tmp_path_factory) -> Path:
    """blank-light.pptx with template decorations, built with python-pptx.

    - slide master 0: a 64x32 PNG logo and a copyright text box
    - layout "Title Only": a full-width header band containing its title placeholder
    - layout "Blank": showMasterSp="0" (hides the master logo / copyright)
    - layout "Section Header": a gradient background (non-solid ground)
    """
    import io

    from lxml import etree
    from PIL import Image
    from pptx.dml.color import RGBColor
    from pptx.shapes.autoshape import Shape

    prs = Presentation(str(_root / "sdpm" / "templates" / "blank-light.pptx"))
    emu = prs.slide_width / 1920
    master = prs.slide_masters[0]
    layouts = {layout.name: layout for layout in master.slide_layouts}

    def px(*values):
        return [int(round(v * emu)) for v in values]

    png = io.BytesIO()
    Image.new("RGB", (64, 32), (200, 30, 30)).save(png, format="PNG")
    png.seek(0)
    _, r_id = master.part.get_or_add_image_part(png)
    tree = master.shapes._spTree
    tree.add_pic(master.shapes._next_shape_id, "Logo", "", r_id, *px(*DECORATED_LOGO_PX))
    copyright_sp = tree.add_textbox(master.shapes._next_shape_id, "Copyright", *px(*DECORATED_COPYRIGHT_PX))
    Shape(copyright_sp, master.shapes).text_frame.text = "© Example Corp"

    title_only = layouts["Title Only"]
    title = next(ph for ph in title_only.placeholders if ph.placeholder_format.idx == 0)
    top = max(0, title.top - int(10 * emu))
    band_sp = title_only.shapes._spTree.add_autoshape(
        title_only.shapes._next_shape_id, "Header Band", "rect",
        0, top, prs.slide_width, title.height + int(20 * emu),
    )
    band = Shape(band_sp, title_only.shapes)
    band.fill.solid()
    band.fill.fore_color.rgb = RGBColor(*DECORATED_BAND_RGB)
    band.line.fill.background()

    layouts["Blank"]._element.set("showMasterSp", "0")

    ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    c_sld = layouts["Section Header"]._element.find(f"{{{ns}}}cSld")
    bg = etree.fromstring(
        f'<p:bg xmlns:p="{ns}" xmlns:a="{a}"><p:bgPr><a:gradFill><a:gsLst>'
        '<a:gs pos="0"><a:srgbClr val="112233"/></a:gs>'
        '<a:gs pos="100000"><a:srgbClr val="445566"/></a:gs>'
        "</a:gsLst><a:lin ang=\"0\" scaled=\"0\"/></a:gradFill><a:effectLst/></p:bgPr></p:bg>"
    )
    c_sld.insert(0, bg)

    out = tmp_path_factory.mktemp("decorated") / "decorated.pptx"
    prs.save(str(out))
    return out
