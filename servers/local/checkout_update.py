# SPDX-License-Identifier: MIT-0
"""Bring an installed checkout (``~/.sdpm/checkout``) to the fetched ``main``.

``sdpm update`` and the installer fetch ``main``, then run this file *as of the fetched
commit* (taken from ``FETCH_HEAD``, before anything is checked out). So the newest version
of these steps runs even over an old checkout, and the shell launchers only fetch and
hand over. Standard library only; any Python 3.8+ runs it.

Local changes to tracked files block a fast-forward ("Your local changes to the following
files would be overwritten"). They are mostly files an earlier version's tools rewrote
(``sdpm/uv.lock``, ``web-ui/next-env.d.ts``), but they may be the user's own edits, so they
are never discarded: they go into a git stash named after the update, and the command that
brings them back is printed. Nothing is reset or cleaned; untracked files are not touched.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import List, Optional

BRANCH = "main"
# The Troubleshooting entry that covers a stopped update.
HELP = "https://github.com/aws-samples/sample-spec-driven-presentation-maker/blob/main/docs/en/getting-started.md#sdpm-update-stops"
# The stash is a commit; git refuses to make one without an identity, which a machine that
# only ever ran the installer may not have.
_IDENTITY = ["-c", "user.name=sdpm update", "-c", "user.email=sdpm-update@localhost"]


def _git(checkout: str, *args: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(  # nosec B603 B607 - fixed git commands on the local checkout
        ["git", "-C", checkout, *args],
        capture_output=capture, text=True, encoding="utf-8", errors="replace", check=False,
    )


def local_changes(checkout: str) -> List[str]:
    """``git status --porcelain`` lines of the tracked files that differ from HEAD."""
    out = _git(checkout, "status", "--porcelain", "--untracked-files=no")
    return [line for line in out.stdout.splitlines() if line.strip()]


def set_aside(checkout: str) -> Optional[str]:
    """Stash the tracked changes under a name that says where they came from; the stash commit."""
    head = _git(checkout, "rev-parse", "--short", "HEAD").stdout.strip() or "unknown"
    message = f"sdpm update {time.strftime('%Y-%m-%d %H:%M')} (local changes on {head})"
    if _git(checkout, *_IDENTITY, "stash", "push", "--quiet", "-m", message, capture=False).returncode != 0:
        return None
    return _git(checkout, "rev-parse", "--verify", "-q", "refs/stash").stdout.strip() or None


def _quote(path: str) -> str:
    return f'"{path}"'


def pull(checkout: str) -> int:
    """Set local changes aside, check out main and fast-forward it to FETCH_HEAD."""
    out, err = sys.stdout, sys.stderr
    stash = None
    changes = local_changes(checkout)
    if changes:
        stash = set_aside(checkout)
        if stash is None:
            print(f"Could not move the local changes in {checkout} to a git stash; nothing was changed.", file=err)
            print(f"  See {HELP}.", file=err)
            return 1
        print(f"  Local changes in {checkout} were set aside (git stash) so the update can pull:", file=out)
        for line in changes:
            print(f"    {line}", file=out)
        print("  If you did not edit these files, an earlier version's tools wrote them: nothing to do.", file=out)
        print(f"  To bring them back: git -C {_quote(checkout)} stash apply {stash}", file=out)
    steps = (
        ("check out main", ["checkout", "-q", BRANCH]),
        ("fast-forward main", ["merge", "--ff-only", "-q", "FETCH_HEAD"]),
    )
    for what, args in steps:
        if _git(checkout, *args, capture=False).returncode != 0:
            print(f"sdpm update could not {what} in {checkout} (git's message above). Nothing was discarded.", file=err)
            if stash:
                print(f"  Your local changes are in stash {stash}: git -C {_quote(checkout)} stash apply {stash}", file=err)
            print(f"  See {HELP}.", file=err)
            return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # A Windows pipe has the ANSI code page; show '?' for what it cannot encode, never fail.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="checkout_update.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--checkout", required=True, help="the installed checkout")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("pull", help="set local changes aside, check out main, fast-forward to FETCH_HEAD")
    args = parser.parse_args(argv)
    if args.command == "pull":
        return pull(args.checkout)
    return 2


if __name__ == "__main__":
    sys.exit(main())
