"""The storyboard: one still frame per click, derived from the catalog.

The motion-path test here is a regression guard. The first implementation read
the catalog through an index method that does not exist and caught the
AttributeError, so every motion path silently contributed no offset while the
storyboard still produced plausible-looking frames. Only the rendered PNG
showed it, and only because the icon was somewhere it should not have been.
"""

import pytest

from sdpm.engine.storyboard import (
    DIM_TEXT,
    _entry,
    _motion_offset,
    click_steps,
    frame_slide,
    frames,
    storyboard,
)
from sdpm.engine.timing.writer import load_capability_index


@pytest.fixture(scope="module")
def index():
    return load_capability_index()


def _fx(effect_id, element, category, effect, start="onPageClick", **patch):
    out = {
        "id": effect_id,
        "target": {"element": element},
        "preset": {"category": category, "effect": effect},
        "start": {"type": start, "delayMs": 0},
        "timing": {"durationMs": 500},
    }
    for key in ("afterEffect", "text"):
        if key in patch:
            out[key] = patch.pop(key)
    if patch:
        out["timing"].update(patch)
    return out


def _slide(effects, elements=None, interactive=None, slide_id="probe"):
    return {
        "id": slide_id,
        "layout": "Blank",
        "elements": elements or [
            {"id": "a", "type": "shape", "shape": "rectangle",
             "x": 100, "y": 100, "width": 200, "height": 100, "fill": "#FFFFFF"},
            {"id": "b", "type": "shape", "shape": "rectangle",
             "x": 400, "y": 100, "width": 200, "height": 100, "fill": "#FFFFFF"},
            {"id": "icon", "type": "image", "src": "assets:material/train",
             "x": 150, "y": 120, "width": 40, "height": 40},
        ],
        "animations": {
            "mainSequence": effects,
            "interactiveSequences": interactive or [],
        },
    }


class TestClickSteps:
    def test_each_on_page_click_opens_a_step(self):
        steps = click_steps([
            _fx("1", "a", "entrance", "fade"),
            _fx("2", "b", "entrance", "fade", start="withPrevious"),
            _fx("3", "a", "emphasis", "pulse"),
        ])
        assert [[e["id"] for e in s] for s in steps] == [["1", "2"], ["3"]]

    def test_with_previous_and_after_previous_join_the_open_step(self):
        steps = click_steps([
            _fx("1", "a", "entrance", "fade"),
            _fx("2", "b", "entrance", "fade", start="afterPrevious"),
            _fx("3", "b", "entrance", "fade", start="withPrevious"),
        ])
        assert len(steps) == 1

    def test_a_sequence_that_does_not_open_with_a_page_click_still_starts_a_step(self):
        """The first thing in a sequence waits for the sequence's own trigger,
        so it is a step even when its start type is not onPageClick."""
        steps = click_steps([_fx("1", "a", "emphasis", "spin", start="onShapeClick")])
        assert len(steps) == 1

    def test_no_effects_means_no_steps(self):
        assert click_steps([]) == []

    def test_a_non_mapping_effect_is_skipped(self):
        assert click_steps(["nonsense", None]) == []


class TestFrameZero:
    def test_anything_an_entrance_reveals_starts_off_screen(self, index):
        result = frames(_slide([_fx("in", "a", "entrance", "fade")]), index)
        assert result[0]["state"]["a"]["visible"] is False

    def test_anything_with_no_entrance_is_on_screen_from_the_start(self, index):
        """This is the defect the storyboard was built to show: an icon with no
        entrance of its own hangs in empty space until its tile arrives."""
        result = frames(_slide([_fx("in", "a", "entrance", "fade")]), index)
        assert result[0]["state"]["icon"]["visible"] is True
        assert result[0]["state"]["b"]["visible"] is True

    def test_frame_zero_is_labelled_as_before_the_first_click(self, index):
        result = frames(_slide([_fx("in", "a", "entrance", "fade")]), index)
        assert result[0]["frame"] == 0
        assert "before the first click" in result[0]["label"]


