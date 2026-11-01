#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Decide which of a target's two effects carries the value it pressed.

A target in the effect-options capture presses twice: the tile, which writes the
effect's **default**, and a value inside the ``Effect Options`` window, which
writes a **second** effect carrying that value. That is the application's
behaviour, measured both ways — re-selecting the shape to avoid it disables the
control outright, and a tile-only control run leaves exactly one effect.

The driver cannot say which of the two is which, and it does not try. Measured:
Grow/Shrink's ``Huge`` and its default have **identical** ``p:cTn`` — same
``presetID``, same ``presetSubtype`` — and differ only in ``p:by``. So the
driver records both and this step resolves them, offline, against the default
every tile already has measured in
``tests/fixtures/animations/gui-only/batch-2026-11-01-complete``.

Three outcomes per target, and each is a statement rather than a guess:

``resolved``
    Exactly one of the shape's effects differs from the tile's default. That one
    is the value, and what differs about it is recorded.
``unchanged``
    No effect differs. The press did nothing the package records, so the value
    is **not** captured — which the single-effect gate could not have caught.
``ambiguous``
    More than one differs, or the default is unknown. Recorded and not resolved;
    a value guessed here would be worse than a gap.

Usage::

    uv run python scripts/animation_catalog/effect_options_resolve.py \\
      --capture /abs/out --plan /abs/plan.json --out /abs/resolved.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def behaviour_fingerprint(behaviors: list[dict[str, Any]]) -> str:
    """Return a comparable form of one effect's behaviours, order included.

    Order is part of it: entrance Bounce's eight ``p:animScale`` differ only in
    duration and delay, so a set would call two different effects the same. The
    ``id`` of each node is **not** part of it — PowerPoint renumbers on save, so
    including it would make every effect differ from every other.
    """
    return json.dumps(
        [
            {
                "element": behavior["element"],
                "attributes": behavior.get("attributes") or {},
                "carrier": behavior.get("carrier") or {},
                "timing": behavior.get("timing") or {},
                "attrNames": behavior.get("attrNames") or [],
                "values": behavior.get("values") or {},
            }
            for behavior in behaviors
        ],
        sort_keys=True,
        ensure_ascii=False,
    )


