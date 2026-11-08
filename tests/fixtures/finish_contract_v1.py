# SPDX-License-Identifier: MIT-0
"""A frozen copy of the ``finish`` parser of UPDATER_CONTRACT 1 (checkout_update.py).

Released versions keep this parser forever: a newer stage 1 that talks to an older target
passes only what this accepts. Never edit it; contract 2 gets its own file.
"""

from __future__ import annotations

import argparse

OPTIONS = ("--entry", "--previous", "--since", "--launcher", "--profile", "--agent-name", "--channel",
           "--register", "--non-interactive", "--prepared")


def parse(argv):
    parser = argparse.ArgumentParser(prog="finish (contract 1)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("finish")
    p.add_argument("--entry", choices=("install", "update", "adopt"), required=True)
    p.add_argument("--previous", default="")
    p.add_argument("--since", default="")
    p.add_argument("--launcher", required=True)
    p.add_argument("--profile", choices=("full", "mcp"), required=True)
    p.add_argument("--agent-name", default="sdpm")
    p.add_argument("--channel", choices=("release", "main"), default="release")
    p.add_argument("--register", choices=("default", "yes", "no"), default="default")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--prepared", choices=("all", "python"))
    return parser.parse_args(argv)