class TestVisibility:
    def test_an_entrance_reveals_its_target_in_its_own_step(self, index):
        result = frames(_slide([_fx("in", "a", "entrance", "fade")]), index)
        assert result[1]["state"]["a"]["visible"] is True

    def test_an_exit_hides_its_target(self, index):
        result = frames(_slide([
            _fx("in", "a", "entrance", "fade"),
            _fx("out", "a", "exit", "fade"),
        ]), index)
        assert result[1]["state"]["a"]["visible"] is True
        assert result[2]["state"]["a"]["visible"] is False

    def test_visibility_comes_from_the_catalog_preset_class(self, index):
        """entrance.fade records no behaviours at all, only presetClass 'entr',
        so the reveal has to come from there rather than from a behaviour."""
        assert _entry(index, "entrance", "fade").get("presetClass") == "entr"
        assert _entry(index, "exit", "fade").get("presetClass") == "exit"

    def test_an_effect_aimed_at_a_missing_element_is_reported(self, index):
        result = frames(_slide([_fx("in", "ghost", "entrance", "fade")]), index)
        assert any("not an element on this slide" in n for n in result[1]["notes"])


class TestMotionPaths:
    def test_the_catalog_gives_the_path_end_as_an_offset(self, index):
        """motionPath.lines records path 'M 0 0 L 0 0.25 E' in slide-relative
        units, so on a 1080-high slide it ends 270px below where it started."""
        assert _motion_offset(_entry(index, "motionPath", "lines"), (1920, 1080)) == (0.0, 270.0)

    def test_a_motion_path_moves_its_target_in_the_frame(self, index):
        result = frames(_slide([_fx("move", "icon", "motionPath", "lines")]), index)
        assert result[1]["state"]["icon"]["dy"] == 270.0

    def test_the_offset_reaches_the_rendered_slide(self, index):
        """The guard for the swallowed-AttributeError bug: the offset has to
        survive all the way into the element's y, not just into the state."""
        slide = _slide([_fx("move", "icon", "motionPath", "lines")])
        result = frames(slide, index)
        derived = frame_slide(slide, result[1], "-f01")
        icon = next(e for e in derived["elements"] if e["id"] == "icon")
        assert icon["y"] == 120 + 270.0

    def test_a_rewound_path_ends_where_it_began(self, index):
        result = frames(_slide([_fx("move", "icon", "motionPath", "lines", rewind=True)]), index)
        assert result[1]["state"]["icon"]["dy"] == 0.0

    def test_an_effect_with_no_motion_behaviour_offsets_nothing(self, index):
        assert _motion_offset(_entry(index, "entrance", "wipe"), (1920, 1080)) == (0.0, 0.0)


