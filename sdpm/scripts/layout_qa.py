# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layout QA harness: objective quality metrics for the layout engine.

Runs the REAL engine pipeline (``sdpm.engine.layout.render.build_layout``, the same
one used by ``pptx_builder.py layout``) on a logical structure JSON, then
measures geometric quality:
  - crossings   : pairs of edge segments that intersect
  - pierces     : edge segments passing through a non-endpoint node icon
  - diagonals   : segments that are neither horizontal nor vertical
  - bad_ports   : first/last segment not perpendicular to its node edge
  - backwards   : first segment travels opposite to the port's outward normal

The pipeline and the metric definitions live in the ``sdpm.engine.layout`` package so
this harness and the CLI can never drift apart. This file is a thin CLI shim.

Usage:
  python3 layout_qa.py <input.json> [--width W] [--height H] [--json]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Re-exported for backward compatibility (e.g. layout_search.py imports these).
from sdpm.engine.layout.metrics import (  # noqa: E402,F401
    measure,
    measure_layout,
    score,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--width", type=int, default=1720)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    args = ap.parse_args()

    tree = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = measure(tree, args.width, args.height)

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return

    print(f"crossings={result['crossings']} pierces={result['pierces']} "
          f"group_pierces={result['group_pierces']} "
          f"diagonals={result['diagonals']} bad_ports={result['bad_ports']} "
          f"backwards={result['backwards']} size={result['size']}")
    print(f"overflow={result['overflow']} wirelength={result['wirelength']} "
          f"wire_norm={result['wire_norm']} aspect={result['aspect']} "
          f"score={result['score']}")
    for cat in ("pierces", "diagonals", "bad_ports", "backwards"):
        for d in result["detail"][cat]:
            print(f"  {cat}: {d}")


if __name__ == "__main__":
    main()
