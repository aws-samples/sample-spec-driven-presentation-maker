#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Read the per-effect settings PowerPoint for Mac actually offers, and where.

The capture plan for after-effects, sounds and timing was written from the
Windows documentation, which describes an **"Effect Options" dialog with
Effect / Timing / Text Animations tabs** reached by double-clicking an effect in
the Animation Pane. On PowerPoint for Mac 16.113.1 that dialog does not exist.

The settings sit inline in the Animation Pane as four ``disclosure`` sections
under a scroll area whose AX identifier is ``SettingsScrollView``. That matters
for more than tidiness:

* **No double-click is needed, and none is available.** The GUI driver posts no
  mouse events; it presses semantically. A plan that requires a double-click is
  unreachable, whereas every disclosure here answers ``AXPress``.
* **Two different surfaces are named ``Effect Options``** — the ribbon
  menubutton that carries the direction and shape options (the 133 measured
  effect-option values), and this disclosure. Resolving by name alone picks the
  wrong one.
* **Which sections exist depends on the selection.** With a motion path on a
  plain rectangle the read returns four sections and no SmartArt or Chart
  section, so those have to be re-read with such an object selected rather than
  assumed from the enumerators.

So this script reads the surface instead of planning against a document for a
different platform: it lists the disclosures, and opens each combobox under them
to record the options offered. It presses no value and saves no document.

## Mechanism, and why it differs from the other scripts

``gui_capture.py`` and ``discover_platform_inventory.py`` drive PowerPoint
through an in-repo pyobjc Accessibility client. This script instead shells out
to the ``agent-desktop`` CLI, because that is the client the 2026-11-02 reading
was taken with, and re-implementing it afterwards would mean the committed
fixture and the committed code had never met. The dependency is recorded in the
output so the provenance stays honest.

One measured constraint shapes the interface: **one popup per process.** Under
memory pressure a single write-type accessibility call held its lease 5-10 s,
and six popups chained into one process ran past the harness timeout and
produced nothing. Each ``--index`` run opens exactly one popup and appends to
the output file.

Usage::

    # which comboboxes are on offer for the current selection
    python scripts/animation_catalog/discover_pane_settings.py \\
      --window-id w-173062 --list

    # record one popup's options, repeat per index
    python scripts/animation_catalog/discover_pane_settings.py \\
      --window-id w-173062 --index 0 --out /abs/pane-settings.json

Prerequisites: the Animations ribbon tab selected, the ``Animation Pane``
switch on, an animated object selected, and the ``Effect Options`` and
``Timing`` disclosures expanded (``--expand`` does that).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

#: AX identifier of the scroll area holding the four disclosure sections.
SETTINGS_SCROLL_VIEW = "SettingsScrollView"

#: The sections a motion path on a plain rectangle returned on 2026-11-02.
KNOWN_SECTIONS = ("Effect Options", "Timing", "Text Animations", "Triggers")

#: A snapshot taken straight after the click returns TIMEOUT / ax_error -25204.
POPUP_SETTLE_SECONDS = 1.2


class PaneReadError(RuntimeError):
    """The accessibility surface could not be read."""