class TestAfterEffects:
    def test_hide_removes_its_target_in_the_same_click(self, index):
        """Measured this session: masterRel='sameClick' on the effect's own
        end, so once the click has settled the element is already gone."""
        result = frames(_slide([
            _fx("in", "a", "entrance", "fade", afterEffect={"type": "hide"}),
        ]), index)
        assert result[1]["state"]["a"]["visible"] is False
        assert any("afterEffect hide" in n for n in result[1]["notes"])

    def test_hide_on_next_click_survives_its_own_click_and_goes_on_the_next(self, index):
        result = frames(_slide([
            _fx("in", "a", "entrance", "fade", afterEffect={"type": "hideOnNextClick"}),
            _fx("next", "b", "entrance", "fade"),
        ]), index)
        assert result[1]["state"]["a"]["visible"] is True
        assert result[2]["state"]["a"]["visible"] is False

    def test_dim_keeps_its_target_but_records_the_colour(self, index):
        result = frames(_slide([
            _fx("in", "a", "entrance", "fade",
                afterEffect={"type": "dim", "color": "#808080"}),
        ]), index)
        assert result[1]["state"]["a"]["visible"] is True
        assert result[1]["state"]["a"]["dim"] == "#808080"

    def test_a_dim_without_a_colour_records_the_theme_default(self, index):
        result = frames(_slide([
            _fx("in", "a", "entrance", "fade", afterEffect={"type": "dim"}),
        ]), index)
        assert result[1]["state"]["a"]["dim"] == "theme accent"

    def test_a_dimmed_element_has_its_text_recoloured_not_its_fill(self, index):
        """PowerPoint dims by animating ppt_c — the text colour — and leaves
        the fill alone. Dropping the fill's opacity instead made a correct
        recede look like a broken tile."""
        slide = _slide([_fx("in", "a", "entrance", "fade", afterEffect={"type": "dim"})])
        derived = frame_slide(slide, frames(slide, index)[1], "-f01")
        dimmed = next(e for e in derived["elements"] if e["id"] == "a")
        assert dimmed["fontColor"] == DIM_TEXT
        assert "opacity" not in dimmed
        assert dimmed["fill"] == "#FFFFFF"

    def test_a_dim_rewrites_the_inline_colour_tags_in_its_paragraphs(self, index):
        """A tile sets its colours with inline {{#RRGGBB:}} tags, so a dim that
        only set fontColor would visibly dim nothing."""
        elements = [
            {"id": "a", "type": "shape", "shape": "rectangle",
             "x": 100, "y": 100, "width": 200, "height": 100, "fill": "#FFFFFF",
             "paragraphs": [{"text": "{{#66666B:LABEL}}"}, {"text": "{{#1D1D1F:42%}}"}]},
        ]
        slide = _slide(
            [_fx("in", "a", "entrance", "fade", afterEffect={"type": "dim"})],
            elements=elements,
        )
        derived = frame_slide(slide, frames(slide, index)[1], "-f01")
        texts = [p["text"] for p in derived["elements"][0]["paragraphs"]]
        assert texts == [f"{{{{{DIM_TEXT}:LABEL}}}}", f"{{{{{DIM_TEXT}:42%}}}}"]

    def test_an_authors_dim_colour_is_used_instead_of_the_stand_in(self, index):
        slide = _slide([
            _fx("in", "a", "entrance", "fade",
                afterEffect={"type": "dim", "color": "#808080"}),
        ])
        derived = frame_slide(slide, frames(slide, index)[1], "-f01")
        assert next(e for e in derived["elements"] if e["id"] == "a")["fontColor"] == "#808080"

    def test_none_changes_nothing(self, index):
        result = frames(_slide([
            _fx("in", "a", "entrance", "fade", afterEffect={"type": "none"}),
        ]), index)
        assert result[1]["state"]["a"] == {
            "visible": True, "dx": 0.0, "dy": 0.0,
            "dim": None, "fill": None, "hiddenBy": None,
        }


class TestWhatAStillFrameCannotShow:
    def test_an_emphasis_is_recorded_as_showing_nothing(self, index):
        result = frames(_slide([
            _fx("in", "a", "entrance", "fade"),
            _fx("pulse", "a", "emphasis", "pulse"),
        ]), index)
        assert any("cannot show it" in n for n in result[2]["notes"])

    def test_an_emphasis_does_not_change_the_state(self, index):
        result = frames(_slide([
            _fx("in", "a", "entrance", "fade"),
            _fx("pulse", "a", "emphasis", "pulse"),
        ]), index)
        assert result[2]["state"]["a"]["visible"] is True
        assert result[2]["state"]["a"]["dx"] == 0.0


class TestRenderedFrame:
    def test_a_hidden_element_is_left_out_entirely(self, index):
        slide = _slide([_fx("in", "a", "entrance", "fade")])
        derived = frame_slide(slide, frames(slide, index)[0], "-f00")
        assert [e["id"] for e in derived["elements"]] == ["b", "icon"]

    def test_the_frame_slide_drops_animations_and_transition(self, index):
        slide = dict(_slide([_fx("in", "a", "entrance", "fade")]),
                     transition={"effect": "morph"})
        derived = frame_slide(slide, frames(slide, index)[1], "-f01")
        assert "animations" not in derived
        assert "transition" not in derived

    def test_each_frame_slide_gets_its_own_id(self, index):
        slide = _slide([_fx("in", "a", "entrance", "fade")])
        derived = frame_slide(slide, frames(slide, index)[1], "-f01")
        assert derived["id"] == "probe-f01"

    def test_the_source_slide_is_not_mutated(self, index):
        slide = _slide([_fx("move", "icon", "motionPath", "lines")])
        original = slide["elements"][2]["y"]
        frame_slide(slide, frames(slide, index)[1], "-f01")
        assert slide["elements"][2]["y"] == original


class TestInteractiveSequences:
    def test_a_trigger_sequence_gets_its_own_frame_after_the_run(self, index):
        slide = _slide(
            [_fx("in", "a", "entrance", "fade")],
            interactive=[{
                "id": "on-icon",
                "trigger": {"type": "onShapeClick", "target": "icon"},
                "effects": [_fx("reveal", "b", "entrance", "fade", start="onShapeClick")],
            }],
        )
        result = frames(slide, index)
        assert "after clicking 'icon'" in result[-1]["label"]
        assert "on-icon" in result[-1]["label"]


