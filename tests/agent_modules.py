# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Import an agent/ module for a test without shadowing servers/remote's ``tools`` package.

agent/ and servers/remote/ both have a top-level ``tools`` package. ``factory`` is
imported first through test_mcp_parallel_connect._factory, which sets the other one
aside while it imports; the module asked for is then imported with agent/ on sys.path
only for the import.
"""

import importlib
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"


def load(name: str):
    from test_mcp_parallel_connect import _factory

    _factory()
    if name in sys.modules:
        return sys.modules[name]
    added = str(AGENT_DIR) not in sys.path
    if added:
        sys.path.insert(0, str(AGENT_DIR))
    try:
        return importlib.import_module(name)
    finally:
        if added:
            sys.path.remove(str(AGENT_DIR))
