# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Media timing and object animations must coexist.

python-pptx's ``add_movie`` writes ``p:video`` by calling
``CT_Slide.get_or_add_childTnLst``, which deletes any existing ``p:timing``;
issue 954 documents the package corruption that follows when a direct
``p:timing`` ends up beside timing wrapped in ``mc:AlternateContent``. The
writer therefore runs after every media object exists, harvests the media
nodes, and rebuilds exactly one timing tree. With animations switched off the
media timing has to survive untouched in spirit: the video still plays.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation

from sdpm.engine.builder import PPTXBuilder
from sdpm.engine.timing import (
    ShapeIdentityRegistry,
    media_timing_nodes,
    remove_timing,
    write_slide_timing,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "sdpm" / "templates" / "blank-dark.pptx"
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}


@pytest.fixture()
def media_dir(tmp_path):
    """A workspace holding a tiny MP4 and a poster frame."""
    (tmp_path / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128)
    (tmp_path / "second.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128)
    return tmp_path


def _effect(effect_id="fx", element="caption"):
    return {
        "id": effect_id,
        "target": {"element": element},
        "preset": {"category": "entrance", "effect": "fade", "variant": None},
        "start": {"type": "onPageClick", "delayMs": 0},
        "timing": {"durationMs": 500},
        "afterEffect": {"type": "none"},
        "sound": None,
    }


def _slide(*, videos=1, animations=True, transition=None):
    elements = [
        {
            "id": f"clip{index}" if index else "clip",
            "type": "video",
            "src": "clip.mp4" if index == 0 else "second.mp4",
            "x": 10 + index * 400,
            "y": 10,
            "width": 320,
            "height": 180,
        }
        for index in range(videos)
    ]
    elements.append(
        {"id": "caption", "type": "textbox", "text": "Caption", "x": 10, "y": 260, "width": 300, "height": 60}
    )
    slide = {"id": "media", "layout": "Blank", "elements": elements}
    if animations:
        slide["animations"] = {"mainSequence": [_effect()], "interactiveSequences": []}
    if transition is not None:
        slide["transition"] = transition
    return slide


def _build(slide_def, media_dir, *, animations=True, transitions=False):
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        base_dir=media_dir,
        animations_enabled=animations,
        transitions_enabled=transitions,
    )
    slide = builder.add_slide(slide_def)
    return builder, etree.fromstring(etree.tostring(slide._element)), slide


def _timing(root):
    found = root.findall("{%s}timing" % NS["p"])
    assert len(found) == 1, "a slide must carry exactly one timing representation"
    return found[0]


# --- coexistence -----------------------------------------------------------


def test_video_timing_and_object_animations_share_one_timing_tree(media_dir):
    builder, root, slide_obj = _build(_slide(), media_dir)
    timing = _timing(root)
    assert timing.xpath(".//p:video", namespaces=NS), "the video play controls survive"
    assert timing.xpath(".//p:seq[p:cTn/@nodeType='mainSeq']", namespaces=NS)
    report = builder.timing_reports[-1]
    assert report["mediaNodes"] == 1
    assert report["effects"] == 1
    assert report["removedRepresentations"] == 1, "python-pptx's own tree was replaced, not duplicated"


def test_the_media_node_is_the_last_child_of_the_time_root(media_dir):
    _builder, root, slide_obj = _build(_slide(), media_dir)
    children = [
        etree.QName(node).localname
        for node in _timing(root).xpath("./p:tnLst/p:par/p:cTn/p:childTnLst/*", namespaces=NS)
    ]
    assert children == ["seq", "video"]


def test_media_and_animation_ctn_ids_stay_unique(media_dir):
    _builder, root, slide_obj = _build(_slide(videos=2), media_dir)
    timing = _timing(root)
    ids = timing.xpath(".//p:cTn/@id", namespaces=NS)
    assert len(ids) == len(set(ids))
    assert len(timing.xpath(".//p:video", namespaces=NS)) == 2


def test_the_media_target_still_points_at_its_own_shape(media_dir):
    builder, root, slide_obj = _build(_slide(), media_dir)
    clip_spid = builder.identity_registries["media"].resolve("clip")
    caption_spid = builder.identity_registries["media"].resolve("caption")
    timing = _timing(root)
    assert timing.xpath(".//p:video//p:spTgt/@spid", namespaces=NS) == [str(clip_spid)]
    assert str(caption_spid) in timing.xpath(".//p:seq//p:spTgt/@spid", namespaces=NS)
    assert clip_spid != caption_spid


def test_animations_off_keeps_the_video_timing(media_dir):
    builder, root, slide_obj = _build(_slide(animations=True), media_dir, animations=False)
    timing = _timing(root)
    assert timing.xpath(".//p:video", namespaces=NS)
    assert timing.xpath(".//p:seq", namespaces=NS) == [], "no object-animation branch"
    report = builder.timing_reports[-1]
    assert report["mediaNodes"] == 1 and report["effects"] == 0


def test_animations_off_without_media_writes_no_timing(media_dir):
    _builder, root, slide_obj = _build(_slide(videos=0), media_dir, animations=False)
    assert root.findall("{%s}timing" % NS["p"]) == []


def test_a_transition_does_not_disturb_media_timing(media_dir):
    _builder, root, slide_obj = _build(
        _slide(animations=False, transition={"effect": "fade", "parameters": {}, "durationMs": 700}),
        media_dir,
        animations=False,
        transitions=True,
    )
    order = [etree.QName(child).localname for child in root]
    assert order == ["cSld", "clrMapOvr", "AlternateContent", "timing"]
    assert _timing(root).xpath(".//p:video", namespaces=NS)