class TestStoryboard:
    def test_it_numbers_pages_across_slides_and_maps_them_back(self, index):
        deck = {"slideSize": {"width": 1920, "height": 1080}}
        slides = [
            _slide([_fx("in", "a", "entrance", "fade")], slide_id="one"),
            _slide([_fx("in", "a", "entrance", "fade")], slide_id="two"),
        ]
        _, frame_slides, manifest = storyboard(deck, slides, index)
        assert len(frame_slides) == len(manifest) == 4
        assert [m["page"] for m in manifest] == [1, 2, 3, 4]
        assert [m["slide"] for m in manifest] == ["one", "one", "two", "two"]
        assert [m["frame"] for m in manifest] == [0, 1, 0, 1]

    def test_it_flags_a_build_that_ends_with_an_element_off_screen(self, index):
        """The METHOD A defect: an afterEffect hide on the last step leaves a
        hole that neither the ordinary preview nor a round-trip check shows."""
        deck = {}
        slides = [_slide([
            _fx("in", "a", "entrance", "fade", afterEffect={"type": "hide"}),
        ], slide_id="holes")]
        _, _, manifest = storyboard(deck, slides, index)
        assert any("a off screen (afterEffect hide)" in n for n in manifest[-1]["notes"])

    def test_an_element_the_author_exited_is_not_called_stranded(self, index):
        """A motion-led deck sends its travelling parts off stage on purpose.
        Flagging those buries the real finding under noise."""
        deck = {}
        slides = [_slide([
            _fx("in", "a", "entrance", "fade"),
            _fx("out", "a", "exit", "fade", start="afterPrevious"),
        ], slide_id="departs")]
        _, _, manifest = storyboard(deck, slides, index)
        assert not any("off screen" in n for n in manifest[-1]["notes"])

    def test_the_stranding_note_names_why_each_element_is_gone(self, index):
        deck = {}
        slides = [_slide([
            _fx("in", "a", "entrance", "fade", afterEffect={"type": "hideOnNextClick"}),
            _fx("next", "b", "entrance", "fade"),
        ], slide_id="reasons")]
        _, _, manifest = storyboard(deck, slides, index)
        note = next(n for n in manifest[-1]["notes"] if "off screen" in n)
        assert "a off screen (afterEffect hideOnNextClick)" in note

    def test_a_clean_build_is_not_flagged(self, index):
        deck = {}
        slides = [_slide([
            _fx("in", "a", "entrance", "fade"),
            _fx("in-b", "b", "entrance", "fade"),
        ], slide_id="clean")]
        _, _, manifest = storyboard(deck, slides, index)
        assert not any("off screen" in n for n in manifest[-1]["notes"])

    def test_the_derived_deck_turns_animation_off(self, index):
        deck = {"animations": {"enabled": True}, "transitions": {"enabled": True}}
        derived, _, _ = storyboard(deck, [_slide([])], index)
        assert derived["animations"] == {"enabled": False}
        assert derived["transitions"] == {"enabled": False}

    def test_the_slide_size_is_taken_from_the_deck(self, index):
        """A path offset is a fraction of the slide, so the deck's own size has
        to reach it rather than the module default."""
        deck = {"slideSize": {"width": 960, "height": 540}}
        slides = [_slide([_fx("move", "icon", "motionPath", "lines")], slide_id="small")]
        _, frame_slides, _ = storyboard(deck, slides, index)
        icon = next(e for e in frame_slides[1]["elements"] if e["id"] == "icon")
        assert icon["y"] == 120 + 0.25 * 540

    def test_the_manifest_lists_what_is_on_and_off_screen(self, index):
        deck = {}
        slides = [_slide([_fx("in", "a", "entrance", "fade")], slide_id="one")]
        _, _, manifest = storyboard(deck, slides, index)
        assert manifest[0]["offScreen"] == ["a"]
        assert manifest[0]["onScreen"] == ["b", "icon"]


