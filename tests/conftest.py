# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Test configuration — add mcp-server/ and skill/ to sys.path."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "mcp-server"))
sys.path.insert(0, str(_root / "skill"))