def _agent_desktop(session: str, *args: str) -> dict[str, Any]:
    """Run one ``agent-desktop`` command and return its parsed JSON."""
    completed = subprocess.run(
        ["agent-desktop", "--session", session, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PaneReadError(
            f"agent-desktop {' '.join(args)} returned no JSON: "
            f"{completed.stdout[:200]!r} {completed.stderr[:200]!r}"
        ) from exc


def _require(result: dict[str, Any], what: str) -> dict[str, Any]:
    if not result.get("ok"):
        code = (result.get("error") or {}).get("code", "unknown")
        message = (result.get("error") or {}).get("message", "")
        raise PaneReadError(f"{what} failed: {code} {message}")
    return result["data"]


def _find_settings_scroll_view(node: dict[str, Any]) -> dict[str, Any] | None:
    if (node.get("native_id") or {}).get("value") == SETTINGS_SCROLL_VIEW:
        return node
    for child in node.get("children") or []:
        found = _find_settings_scroll_view(child)
        if found is not None:
            return found
    return None


def _settings_view(session: str, window_id: str) -> dict[str, Any]:
    data = _require(
        _agent_desktop(session, "snapshot", "--window-id", window_id, "--max-depth", "12"),
        "window snapshot",
    )
    view = _find_settings_scroll_view(data["tree"])
    if view is None:
        raise PaneReadError(
            f"no {SETTINGS_SCROLL_VIEW} in window {window_id}; is the Animation Pane "
            "switch on, with an animated object selected?"
        )
    return view


def read_sections(session: str, window_id: str) -> list[dict[str, Any]]:
    """Return the disclosure sections offered for the current selection."""
    view = _settings_view(session, window_id)
    sections = []
    for child in view.get("children") or []:
        if child.get("role") != "disclosure":
            continue
        sections.append(
            {
                "name": child.get("name"),
                "axIdentifier": (child.get("native_id") or {}).get("value"),
                "expanded": child.get("value") == "1",
                "actions": child.get("available_actions") or [],
            }
        )
    return sections


def expand_sections(session: str, window_id: str, names: tuple[str, ...]) -> list[str]:
    """Expand the named disclosures; returns the ones verified expanded."""
    expanded = []
    for name in names:
        view = _settings_view(session, window_id)
        target = None
        for child in view.get("children") or []:
            if child.get("role") == "disclosure" and child.get("name") == name:
                target = child
                break
        if target is None:
            continue
        if target.get("value") == "1":
            expanded.append(name)
            continue
        result = _agent_desktop(session, "expand", target["ref_id"])
        if result.get("ok"):
            states = (result["data"].get("post_state") or {}).get("states") or []
            if "expanded" in states:
                expanded.append(name)
    return expanded


def read_comboboxes(session: str, window_id: str) -> list[dict[str, Any]]:
    """Return each combobox under the expanded sections, with its label.

    The label is a sibling ``statictext`` that precedes the control; the pane
    exposes no ``AXTitleUIElement`` link, so order is the only association.
    """
    view = _settings_view(session, window_id)
    found = []
    last_label = None
    for child in view.get("children") or []:
        if child.get("role") == "statictext":
            last_label = child.get("name")
        elif child.get("role") == "combobox":
            found.append(
                {
                    "label": last_label,
                    "current": child.get("value"),
                    "ref": child.get("ref_id"),
                    "axIdentifier": (child.get("native_id") or {}).get("value"),
                }
            )
    return found


def read_checkboxes(session: str, window_id: str) -> list[dict[str, Any]]:
    """Return each checkbox under the expanded sections and its default state.

    The state read here *is* the default only on an untouched effect, which is
    why it is recorded rather than inferred: ``Smooth Start`` and ``Smooth
    End`` came back **checked** on a motion path, so for those two it is the
    cleared state that has to be captured.
    """
    view = _settings_view(session, window_id)
    return [
        {
            "label": child.get("name"),
            "checked": child.get("value") == "1",
            "axIdentifier": (child.get("native_id") or {}).get("value"),
        }
        for child in view.get("children") or []
        if child.get("role") == "checkbox"
    ]


def read_popup(session: str, window_id: str, index: int) -> dict[str, Any]:
    """Open one combobox, record the options it offers, and close it."""
    boxes = read_comboboxes(session, window_id)
    if index >= len(boxes):
        raise PaneReadError(f"index {index} out of range; {len(boxes)} comboboxes offered")
    box = boxes[index]
    print(f"opening [{index}] {box['label']!r} current={box['current']!r}", file=sys.stderr)

    _require(_agent_desktop(session, "click", box["ref"]), f"click {box['label']!r}")
    time.sleep(POPUP_SETTLE_SECONDS)

    menu = _agent_desktop(
        session, "snapshot", "--surface", "menu", "--app", "Microsoft PowerPoint", "--max-depth", "4"
    )
    items: list[dict[str, Any]] = []
    menu_name = None
    error = None
    if menu.get("ok"):
        tree = menu["data"]["tree"]
        menu_name = tree.get("name")

        def walk(node: dict[str, Any]) -> None:
            if node.get("role") in ("menuitem", "button") and node.get("name"):
                items.append(
                    {
                        "label": node["name"],
                        "role": node["role"],
                        "checked": "checked" in (node.get("states") or []),
                    }
                )
            for child in node.get("children") or []:
                walk(child)

        walk(tree)
    else:
        error = (menu.get("error") or {}).get("code")

    # Leave the pane as it was found, whatever the read did.
    _agent_desktop(session, "press", "escape")

    return {
        "index": index,
        "label": box["label"],
        "current": box["current"],
        "menuName": menu_name,
        "itemCount": len(items),
        "items": items,
        "error": error,
    }


#: Metadata describing the run, re-applied on every write so a file started by
#: an earlier revision of this script does not keep that revision's fields.
def _metadata(window_id: str) -> dict[str, Any]:
    return {
        "record": "paneSettings",
        "application": "Microsoft PowerPoint",
        "version": "16.113.1",
        "platform": "macOS",
        "mechanism": "macOS Accessibility API via the agent-desktop CLI",
        "window": window_id,
        "finding": (
            "this build has no 'Effect Options' dialog with Effect / Timing / Text "
            "Animations tabs. Those settings are inline in the Animation Pane as "
            "disclosure sections under a scroll area identified SettingsScrollView, "
            "every one of which answers AXPress, so no double-click is needed and "
            "none is available to a semantic driver."
        ),
    }


def _load_or_start(out: Path, window_id: str) -> dict[str, Any]:
    document: dict[str, Any] = {"popups": {}}
    if out.exists():
        document = json.loads(out.read_text())
        document.setdefault("popups", {})
    document.update(_metadata(window_id))
    return document


def _write(out: Path, document: dict[str, Any]) -> None:
    out.write_text(json.dumps(document, indent=2) + "\n")


def _merge_popup(out: Path, record: dict[str, Any], window_id: str) -> None:
    document = _load_or_start(out, window_id)
    document["popups"][str(record["index"])] = record
    _write(out, document)


def _merge_structure(
    out: Path,
    window_id: str,
    selection: str,
    sections: list[dict[str, Any]],
    checkboxes: list[dict[str, Any]],
) -> None:
    """Record the sections and checkbox states read for one kind of selection.

    Keyed by ``selection`` because both are selection-dependent: the section
    list differs for a SmartArt graphic, and a checkbox's state is only a
    default for the effect type it was read on.
    """
    document = _load_or_start(out, window_id)
    document.setdefault("structure", {})[selection] = {
        "sections": sections,
        "checkboxes": checkboxes,
        "defaultsOn": sorted(box["label"] for box in checkboxes if box["checked"]),
    }
    _write(out, document)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-id", required=True, help="from agent-desktop list-windows")
    parser.add_argument("--session", default="pane-settings", help="snapshot namespace")
    parser.add_argument("--list", action="store_true", help="list sections and comboboxes")
    parser.add_argument("--expand", action="store_true", help="expand Effect Options and Timing")
    parser.add_argument("--index", type=int, help="read one combobox's popup")
    parser.add_argument(
        "--structure",
        action="store_true",
        help="record the disclosure sections and checkbox states for --selection",
    )
    parser.add_argument(
        "--selection",
        default="motionPathOnRectangle",
        help="what is selected, since sections and defaults depend on it",
    )
    parser.add_argument("--out", type=Path, help="append the record here")
    args = parser.parse_args()

    try:
        if args.expand:
            expanded = expand_sections(args.session, args.window_id, ("Effect Options", "Timing"))
            print(f"expanded: {expanded}")

        if args.list:
            print("sections:")
            for section in read_sections(args.session, args.window_id):
                state = "expanded" if section["expanded"] else "collapsed"
                print(f"  {section['name']!r} {state} ax={section['axIdentifier']}")
            print("comboboxes:")
            for i, box in enumerate(read_comboboxes(args.session, args.window_id)):
                print(f"  [{i}] {box['label']!r} current={box['current']!r}")
            print("checkboxes:")
            for box in read_checkboxes(args.session, args.window_id):
                print(f"  {box['label']!r} checked={box['checked']}")
            return 0

        if args.structure:
            if args.out is None:
                parser.error("--structure needs --out")
            sections = read_sections(args.session, args.window_id)
            checkboxes = read_checkboxes(args.session, args.window_id)
            _merge_structure(
                args.out, args.window_id, args.selection, sections, checkboxes
            )
            on = [box["label"] for box in checkboxes if box["checked"]]
            print(f"sections: {[s['name'] for s in sections]}")
            print(f"checkboxes: {len(checkboxes)}, on by default: {on}")
            print(f"wrote {args.out}")
            return 0

        if args.index is None:
            parser.error("pass --list, --expand, --structure or --index N")

        record = read_popup(args.session, args.window_id, args.index)
        print(f"\n=== [{record['index']}] {record['label']!r} ({record['itemCount']} items)")
        if record["error"]:
            print(f"    READ FAILED: {record['error']}")
        for item in record["items"]:
            print(f"    {item['role']:9} {item['label']!r}{' checked' if item['checked'] else ''}")
        if args.out:
            _merge_popup(args.out, record, args.window_id)
            print(f"\nwrote {args.out}")
        return 0
    except PaneReadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
