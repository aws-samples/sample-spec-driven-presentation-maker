# SPDX-License-Identifier: MIT-0
"""Generate a release's six manifests from scripts/release/manifest.toml and the CHANGELOG.

    uv run --no-project --python ">=3.11" python scripts/release/manifest.py --tag v0.13.0 --out dist/

writes ``release-{macos,linux,windows}-{install,update}.json``. The installer and
``sdpm update`` download exactly one of them per run (servers/local/checkout_update.py),
which is what GitHub's ``download_count`` counts. Every file is validated with the same
parser that reads it. ``--commit`` and ``--version`` are for tests (CI's v99 tags) only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "servers" / "local"))
import checkout_update  # noqa: E402
from client_config import local_install_notes  # noqa: E402

OSES = ("macos", "linux", "windows")
USES = ("install", "update")


def package_version(root: Path) -> str:
    text = (root / "sdpm" / "sdpm" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("sdpm/sdpm/__init__.py has no __version__")
    return match.group(1)


def python_minimum(root: Path) -> str:
    data = tomllib.loads((root / "servers" / "local" / "pyproject.toml").read_text(encoding="utf-8"))
    match = re.match(r"^\s*>=\s*(\d+(?:\.\d+)*)", data["project"]["requires-python"])
    if not match:
        raise SystemExit("servers/local/pyproject.toml: requires-python is not a >= floor")
    return match.group(1)


def tag_commit(root: Path, tag: str) -> str:
    res = subprocess.run(["git", "-C", str(root), "rev-parse", f"{tag}^{{commit}}"],  # nosec B603 B607
                         capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise SystemExit(f"git cannot resolve {tag}: {res.stderr.strip()}")
    return res.stdout.strip()


def build(source: dict, *, tag: str, version: str, commit: str, notes: list[str], python_min: str,
          os_name: str, use: str) -> dict:
    requires = []
    for name, item in source.get("requires", {}).items():
        minimum = python_min if name == "python" else item["min"]
        requires.append({"name": name, "min": minimum, "profiles": list(item["profiles"]),
                         "help": item["help"][os_name]})
    manifest = {
        "schema": 1, "version": version, "tag": tag, "commit": commit, "os": os_name, "use": use,
        "min_launcher": int(source["min_launcher"]), "requires": requires, "notes": notes,
    }
    checkout_update.parse_manifest(manifest, tag=tag, os_name=os_name, use=use)  # raises ValueError
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (tests)")
    parser.add_argument("--source", type=Path, help="manifest.toml (default: next to this file)")
    parser.add_argument("--commit", help="tests only: the commit to name instead of the tag's")
    parser.add_argument("--version", help="tests only: the version to name instead of sdpm's")
    args = parser.parse_args(argv)

    if checkout_update.parse_version(args.tag) is None:
        raise SystemExit(f"{args.tag} is not a stable release tag (vX.Y.Z)")
    version = args.version or package_version(args.root)
    if version != args.tag[1:]:
        raise SystemExit(f"sdpm/sdpm/__init__.py says {version}, the tag is {args.tag}")
    commit = args.commit or tag_commit(args.root, args.tag)
    source = tomllib.loads((args.source or Path(__file__).with_name("manifest.toml")).read_text(encoding="utf-8"))
    changelog = (args.root / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = [text.replace("**", "") for v, text in local_install_notes(changelog) if v == version]
    # The schema's limits (checkout_update.parse_manifest): 20 notes of 500 characters.
    notes = [n if len(n) <= 500 else n[:499] + "…" for n in notes[:20]]
    python_min = python_minimum(args.root)
    args.out.mkdir(parents=True, exist_ok=True)
    for os_name in OSES:
        for use in USES:
            manifest = build(source, tag=args.tag, version=version, commit=commit, notes=notes,
                             python_min=python_min, os_name=os_name, use=use)
            path = args.out / checkout_update.manifest_name(os_name, use)
            path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
