#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Generate and validate the deterministic Morph package spike."""

from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml import parse_xml
from pptx.util import Inches

MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
P159_NS = "http://schemas.microsoft.com/office/powerpoint/2015/09/main"
MORPH_OPTIONS = ("byObject", "byWord", "byChar")
MORPH_NAME_PREFIX = "!!"
MORPH_NAME = "!!sdpm-morph-hero"


def morph_name(morph_id: str) -> str:
    """Return PowerPoint's documented forced-Morph object name."""
    if not isinstance(morph_id, str) or not morph_id.strip():
        raise ValueError("morphId must be a non-empty string")
    if morph_id.startswith(MORPH_NAME_PREFIX):
        raise ValueError("morphId must not include PowerPoint's !! prefix")
    return f"{MORPH_NAME_PREFIX}sdpm-morph-{morph_id}"


def validate_slide_morph_ids(morph_ids: list[str]) -> None:
    """Reject ambiguous forced-Morph identities on one slide."""
    seen: set[str] = set()
    for morph_id in morph_ids:
        name = morph_name(morph_id)
        if name in seen:
            raise ValueError(f"duplicate morphId on one slide: {morph_id}")
        seen.add(name)


def morph_transition_xml(option: str, duration_ms: int = 800) -> str:
    """Return PowerPoint-compatible Morph with a legacy fade fallback."""
    if option not in MORPH_OPTIONS:
        raise ValueError(f"unsupported Morph option {option!r}; expected one of {MORPH_OPTIONS}")
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms <= 0:
        raise ValueError("Morph durationMs must be a positive integer")
    return (
        f'<mc:AlternateContent xmlns:mc="{MC_NS}">'
        f'<mc:Choice xmlns:p159="{P159_NS}" Requires="p159">'
        f'<p:transition xmlns:p="{P_NS}" xmlns:p14="{P14_NS}" p14:dur="{duration_ms}">'
        f'<p159:morph option="{option}"/>'
        "</p:transition>"
        "</mc:Choice>"
        f'<mc:Fallback><p:transition xmlns:p="{P_NS}"><p:fade/></p:transition></mc:Fallback>'
        "</mc:AlternateContent>"
    )


def insert_transition(slide, transition_xml: str) -> None:
    """Insert a transition after clrMapOvr and before timing/extLst."""
    root = slide._element
    for child in list(root):
        local = etree.QName(child).localname
        if local == "transition":
            root.remove(child)
        elif local == "AlternateContent" and child.xpath(".//*[local-name()='transition']"):
            root.remove(child)

    transition = parse_xml(transition_xml)
    insertion = len(root)
    for index, child in enumerate(root):
        if etree.QName(child).localname in {"timing", "extLst"}:
            insertion = index
            break
    root.insert(insertion, transition)


def build_probe(output_path: Path) -> Path:
    """Build source plus Object/Word/Character Morph destination slides."""
    prs = Presentation()
    blank = prs.slide_layouts[6]
    geometries = (
        (1.0, 2.0, 2.0, 1.0),
        (6.0, 3.0, 3.0, 1.5),
        (2.0, 4.0, 4.0, 1.0),
        (5.0, 1.0, 2.5, 2.0),
    )
    for index, (x, y, width, height) in enumerate(geometries):
        slide = prs.slides.add_slide(blank)
        shape = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(x),
            Inches(y),
            Inches(width),
            Inches(height),
        )
        shape.name = MORPH_NAME
        shape.text = "Morph target"
        if index:
            insert_transition(slide, morph_transition_xml(MORPH_OPTIONS[index - 1]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output_path)
    return output_path


def _slide_xml(package: zipfile.ZipFile, index: int):
    return etree.fromstring(package.read(f"ppt/slides/slide{index}.xml"))


def verify_package(path: Path) -> dict:
    """Verify names, options, fallback, namespaces, and child ordering."""
    findings: list[str] = []
    with zipfile.ZipFile(path) as package:
        for slide_index in range(1, 5):
            root = _slide_xml(package, slide_index)
            names = root.xpath(".//p:cNvPr/@name", namespaces={"p": P_NS})
            if MORPH_NAME not in names:
                findings.append(f"slide {slide_index}: missing forced Morph name")
            if slide_index == 1:
                if root.xpath(".//*[local-name()='transition']"):
                    findings.append("slide 1: source slide must not have a transition")
                continue

            option = MORPH_OPTIONS[slide_index - 2]
            choices = root.xpath(
                "./mc:AlternateContent/mc:Choice[@Requires='p159']/p:transition/p159:morph",
                namespaces={"mc": MC_NS, "p": P_NS, "p159": P159_NS},
            )
            if len(choices) != 1 or choices[0].get("option") != option:
                findings.append(f"slide {slide_index}: Morph option {option} missing")
            fallbacks = root.xpath(
                "./mc:AlternateContent/mc:Fallback/p:transition/p:fade",
                namespaces={"mc": MC_NS, "p": P_NS},
            )
            if len(fallbacks) != 1:
                findings.append(f"slide {slide_index}: fade fallback missing")
            children = [etree.QName(child).localname for child in root]
            ac_index = children.index("AlternateContent") if "AlternateContent" in children else -1
            for later in ("timing", "extLst"):
                if later in children and ac_index > children.index(later):
                    findings.append(f"slide {slide_index}: transition follows {later}")

    if findings:
        raise ValueError("; ".join(findings))
    return {"slides": 4, "options": list(MORPH_OPTIONS), "forcedName": MORPH_NAME}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-package", action="store_true")
    args = parser.parse_args()
    if not args.output and not args.verify_package:
        parser.error("pass --output or --verify-package")

    if args.verify_package:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = build_probe(Path(temp_dir) / "morph-probe.pptx")
            print(json.dumps(verify_package(path), sort_keys=True))
        return

    path = build_probe(args.output)
    print(json.dumps(verify_package(path), sort_keys=True))
    print(path)


if __name__ == "__main__":
    main()
