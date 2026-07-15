# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Layout auto-direction search.

Given a logical-structure JSON where the LLM has fixed only the *group
nesting* (which icons belong to which group, and the relative order of
groups), this searches the orientation/alignment degrees of freedom the
engine is allowed to vary and picks the configuration that minimizes the
multi-objective score from layout_qa.score().

Degrees of freedom searched (group membership + relative order preserved):
  - direction : horizontal | vertical   (per group, including the root)
  - align     : start | center | end     (per group)
Child reordering is delegated to the engine's existing optimize_order(),
which measure() already invokes.

Usage:
  python3 layout_search.py <input.json> [--out best.json] [--align] [--top N]
"""

import argparse
import copy
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from layout_qa import measure  # noqa: E402

_DIRECTIONS = ("horizontal", "vertical")
_ALIGNS = ("start", "center", "end")
# Hard ceiling on raw config combinations before we fall back to a greedy
# coordinate-descent search instead of exhaustive enumeration. Each candidate
# runs the full scale/route/measure pipeline (~0.1-0.5s), so exhaustive is
# only viable for a handful of groups; greedy converges in O(rounds * n).
_EXHAUSTIVE_LIMIT = 64


def _collect_groups(tree):
    """Return (group_dict_refs) for the root and every nested group, in a
    stable pre-order. A "group" is any dict carrying a children/nodes list.
    The root tree itself counts as a group (its direction is the top-level
    layout axis)."""
    groups = []

    def walk(node, is_root=False):
        kids = node.get("children", node.get("nodes")) if isinstance(node, dict) else None
        if kids is None:
            return
        groups.append(node)
        for k in kids:
            walk(k)

    walk(tree, is_root=True)
    return groups


def _apply_config(tree, groups, dirs, aligns):
    """Mutate a deep copy's groups with the given direction/align vectors."""
    for g, d in zip(groups, dirs):
        g["direction"] = d
    if aligns is not None:
        for g, a in zip(groups, aligns):
            g["align"] = a
    return tree


def _eval(tree):
    try:
        m = measure(tree)
    except Exception as exc:  # noqa: BLE001 - degenerate configs can throw
        return None, str(exc)
    return m, None


def _exhaustive(base, search_align, top):
    groups = _collect_groups(base)
    n = len(groups)
    dir_space = list(itertools.product(_DIRECTIONS, repeat=n))
    results = []
    for dirs in dir_space:
        if search_align:
            align_space = itertools.product(_ALIGNS, repeat=n)
        else:
            align_space = [None]
        for aligns in align_space:
            cand = copy.deepcopy(base)
            cgroups = _collect_groups(cand)
            _apply_config(cand, cgroups, dirs, aligns)
            m, err = _eval(cand)
            if m is None:
                continue
            results.append((m["score"], dirs, aligns, m, cand))
    results.sort(key=lambda r: r[0])
    return results[:top], len(results)


def _greedy(base, search_align, rounds=4):
    """Coordinate descent: start from the input config, then repeatedly try
    flipping one group's direction (and optionally cycling its align),
    keeping any change that lowers the score. Converges fast on large trees
    where exhaustive 2^N is infeasible."""
    cur = copy.deepcopy(base)
    groups = _collect_groups(cur)
    n = len(groups)
    best_m, _ = _eval(cur)
    best_score = best_m["score"] if best_m else (1e9,)
    evals = 1
    for _ in range(rounds):
        improved = False
        for i in range(n):
            for d in _DIRECTIONS:
                aligns_opts = _ALIGNS if search_align else (None,)
                for a in aligns_opts:
                    cand = copy.deepcopy(cur)
                    cg = _collect_groups(cand)
                    cg[i]["direction"] = d
                    if a is not None:
                        cg[i]["align"] = a
                    m, _ = _eval(cand)
                    evals += 1
                    if m and m["score"] < best_score:
                        best_score, cur, best_m = m["score"], cand, m
                        improved = True
        if not improved:
            break
    return [(best_score, None, None, best_m, cur)], evals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", help="write best config to this path")
    ap.add_argument("--align", action="store_true", help="also search align")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--greedy", action="store_true", help="force greedy search")
    args = ap.parse_args()

    base = json.loads(Path(args.input).read_text(encoding="utf-8"))
    groups = _collect_groups(base)
    n = len(groups)
    combos = (2 ** n) * ((3 ** n) if args.align else 1)

    base_m, _ = _eval(base)
    print(f"groups={n}  combos={combos}  baseline score={base_m['score']}")

    use_greedy = args.greedy or combos > _EXHAUSTIVE_LIMIT
    if use_greedy:
        print(f"search=greedy (combos {combos} > {_EXHAUSTIVE_LIMIT})")
        top, evals = _greedy(base, args.align)
    else:
        print("search=exhaustive")
        top, evals = _exhaustive(base, args.align, args.top)
    print(f"evaluated {evals} configs")

    for rank, (sc, dirs, aligns, m, cand) in enumerate(top):
        print(f"#{rank+1} score={sc} cross={m['crossings']} pierce={m['pierces']} "
              f"back={m['backwards']} wire={m['wire_norm']} aspect={m['aspect']}")
        if dirs is not None:
            cg = _collect_groups(cand)
            for g, d in zip(cg, dirs):
                gid = g.get("id", "_root")
                print(f"     {gid}: {d}")

    best = top[0]
    if args.out:
        Path(args.out).write_text(
            json.dumps(best[4], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {args.out}  (score={best[0]})")


if __name__ == "__main__":
    main()
