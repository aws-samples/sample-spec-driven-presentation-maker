"""A built deck carries its own document properties, not its template's.

The template's author, last editor, description, dates and revision (core.xml), its slide
titles and statistics (app.xml) and the bundled templates' custom properties (custom.xml)
must not reach a deck built from it. A user template's custom properties stay.
"""

import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation

TEMPLATES = Path(__file__).parent.parent / "sdpm" / "templates"
BUNDLED = sorted(TEMPLATES.glob("*.pptx"))
EP = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"


def _build(tmp_path: Path, template: Path) -> Path:
    from sdpm.engine.builder import PPTXBuilder

    b = PPTXBuilder(str(template), fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"}, default_text_color="#FFFFFF")
    b.add_slide({"layout": "blank", "elements": []})
    out = tmp_path / "deck.pptx"
    b.save(out)
    return out


def _part(path: Path, name: str) -> etree._Element | None:
    with zipfile.ZipFile(path) as z:
        return etree.fromstring(z.read(name)) if name in z.namelist() else None


def _template_core(template: Path) -> dict:
    p = Presentation(str(template)).core_properties
    return {"author": p.author, "last_modified_by": p.last_modified_by, "comments": p.comments}


@pytest.mark.parametrize("template", BUNDLED, ids=lambda t: t.name)
def test_core_properties_start_fresh(tmp_path, template):
    # The bundled templates do carry metadata, or this test proves nothing.
    assert any(_template_core(template).values())

    before = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    props = Presentation(str(_build(tmp_path, template))).core_properties
    for name in ("author", "last_modified_by", "comments", "subject", "keywords", "category", "title"):
        assert getattr(props, name) == "", name
    assert props.revision == 1
    assert props.last_printed is None
    for stamp in (props.created, props.modified):
        assert before <= stamp <= before + timedelta(minutes=5)


@pytest.mark.parametrize("template", BUNDLED, ids=lambda t: t.name)
def test_app_statistics_and_custom_properties_are_dropped(tmp_path, template):
    out = _build(tmp_path, template)
    app = _part(out, "docProps/app.xml")
    for name in ("TitlesOfParts", "HeadingPairs", "Slides", "Words", "TotalTime", "Company"):
        assert app.find(f"{EP}{name}") is None, name
    custom = _part(out, "docProps/custom.xml")
    assert custom is None or len(custom) == 0


def test_user_template_keeps_its_custom_properties(tmp_path):
    # A user template's custom properties (e.g. a sensitivity label) are the user's policy.
    # Re-saving gives a template with the same custom.xml but bytes of its own.
    user_template = tmp_path / "corporate.pptx"
    Presentation(str(BUNDLED[0])).save(str(user_template))
    assert user_template.read_bytes() != BUNDLED[0].read_bytes()
    assert len(_part(user_template, "docProps/custom.xml")) > 0

    out = _build(tmp_path, user_template)
    assert len(_part(out, "docProps/custom.xml")) > 0
    assert Presentation(str(out)).core_properties.last_modified_by == ""


@pytest.mark.parametrize("template", BUNDLED, ids=lambda t: t.name)
def test_copied_bundled_template_still_counts_as_bundled(tmp_path, template):
    # The remote server downloads a bundled template from S3 into <tmpdir>/template.pptx.
    copy = tmp_path / "template.pptx"
    shutil.copy(template, copy)
    custom = _part(_build(tmp_path, copy), "docProps/custom.xml")
    assert custom is None or len(custom) == 0