class TestTheBuildPointsAtTheStoryboard:
    """A deck with motion has to be told to look at its frames.

    The guide carries the rule, but a guide is only read when someone goes
    looking. The build output is read every time, so the count of animated
    slides is reported there and the CLI turns it into the command to run.
    """

    def _deck(self, tmp_path, *, animated, enabled=True):
        import json

        deck = tmp_path / "deck"
        (deck / "slides").mkdir(parents=True)
        (deck / "specs").mkdir()
        (deck / "deck.json").write_text(json.dumps({
            "template": "blank-light",
            "animations": {"enabled": enabled},
            "transitions": {"enabled": enabled},
            "slideSize": {"width": 1920, "height": 1080, "ptPerPx": 0.5},
        }))
        slide = {
            "id": "one",
            "layout": "Blank",
            "elements": [
                {"id": "a", "type": "shape", "shape": "rectangle", "x": 100, "y": 200,
                 "width": 400, "height": 200, "fill": "#FFFFFF"},
            ],
        }
        if animated:
            slide["animations"] = {
                "mainSequence": [{
                    "id": "in", "target": {"element": "a"},
                    "preset": {"category": "entrance", "effect": "fade"},
                    "start": {"type": "onPageClick", "delayMs": 0},
                    "timing": {"durationMs": 400},
                }],
                "interactiveSequences": [],
            }
        (deck / "slides/one.json").write_text(json.dumps(slide, ensure_ascii=False))
        (deck / "specs/outline.md").write_text("- [one] one\n")
        return deck

    def test_a_deck_with_motion_reports_how_many_slides_carry_it(self, tmp_path):
        from sdpm.api import generate

        deck = self._deck(tmp_path, animated=True)
        result = generate(str(deck), output_path=str(tmp_path / "out.pptx"))
        assert result["animated_slides"] == 1

    def test_a_deck_with_no_motion_reports_none(self, tmp_path):
        from sdpm.api import generate

        deck = self._deck(tmp_path, animated=False)
        result = generate(str(deck), output_path=str(tmp_path / "out.pptx"))
        assert result["animated_slides"] == 0

    def test_motion_switched_off_reports_none_even_though_the_slide_has_it(self, tmp_path):
        """The nudge follows what reached the package, not what the JSON says:
        a deck built with animations off has no build order to inspect."""
        from sdpm.api import generate

        deck = self._deck(tmp_path, animated=True, enabled=False)
        result = generate(str(deck), output_path=str(tmp_path / "out.pptx"))
        assert result["animated_slides"] == 0


def _bfx(effect_id, element, behaviors, start="onPageClick", **timing):
    """An effect in the advanced form: primitives instead of a gallery preset."""
    out = {
        "id": effect_id,
        "target": {"element": element},
        "behaviors": behaviors,
        "start": {"type": start, "delayMs": 0},
        "timing": {"durationMs": 800},
    }
    out["timing"].update(timing)
    return out


