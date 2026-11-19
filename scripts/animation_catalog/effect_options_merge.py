#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Merge every effect-option capture into one measured value per target, and refuse a guess.

``effect_options_resolve.py`` turns one capture into resolved targets. The 133
values did not come from one capture: a press inside the ``Effect Options``
window is intermittent, so values that came back equal to their effect's
default had to be measured again on decks of their own. This merges those
captures, later ones winning, and then checks the result is actually a
measurement rather than a default recorded by accident.

## The check that matters

Two values of the same setting cannot produce the same OOXML. ``From Bottom``
and ``From Right`` are different directions; if both resolve to
``presetSubtype 4`` then one press did not take and the capture recorded the
effect's default in its place. That is not a hypothetical — it is how three of
these values read until they were measured again:

===================================  =================  ======================
Value                                Recorded           Measured on a clean deck
===================================  =================  ======================
``entrance.flyIn`` From Right        ``presetSubtype`` 4  ``presetSubtype`` 2
``entrance.stretch`` From Top        ``presetSubtype`` 10 ``presetSubtype`` 1
``emphasis.transparency`` 25%        ``opacity: 0.5``     ``opacity: 0.75``
===================================  =================  ======================

The comparison is over the preset attributes **and** the behaviours, because
some settings do not touch ``presetSubtype`` at all: ``Spin``'s direction is
the sign of ``p:animRot/@by`` and both its values carry ``presetSubtype 0``.
Comparing presets alone reports those as collisions when they are measured
correctly, and comparing behaviours alone would miss nothing but says less.

Usage::

    uv run python scripts/animation_catalog/effect_options_merge.py \\
      --plan tests/fixtures/animations/gui-only/effect-options-capture-2026-11-02/plan.json \\
      --resolved .../effect-options-capture-2026-11-02/resolved.json \\
      --resolved .../effect-options-remeasure-2026-11-02/resolved.json \\
      --out /abs/merged-effect-options.json

    uv run python scripts/animation_catalog/effect_options_merge.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
GUI_ONLY = REPO_ROOT / "tests" / "fixtures" / "animations" / "gui-only"

#: The plan that names all 133 targets, and every capture that measured any of
#: them, **in the order they were taken**. A later capture wins, because the
#: reason a target was captured again is that the earlier reading was refused.
DEFAULT_PLAN = GUI_ONLY / "effect-options-capture-2026-11-02" / "plan.json"
#: Every capture is a directory carrying its own ``plan.json``,
#: ``powerpoint-oracle.pptx`` and ``powerpoint-readback.jsonl``, so every value
#: here can be re-derived by re-running ``effect_options_resolve.py``. Two
#: earlier re-runs (``quarter-spin-resolved.json`` and
#: ``spin-reopen-resolved.json``) could not: they were resolved in a scratch
#: directory and only the result was committed, so the package their values
#: came from no longer exists. Their two values were measured again as
#: ``spin-amounts/`` and agreed, which is why they could be dropped rather than
#: trusted.
DEFAULT_RESOLVED = (
    GUI_ONLY / "effect-options-capture-2026-11-02" / "resolved.json",
    GUI_ONLY / "effect-options-remeasure-2026-11-02" / "resolved.json",
    GUI_ONLY / "effect-options-remeasure-2026-11-02" / "spin-amounts" / "resolved.json",
    GUI_ONLY / "effect-options-remeasure-2026-11-02" / "from-right" / "resolved.json",
    GUI_ONLY / "effect-options-remeasure-2026-11-02" / "stretch-from-top" / "resolved.json",
    GUI_ONLY / "effect-options-remeasure-2026-11-02" / "transparency-25" / "resolved.json",
)


def signature(target: dict[str, Any]) -> str:
    """A comparable string for one measured value: its preset and its behaviours."""
    return json.dumps(
        {
            "preset": target.get("effectAttributes", {}),
            "behaviors": target.get("behaviors", []),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def merge(plan: dict[str, Any], resolved_documents: list[tuple[Path, dict[str, Any]]]):
    """Return ``key -> measured target`` plus the targets still missing."""
    planned = {target["key"]: target for target in plan["targets"]}
    merged: dict[str, dict[str, Any]] = {}
    for source, document in resolved_documents:
        for target in document.get("targets", []):
            if target.get("outcome") != "resolved":
                continue
            key = target["key"]
            if key not in planned:
                continue
            merged[key] = {**target, "measuredIn": source.relative_to(REPO_ROOT).as_posix()}
    missing = sorted(key for key in planned if key not in merged)
    return merged, missing


def collisions(merged: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return every group where two values of one setting produced the same OOXML."""
    groups: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for target in merged.values():
        groups[(target["effectKey"], target["setting"])][signature(target)].append(
            target["value"]
        )
    found = []
    for (effect_key, setting), by_signature in sorted(groups.items()):
        for values in by_signature.values():
            if len(values) > 1:
                found.append(
                    {
                        "effectKey": effect_key,
                        "setting": setting,
                        "values": sorted(values),
                    }
                )
    return found


def build(plan_path: Path, resolved_paths: list[Path]) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    documents = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in resolved_paths]
    merged, missing = merge(plan, documents)
    found = collisions(merged)
    settings: dict[str, int] = defaultdict(int)
    for target in merged.values():
        settings[target["setting"]] += 1
    return {
        "source": "sdpm GUI capture",
        "application": "Microsoft PowerPoint",
        "version": "16.113.1",
        "plan": plan_path.relative_to(REPO_ROOT).as_posix(),
        "captures": [path.relative_to(REPO_ROOT).as_posix() for path in resolved_paths],
        "counts": {
            "planned": len(plan["targets"]),
            "measured": len(merged),
            "missing": len(missing),
            "collisions": len(found),
            "effects": len({t["effectKey"] for t in merged.values()}),
            "bySetting": dict(sorted(settings.items())),
        },
        "missing": missing,
        "collisions": found,
        "targets": [merged[key] for key in sorted(merged)],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--resolved", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any target is unmeasured or two values collide",
    )
    args = parser.parse_args(argv)

    resolved_paths = args.resolved or [path for path in DEFAULT_RESOLVED if path.exists()]
    document = build(args.plan, resolved_paths)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    print(json.dumps({"counts": document["counts"]}, indent=2, ensure_ascii=False))
    if document["missing"]:
        print("\nunmeasured:", file=sys.stderr)
        for key in document["missing"]:
            print(f"  {key}", file=sys.stderr)
    if document["collisions"]:
        print("\ntwo values of one setting produced the same OOXML:", file=sys.stderr)
        for group in document["collisions"]:
            print(
                f"  {group['effectKey']} {group['setting']}: {group['values']}",
                file=sys.stderr,
            )
    if args.check and (document["missing"] or document["collisions"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
