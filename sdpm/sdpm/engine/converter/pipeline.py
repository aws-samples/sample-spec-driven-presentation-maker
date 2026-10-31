# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""PPTX to JSON conversion pipeline.

Output structure (deck format — stable since pptx-import-edit):
    {output_dir}/
        ├── deck.json              # {fonts, defaultTextColor}  (template set by caller)
        ├── slides/
        │   ├── slide-001.json
        │   ├── slide-002.json
        │   └── ...
        └── images/                # extracted slide images

The in-memory ``result`` dict still contains ``{slides: [...], fonts, defaultTextColor}``
for callers that prefer the all-in-one structure (e.g. sdpm.engine.diff). Only the on-disk
layout changed — the legacy single ``slides.json`` is no longer written.
"""
import argparse
import sys
from pathlib import Path

from pptx import Presentation

from .color import extract_theme_colors_and_mapping
from .constants import conversion_scale
from .slide import extract_slide
from sdpm.utils.io import write_json
from sdpm.engine.schema.defaults import sort_element_keys
from sdpm.engine.timing.raw import RAW_MANIFEST_VERSION, RawSidecarWriter
from sdpm.engine.timing.reader import resolve_import_switches


def _source_provenance(pptx_path: Path) -> dict:
    """Return the authoring application the source package records.

    Provenance has to be stable, not a wall-clock stamp, so the sidecar
    manifest records where the XML came from (``docProps/app.xml``) rather than
    when it was converted. A package without those properties simply records
    nulls — guessing a version would be worse than admitting it is unknown.
    """
    import zipfile
    from xml.etree import ElementTree

    provenance = {
        "sourceFile": pptx_path.name,
        "sourceApplication": None,
        "sourceAppVersion": None,
        "sidecarSchema": RAW_MANIFEST_VERSION,
    }
    try:
        with zipfile.ZipFile(pptx_path) as package:
            data = package.read("docProps/app.xml")
    except (OSError, KeyError, zipfile.BadZipFile):
        return provenance
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return provenance
    for child in root:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "Application":
            provenance["sourceApplication"] = (child.text or "").strip() or None
        elif tag == "AppVersion":
            provenance["sourceAppVersion"] = (child.text or "").strip() or None
    return provenance


def pptx_to_json(
    pptx_path: Path,
    output_dir: Path = None,
    use_layout_names: bool = True,
    minimal: bool = False,
    existing_deck: dict = None,
):
    """Convert PPTX to JSON. Output is a deck-structure directory.

    Args:
        pptx_path: Input PPTX file.
        output_dir: Output directory (auto-derived from pptx_path stem if None).
        use_layout_names: Use layout names verbatim (else heuristic detection).
        minimal: Strip defaults for clean output.
        existing_deck: The current ``deck.json`` when this is a hand-edit sync
            rather than a new import. An explicit ``animations``/``transitions``
            switch in it is preserved; only a missing one is derived from the
            detected content (REQ-1.2).

    Returns:
        Dict with {slides, fonts, defaultTextColor} for in-memory consumers.

    On-disk output:
        deck.json  (fonts + defaultTextColor + animation/transition switches)
        slides/slide-{NNN}.json  (one per slide; NNN is 3-digit 1-based)
        images/   (unchanged — populated by extract_slide)
        media/    (semantic sound/media assets referenced by slide JSON)
        animations/  (raw timing/transition sidecars + hashed manifest)
    """
    actual_path = pptx_path
    prs = Presentation(str(actual_path))

    # Create output directory
    if output_dir is None:
        output_dir = pptx_path.with_suffix('')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    slides_dir = output_dir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    result: dict = {"slides": []}

    # Extract fonts from template
    try:
        from sdpm.engine.analyzer import extract_fonts
        result["fonts"] = extract_fonts(actual_path)
    except Exception:
        pass

    # Compute builder's default text color (from slide_masters[0])
    builder_text_color = None
    try:
        tc0, cm0, _ = extract_theme_colors_and_mapping(actual_path, 0)
        tx1_ref = cm0.get('tx1', 'dk1')
        builder_text_color = tc0.get(tx1_ref)
    except Exception:
        pass

    if builder_text_color:
        result["defaultTextColor"] = builder_text_color

    # Animation/transition preservation: one sidecar writer per deck, so the
    # whole dependency closure lands in one retainable subtree.
    sidecar_writer = RawSidecarWriter(output_dir, provenance=_source_provenance(actual_path))
    detected = {"animations": False, "transitions": False}

    # Scope the px scale to this deck's actual slide width (restored on exit)
    with conversion_scale(int(prs.slide_width)):
        for slide_idx, slide in enumerate(prs.slides):
            # Get slide master index
            slide_master = slide.slide_layout.slide_master
            master_idx = list(prs.slide_masters).index(slide_master)

            # Extract theme colors and mapping for this master
            theme_colors, color_mapping, theme_styles = extract_theme_colors_and_mapping(actual_path, master_idx)

            motion_out: dict = {}
            slide_dict = extract_slide(
                slide, theme_colors, color_mapping, theme_styles, master_idx, output_dir, slide_idx,
                pptx_path=actual_path, use_layout_names=use_layout_names, builder_text_color=builder_text_color,
                sidecar_writer=sidecar_writer, motion_out=motion_out,
            )
            for feature in detected:
                detected[feature] = detected[feature] or bool(motion_out.get(feature))
            slide_dict["elements"] = [sort_element_keys(e) for e in slide_dict.get("elements", [])]
            if minimal:
                from sdpm.engine.schema.minimal import minimize
                slide_dict["elements"] = minimize(slide_dict["elements"])
            result["slides"].append(slide_dict)

    # Write deck.json (fonts + defaultTextColor; template is caller's responsibility)
    deck_meta: dict = {}
    if "fonts" in result:
        deck_meta["fonts"] = result["fonts"]
    if "defaultTextColor" in result:
        deck_meta["defaultTextColor"] = result["defaultTextColor"]
    # Imported text must roundtrip verbatim — disable CJK↔Latin auto-spacing
    deck_meta["autoSpacing"] = False
    # Write slideSize from the source pptx (new-deck only — R4)
    from sdpm.engine import slide_size_px as _slide_size_px
    _w, _h = _slide_size_px(int(prs.slide_width), int(prs.slide_height))
    _pt_per_px = round((int(prs.slide_width) / 12700) / 1920, 6)
    deck_meta["slideSize"] = {"width": _w, "height": _h, "ptPerPx": _pt_per_px}
    # A new import writes each switch from detected content; a hand-edit sync
    # preserves an explicit switch and derives only a missing one (REQ-1.2).
    #
    # A switch that resolves to false *and* was not already explicit is left
    # out rather than written as `false`: the deck schema defines an absent
    # switch as disabled, so the two are the same deck, and REQ-9.4 requires an
    # ordinary still deck to import exactly as it did before this feature
    # existed. A deck that carries motion always gets both switches written, so
    # the enabled state is never implicit where it matters.
    switches = resolve_import_switches(detected, existing_deck)
    for feature, value in switches.items():
        was_explicit = isinstance((existing_deck or {}).get(feature), dict)
        if value["enabled"] or was_explicit or any(switches[f]["enabled"] for f in switches):
            deck_meta[feature] = value
    write_json(output_dir / "deck.json", deck_meta)
    sidecar_writer.write_manifest()

    # Write slides/slide-{NNN}.json (1-based, zero-padded, hyphen separator to match parse_outline_slugs).
    # 3-digit padding keeps lexicographic sort == presentation order for decks
    # up to 999 slides (2-digit broke ordering at 100+: "slide-100" < "slide-11").
    for idx, slide_dict in enumerate(result["slides"], start=1):
        slug = f"slide-{idx:03d}"
        slide_path = slides_dir / f"{slug}.json"
        write_json(slide_path, slide_dict)

    # Status output
    print(f"Converted: {output_dir}/")
    print("  deck.json")
    print(f"  slides/ ({len(result['slides'])} files)")
    images_dir = output_dir / "images"
    if images_dir.exists():
        count = len(list(images_dir.iterdir()))
        print(f"  images/ ({count} files)")

    return result


def main():
    parser = argparse.ArgumentParser(description="Convert PPTX to JSON (deck structure)")
    parser.add_argument("input", help="Input PPTX file")
    parser.add_argument("-o", "--output", help="Output directory (default: input filename without extension)")
    parser.add_argument("--minimal", action="store_true", help="Strip defaults, internal keys, and font tags for clean output")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output) if args.output else None
    pptx_to_json(input_path, output_dir, minimal=args.minimal)


if __name__ == "__main__":
    main()
