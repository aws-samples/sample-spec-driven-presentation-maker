#!/usr/bin/env python3
"""postToolUse hook: auto-build PPTX after slide JSON edit.

Receives hook event JSON via stdin from kiro-cli.
Only triggers build when a slides/*.json file is written.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

SLIDES_PATTERN = re.compile(r".*/slides/[^/]+\.json$")


def main():
    event = json.load(sys.stdin)

    # Only act on fs_write to slides/*.json
    tool_input = event.get("tool_input", {})
    written_path = tool_input.get("path", "")
    if not SLIDES_PATTERN.search(written_path):
        return

    # Extract deck directory from path: .../SDPM-Presentations/{deckId}/slides/slug.json
    path = Path(written_path)
    slides_dir = path.parent
    deck_dir = slides_dir.parent
    slug = path.stem

    if not deck_dir.exists() or not (deck_dir / "deck.json").exists():
        return

    # Run Engine build + measure for the edited slug
    script_dir = Path(__file__).resolve().parent.parent.parent / "skill"
    build_code = f"""
import sys
sys.path.insert(0, {str(script_dir)!r})
from sdpm.api import generate, measure
result = generate(json_path=str({str(deck_dir)!r} + '/deck.json'))
print('build:', result)
m = measure(json_path=str({str(deck_dir)!r} + '/deck.json'), slides='{slug}')
print('measure:', m)
"""
    subprocess.run(
        [sys.executable, "-c", build_code],
        capture_output=True,
        text=True,
        timeout=120,
    )


if __name__ == "__main__":
    main()