# --- issue 954 -------------------------------------------------------------


def test_a_second_timing_representation_is_collapsed(media_dir):
    """A direct p:timing beside AlternateContent timing is the 954 corruption."""
    _builder, _root, slide_obj = _build(_slide(animations=False), media_dir, animations=False)
    hostile = etree.fromstring(
        '<mc:AlternateContent xmlns:mc="%s" xmlns:p="%s">'
        '<mc:Choice Requires="p14"><p:timing><p:tnLst/></p:timing></mc:Choice>'
        "<mc:Fallback><p:timing><p:tnLst/></p:timing></mc:Fallback>"
        "</mc:AlternateContent>" % (NS["mc"], NS["p"])
    )
    slide_obj._element.append(hostile)
    assert len(slide_obj._element.xpath(".//*[local-name()='timing']")) == 3

    registry = ShapeIdentityRegistry("media")
    report = write_slide_timing(slide_obj._element, {"id": "media"}, registry, animations_enabled=False)
    root = etree.fromstring(etree.tostring(slide_obj._element))
    assert report["removedRepresentations"] == 2
    assert len(root.xpath(".//*[local-name()='timing']")) == 1
    assert root.xpath(".//p:video", namespaces=NS), "the real media node was preserved"
    assert root.xpath("./mc:AlternateContent", namespaces=NS) == []


def test_a_wrapper_that_also_carries_a_transition_is_refused_not_deleted(media_dir):
    """Collapsing the slide to one timing representation must not take the
    transition in the same ``mc:AlternateContent`` with it."""
    from sdpm.engine.timing import TimingWriteError

    _builder, _root, slide_obj = _build(_slide(animations=False), media_dir, animations=False)
    mixed = etree.fromstring(
        '<mc:AlternateContent xmlns:mc="%s" xmlns:p="%s">'
        '<mc:Choice Requires="p14"><p:transition><p:fade/></p:transition>'
        "<p:timing><p:tnLst/></p:timing></mc:Choice>"
        "</mc:AlternateContent>" % (NS["mc"], NS["p"])
    )
    slide_obj._element.append(mixed)
    with pytest.raises(TimingWriteError) as error:
        remove_timing(slide_obj._element)
    assert "will not delete the other content" in str(error.value)
    assert slide_obj._element.xpath(".//*[local-name()='transition']")


def test_media_nodes_are_harvested_from_both_forms():
    slide = Presentation().slides.add_slide(Presentation().slide_layouts[6])
    xml = (
        '<p:sld xmlns:p="%s" xmlns:mc="%s"><p:cSld><p:spTree/></p:cSld>'
        '<p:timing><p:tnLst><p:par><p:cTn id="1"><p:childTnLst>'
        '<p:video><p:cMediaNode><p:cTn id="2"/><p:tgtEl><p:spTgt spid="4"/></p:tgtEl></p:cMediaNode></p:video>'
        "</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>"
        '<mc:AlternateContent><mc:Choice Requires="p14"><p:timing><p:tnLst><p:par><p:cTn id="1">'
        '<p:childTnLst><p:audio><p:cMediaNode><p:cTn id="3"/>'
        '<p:tgtEl><p:spTgt spid="5"/></p:tgtEl></p:cMediaNode></p:audio>'
        "</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing></mc:Choice></mc:AlternateContent>"
        "</p:sld>" % (NS["p"], NS["mc"])
    )
    root = etree.fromstring(xml)
    harvested = media_timing_nodes(root)
    assert [etree.QName(node).localname for node in harvested] == ["video", "audio"]
    assert remove_timing(root) == 2
    assert root.xpath(".//*[local-name()='timing']") == []
    assert slide is not None  # the fixture slide is only here to prove no pptx state is needed


def test_the_builder_creates_media_before_resolving_targets(media_dir):
    """REQ-6.1: the timing writer runs after every shape and media object."""
    builder, root, slide_obj = _build(_slide(), media_dir)
    registry = builder.identity_registries["media"]
    assert set(registry.ids()) == {"clip", "caption"}
    timing = _timing(root)
    spids = {int(value) for value in timing.xpath(".//p:spTgt/@spid", namespaces=NS)}
    shape_ids = {int(value) for value in root.xpath(".//p:cNvPr/@id", namespaces=NS)}
    assert spids and spids <= shape_ids, "every target points at a real shape"


# --- the saved package -----------------------------------------------------


def test_the_saved_package_reopens_with_one_timing_tree(media_dir, tmp_path):
    builder = PPTXBuilder(
        TEMPLATE,
        fonts={"fullwidth": "Meiryo", "halfwidth": "Arial"},
        default_text_color="#FFFFFF",
        base_dir=media_dir,
        animations_enabled=True,
        transitions_enabled=True,
    )
    builder.add_slide(_slide(transition={"effect": "morph", "parameters": {"variant": "byObject"}, "durationMs": 800}))
    out = tmp_path / "media.pptx"
    builder.save(out)

    reopened = Presentation(str(out))
    root = etree.fromstring(etree.tostring(list(reopened.slides)[0]._element))
    timing = _timing(root)
    assert timing.xpath(".//p:video", namespaces=NS)
    assert timing.xpath(".//p:seq[p:cTn/@nodeType='mainSeq']", namespaces=NS)
    assert [etree.QName(child).localname for child in root] == [
        "cSld",
        "clrMapOvr",
        "AlternateContent",
        "timing",
    ]
    media_parts = [name for name in reopened.part.package.iter_parts()]
    assert any("media" in str(part.partname) for part in media_parts), "the video part is still packaged"
