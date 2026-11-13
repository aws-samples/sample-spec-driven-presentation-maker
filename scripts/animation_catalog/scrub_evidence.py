#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Remove the operator's identity from a captured PowerPoint package.

Every ``.pptx`` under ``tests/fixtures/animations`` was saved by PowerPoint on a
maintainer's machine, and PowerPoint writes **who saved it** into the package:
``dc:creator`` and ``cp:lastModifiedBy`` in ``docProps/core.xml``, plus
``Company`` and ``Manager`` in ``docProps/app.xml``. This repository is public,
so publishing those fixtures unscrubbed publishes a person's name — found by
audit on all seven committed packages before the first push.

The fixtures themselves are evidence and are not the problem: the OOXML the
capture measured is the whole point of keeping them. Only the authorship
metadata goes.

``--check`` is what CI and :mod:`tests.test_animation_catalog` run, so a new
fixture added without scrubbing fails a test rather than reaching a release.

Usage::

    uv run python scripts/animation_catalog/scrub_evidence.py --check
    uv run python scripts/animation_catalog/scrub_evidence.py --write
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO_ROOT / "tests" / "fixtures" / "animations"

#: ``part -> the elements whose text identifies a person or an organisation``.
#: Emptied rather than deleted: the schema allows an empty value, and removing
#: the element outright would make the package differ from one PowerPoint wrote
#: in a way that has nothing to do with the capture.
IDENTIFYING = {
    "docProps/core.xml": ("dc:creator", "cp:lastModifiedBy"),
    "docProps/app.xml": ("Company", "Manager"),
}


def _element_pattern(name: str) -> re.Pattern[str]:
    """Match one element with non-empty text, and nothing else.

    Narrow on purpose: a blunt pass over the whole part could empty an element
    that happens to share a suffix, and a fixture is evidence — a scrub that
    changes more than authorship would quietly corrupt a measurement.
    """
    return re.compile(rf"(<{re.escape(name)}>)([^<]+)(</{re.escape(name)}>)")


def identities_in(package: Path) -> dict[str, str]:
    """Return ``element -> value`` for every identifying field the package carries."""
    found: dict[str, str] = {}
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        for part, elements in IDENTIFYING.items():
            if part not in names:
                continue
            text = archive.read(part).decode("utf-8", "replace")
            for element in elements:
                match = _element_pattern(element).search(text)
                if match and match.group(2).strip():
                    found[element] = match.group(2)
    return found


def scrub(package: Path) -> dict[str, str]:
    """Empty the identifying fields in place. Returns what was removed.

    The package is rewritten through a temporary file and moved over the
    original, so an interrupted run leaves the fixture intact rather than
    truncated.
    """
    removed = identities_in(package)
    if not removed:
        return {}
    with zipfile.ZipFile(package) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    rewritten: list[tuple[zipfile.ZipInfo, bytes]] = []
    for info, blob in entries:
        elements = IDENTIFYING.get(info.filename)
        if elements:
            text = blob.decode("utf-8", "replace")
            for element in elements:
                text = _element_pattern(element).sub(r"\1\3", text)
            blob = text.encode("utf-8")
        rewritten.append((info, blob))
    with tempfile.NamedTemporaryFile(dir=package.parent, suffix=".pptx", delete=False) as handle:
        temporary = Path(handle.name)
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as out:
        for info, blob in rewritten:
            out.writestr(info, blob)
    shutil.move(str(temporary), str(package))
    return removed


def packages(root: Path) -> list[Path]:
    """Every captured package under ``root``, in a stable order."""
    return sorted(path for path in root.rglob("*.pptx") if not path.name.startswith("~$"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--check", action="store_true", help="fail if any package names a person")
    parser.add_argument("--write", action="store_true", help="empty the identifying fields")
    args = parser.parse_args(argv)
    if not args.check and not args.write:
        parser.error("pass --check or --write")

    found = {
        package: identities_in(package)
        for package in packages(args.root)
    }
    carrying = {package: fields for package, fields in found.items() if fields}

    if args.check:
        for package, fields in carrying.items():
            print(
                f"FAIL: {package.relative_to(REPO_ROOT)} names "
                + ", ".join(f"{name}={value!r}" for name, value in sorted(fields.items())),
                file=sys.stderr,
            )
        print(f"{len(found)} package(s) checked, {len(carrying)} carrying an identity")
        return 1 if carrying else 0

    for package, fields in carrying.items():
        scrub(package)
        print(
            f"scrubbed {package.relative_to(REPO_ROOT)}: "
            + ", ".join(f"{name}={value!r}" for name, value in sorted(fields.items()))
        )
    print(f"{len(found)} package(s) checked, {len(carrying)} scrubbed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
