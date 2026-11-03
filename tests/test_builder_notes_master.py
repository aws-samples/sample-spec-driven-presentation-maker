"""A deck with speaker notes declares its notes master, so Keynote can open it.

python-pptx creates the notes master on the first ``slide.notes_slide`` and
relates it to the presentation, but leaves ``<p:notesMasterIdLst>`` out of
presentation.xml. PowerPoint repairs that silently; Keynote reports the file
format as invalid and Quick Look hangs.
"""

import zipfile
from pathlib import Path

from lxml import etree

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
NOTES_MASTER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster"


TEMPLATES = Path(__file__).parent.parent / "sdpm" / "templates"
# blank-light has no notes master, so python-pptx makes one when notes are written.
# blank-dark ships with one already declared.
NO_NOTES_MASTER = TEMPLATES / "blank-light.pptx"
WITH_NOTES_MASTER = TEMPLATES / "blank-dark.pptx"


def _build(tmp_path: Path, slides: list[dict], template: Path = NO_NOTES_MASTER) -> Path:
    from sdpm.engine.builder import PPTXBuilder

    b = PPTXBuilder(str(template), fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"}, default_text_color="#FFFFFF")
    for slide in slides:
        b.add_slide(slide)
    out = tmp_path / "deck.pptx"
    b.save(out)
    return out


def _parts(path: Path):
    with zipfile.ZipFile(path) as z:
        pres = etree.fromstring(z.read("ppt/presentation.xml"))
        rels = etree.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
    return pres, rels


def _notes_master_rids(rels) -> list[str]:
    return [r.get("Id") for r in rels.findall("rel:Relationship", NS) if r.get("Type") == NOTES_MASTER]


def test_a_deck_with_notes_declares_its_notes_master(tmp_path):
    pres, rels = _parts(_build(tmp_path, [{"layout": "Blank", "elements": [], "notes": "Say hello."}]))
    declared = pres.findall("p:notesMasterIdLst/p:notesMasterId", NS)
    assert [d.get(f"{{{NS['r']}}}id") for d in declared] == _notes_master_rids(rels)
    # Schema order: right after the slide master list
    assert pres.find("p:sldMasterIdLst", NS).getnext().tag == f"{{{NS['p']}}}notesMasterIdLst"


def test_a_template_that_already_declares_it_keeps_one_declaration(tmp_path):
    slides = [
        {"layout": "Blank", "elements": [], "notes": "One."},
        {"layout": "Blank", "elements": [], "notes": "Two."},
    ]
    pres, rels = _parts(_build(tmp_path, slides, template=WITH_NOTES_MASTER))
    declared = pres.findall("p:notesMasterIdLst/p:notesMasterId", NS)
    assert [d.get(f"{{{NS['r']}}}id") for d in declared] == _notes_master_rids(rels)


def test_a_deck_without_notes_declares_no_notes_master(tmp_path):
    pres, rels = _parts(_build(tmp_path, [{"layout": "Blank", "elements": []}]))
    assert _notes_master_rids(rels) == []
    assert pres.find("p:notesMasterIdLst", NS) is None