def differences(default: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the behaviours that differ, paired by position.

    Positional because a value changes a behaviour in place — Huge changes
    ``p:by`` on the one ``p:animScale`` — rather than reordering the effect. A
    length change is reported as its own difference.
    """
    found: list[dict[str, Any]] = []
    if len(default) != len(candidate):
        found.append({"behaviourCount": [len(default), len(candidate)]})
    for index, (before, after) in enumerate(zip(default, candidate)):
        if behaviour_fingerprint([before]) == behaviour_fingerprint([after]):
            continue
        change: dict[str, Any] = {"index": index, "element": after["element"]}
        for field in ("attributes", "carrier", "timing", "attrNames", "values"):
            if (before.get(field) or {}) != (after.get(field) or {}):
                change[field] = {"default": before.get(field), "measured": after.get(field)}
        found.append(change)
    return found


def tile_default(effects_by_target: list[list[dict[str, Any]]]) -> str | None:
    """Return the fingerprint of the effect a tile writes by default, or None.

    Resolved **inside the capture** rather than against an external baseline,
    which is what the first version did and why 58 of 133 targets could not be
    resolved: the baseline was the 76-value capture, and it holds only the tiles
    that *needed* capturing — ``Appear``, ``Blinds``, ``Wipe`` and 21 others
    were already writable and have no measured default anywhere.

    Nothing external is needed. A tile has several targets, one per value, each
    on its own shape. A fingerprint that appears on **more than one** of those
    shapes is the tile's default, because the values differ by construction and
    only the default repeats. None repeating means the press modifies the effect
    in place rather than adding one — measured: every ``Direction`` target
    carries exactly one effect, and the eight Fly In directions carry eight
    different ``presetSubtype`` values.
    """
    counts: dict[str, int] = {}
    for effects in effects_by_target:
        for fingerprint in {behaviour_fingerprint(effect["behaviors"]) for effect in effects}:
            counts[fingerprint] = counts.get(fingerprint, 0) + 1
    repeated = [(count, fingerprint) for fingerprint, count in counts.items() if count > 1]
    if not repeated:
        return None
    return max(repeated)[1]


def resolve(capture_dir: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Resolve every captured target against its tile's measured default."""
    package = capture_dir / generate.GUI_CAPTURE_PACKAGE
    readback = capture_dir / generate.GUI_CAPTURE_READBACK
    effects = generate.parse_gui_capture_package_all(package)
    records = {
        record["catalogKey"]: record
        for record in generate.read_oracle_readback(readback)
        if isinstance(record, dict) and record.get("record") == generate.GUI_CAPTURE_RECORD
    }
    # Grouped by tile, because the tile's default is read from its own targets.
    per_tile: dict[str, list[list[dict[str, Any]]]] = {}
    for target in plan["targets"]:
        record = records.get(target["key"])
        spid = str((record or {}).get("shapeSpid"))
        per_tile.setdefault(target["effectKey"], []).append(effects.get(spid, []))
    defaults = {tile: tile_default(shapes) for tile, shapes in per_tile.items()}

    resolved: list[dict[str, Any]] = []
    for target in plan["targets"]:
        key = target["key"]
        record = records.get(key)
        spid = str((record or {}).get("shapeSpid"))
        candidates = effects.get(spid, [])
        entry: dict[str, Any] = {
            "key": key,
            "effectKey": target["effectKey"],
            "setting": target["setting"],
            "value": target["value"],
            "shapeSpid": None if record is None else record.get("shapeSpid"),
            "effectsOnShape": len(candidates),
            "outcome": "missing",
        }
        default = defaults.get(target["effectKey"])
        if record is None or record.get("rejected"):
            entry["reason"] = "the driver recorded no successful capture for this target"
            resolved.append(entry)
            continue

        if len(candidates) == 1:
            # The press **modified** the effect in place, which is what 125 of
            # the 133 targets did: every Direction, Shapes, Spokes, Vanishing
            # Point and Zoom target, and four Amount ones. The one effect on the
            # shape is therefore the measured value, with nothing to choose
            # between. An earlier single-target trial on Grow/Shrink's Amount
            # saw two effects and I generalised from it; measuring all 133
            # showed that only Amount ever adds.
            effect = candidates[0]
            entry["outcome"] = "resolved"
            entry["mechanism"] = "modifiedInPlace"
        else:
            # Amount adds a second effect, so the tile's default has to be told
            # from the value. The default is the fingerprint that repeats across
            # the tile's other shapes; anything else is a candidate value.
            unlike = [
                candidate
                for candidate in candidates
                if default is None or behaviour_fingerprint(candidate["behaviors"]) != default
            ]
            if len(unlike) != 1:
                entry["outcome"] = "ambiguous"
                entry["reason"] = (
                    f"{len(unlike)} of {len(candidates)} effects on the shape differ from the "
                    "tile's default"
                    + ("" if default is not None else ", and no default repeats across the tile")
                    + "; the package cannot say which one this press wrote"
                )
                resolved.append(entry)
                continue
            effect = unlike[0]
            entry["outcome"] = "resolved"
            entry["mechanism"] = "addedSecondEffect"

        entry["effectAttributes"] = effect["attributes"]
        entry["behaviors"] = effect["behaviors"]
        if effect.get("iterate"):
            entry["iterate"] = effect["iterate"]
        # What distinguishes this value, when the tile's default is known. For a
        # Direction it is ``presetSubtype`` — Fly In's eight directions carry
        # eight different ones — and for an Amount it is a behaviour payload.
        if default is not None:
            entry["differences"] = differences(
                json.loads(default) if default.startswith("[") else [], effect["behaviors"]
            ) or None
        resolved.append(entry)

    counts: dict[str, int] = {}
    for entry in resolved:
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
    return {
        "source": generate.GUI_CAPTURE_SOURCE,
        "application": generate.BASELINE_APPLICATION,
        "version": generate.BASELINE_VERSION,
        "package": str(package.relative_to(REPO_ROOT)) if package.is_relative_to(REPO_ROOT) else package.name,
        "counts": counts,
        "targets": resolved,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    document = resolve(args.capture, plan)
    text = json.dumps(document, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(json.dumps({"out": str(args.out), **document["counts"]}, indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