class TestDirectlyAuthoredBehaviors:
    """A motion-led deck is written almost entirely in the `behaviors` form.

    These effects carry no presetClass, so the first version of this module
    read only the catalog and silently did nothing for all of them: a packet
    authored to cross the slide stayed where it was, the markers it was meant
    to light stayed dark, and no note said anything was unmodelled. Only the
    rendered frame showed it.
    """

    def test_an_authored_motion_path_moves_its_target(self, index):
        slide = _slide([_bfx("fly", "icon", [
            {"type": "motion", "path": "M 0 0 C 0.16 -0.16 0.49 -0.16 0.6458 0 E",
             "pathEditMode": "relative", "origin": "layout"},
        ])])
        result = frames(slide, index, slide_size=(1920, 1080))
        assert round(result[1]["state"]["icon"]["dx"]) == round(0.6458 * 1920)
        assert result[1]["state"]["icon"]["dy"] == 0.0

    def test_the_authored_offset_reaches_the_rendered_slide(self, index):
        slide = _slide([_bfx("fly", "icon", [
            {"type": "motion", "path": "M 0 0 L 0.25 0 E"},
        ])])
        derived = frame_slide(slide, frames(slide, index)[1], "-f01")
        icon = next(e for e in derived["elements"] if e["id"] == "icon")
        assert icon["x"] == 150 + 0.25 * 1920

    def test_a_round_trip_path_is_noted_not_moved(self, index):
        """A hop that leaves and comes back ends where it began, so the frame
        cannot show the journey — and silence would read as "nothing happens"."""
        slide = _slide([_bfx("hop", "icon", [
            {"type": "motion", "path": "M 0 0 C 0.05 -0.07 0.13 -0.07 0.177 0 "
                                       "C 0.13 0.07 0.05 0.07 0 0 E"},
        ])])
        result = frames(slide, index)
        assert result[1]["state"]["icon"]["dx"] == 0.0
        assert any("leaves and returns" in n for n in result[1]["notes"])

    def test_a_path_that_settles_into_place_is_not_reported_as_motionless(self, index):
        """`M 0 0.035 L 0 0` is how a line of text rises into position: it
        starts displaced and finishes where it is authored. The frame shows
        that correctly, so warning about it would be crying wolf on the most
        ordinary motion idiom there is."""
        slide = _slide([_bfx("rise", "a", [
            {"type": "motion", "path": "M 0 0.035 L 0 0 E"},
        ])])
        result = frames(slide, index)
        assert result[1]["state"]["a"]["dy"] == 0.0
        assert result[1]["notes"] == []

    def test_a_reversed_path_ends_where_it_began(self, index):
        slide = _slide([_bfx("there-and-back", "icon", [
            {"type": "motion", "path": "M 0 0 L 0.25 0 E"},
        ], autoReverse=True)])
        result = frames(slide, index)
        assert result[1]["state"]["icon"]["dx"] == 0.0
        assert any("reversed" in n for n in result[1]["notes"])

    def test_a_colour_behaviour_recolours_its_target(self, index):
        slide = _slide([_bfx("light-up", "a", [{"type": "color", "to": "#3B5BFF"}])])
        result = frames(slide, index)
        assert result[1]["state"]["a"]["fill"] == "#3B5BFF"

    def test_a_colour_without_its_hash_is_still_understood(self, index):
        """The reader returns `3B5BFF`, so a re-imported deck must work too."""
        slide = _slide([_bfx("light-up", "a", [{"type": "color", "to": "3B5BFF"}])])
        assert frames(slide, index)[1]["state"]["a"]["fill"] == "#3B5BFF"

    def test_the_recolour_reaches_the_rendered_slide(self, index):
        slide = _slide([_bfx("light-up", "a", [{"type": "color", "to": "#3B5BFF"}])])
        derived = frame_slide(slide, frames(slide, index)[1], "-f01")
        assert next(e for e in derived["elements"] if e["id"] == "a")["fill"] == "#3B5BFF"

    def test_a_scale_is_named_as_something_the_frame_cannot_show(self, index):
        slide = _slide([_bfx("swell", "a", [{"type": "scale", "to": {"x": 1.4, "y": 1.4}}])])
        assert any("a scale that this frame cannot show" in n
                   for n in frames(slide, index)[1]["notes"])

    def test_a_rotation_is_named_too(self, index):
        slide = _slide([_bfx("spin", "a", [{"type": "rotation", "by": 360}])])
        assert any("a rotation that this frame cannot show" in n
                   for n in frames(slide, index)[1]["notes"])

    def test_a_set_of_visibility_reveals_its_target(self, index):
        slide = _slide([_bfx("show", "a", [
            {"type": "set", "attrName": "style.visibility", "to": "visible"},
        ])])
        assert frames(slide, index)[1]["state"]["a"]["visible"] is True

    def test_an_unmodelled_behaviour_is_named_rather_than_ignored(self, index):
        """The failure that mattered was silence, not inaccuracy."""
        slide = _slide([_bfx("odd", "a", [{"type": "property", "attrName": "ppt_w", "to": "2"}])])
        assert any("not modelled" in n for n in frames(slide, index)[1]["notes"])

    def test_an_unknown_behaviour_type_is_named(self, index):
        slide = _slide([_bfx("weird", "a", [{"type": "teleport"}])])
        assert any("unknown behavior 'teleport'" in n
                   for n in frames(slide, index)[1]["notes"])

    def test_motion_and_scale_in_one_effect_both_register(self, index):
        """One effect carrying several primitives is how a packet travels and
        shrinks at once; the storyboard has to read the whole list."""
        slide = _slide([_bfx("fly-and-shrink", "icon", [
            {"type": "motion", "path": "M 0 0 L 0.25 0 E"},
            {"type": "scale", "to": {"x": 0.5, "y": 0.5}},
        ])])
        result = frames(slide, index)
        assert result[1]["state"]["icon"]["dx"] == 0.25 * 1920
        assert any("a scale that this frame cannot show" in n for n in result[1]["notes"])
