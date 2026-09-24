# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Integration smoke test for the local MCP server.

Starts servers/local over real stdio (no mocks) and verifies that
filesystem-anchored resolution works end to end:
- the server boots and lists its tools,
- list_templates finds bundled templates,
- start_presentation serves the canonical orchestrator workflow.

This is the CI guard for the local-only surface (the v0.5 reviews found
that local-facing regressions slip through the mocked unit suite).

Run: uv run python scripts/smoke_local.py  (or: make smoke)
"""

import argparse
import asyncio
import json
import shlex
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def _text(result) -> str:
    return "".join(c.text for c in result.content if getattr(c, "text", None))


async def main(command: str | None = None) -> None:
    if command:
        command_parts = shlex.split(command)
        if not command_parts:
            raise ValueError("--command must not be empty")
    else:
        command_parts = [
            "uv", "run", "--directory", str(ROOT / "servers" / "local"), "python", "server.py",
        ]
    params = StdioServerParameters(command=command_parts[0], args=command_parts[1:])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            names = sorted(t.name for t in listed.tools)
            for required in ("list_templates", "start_presentation", "start_composing", "run_python", "generate_pptx", "check_specs"):
                assert required in names, f"tool missing: {required} (got {names})"

            # Real filesystem resolution: bundled templates must be found
            templates = json.loads(_text(await session.call_tool("list_templates", {})))
            assert templates.get("templates"), f"no templates resolved: {templates}"

            # Canonical role workflow served through the entry tool
            entry = json.loads(_text(await session.call_tool("start_presentation", {})))
            workflow = entry.get("static", {}).get("workflow", "")
            assert workflow, "orchestrator workflow is empty"
            assert entry.get("styles"), "start_presentation returned no styles"

            print(
                f"OK: {len(names)} tools, {len(templates['templates'])} templates, "
                f"orchestrator workflow served ({len(workflow)} chars)"
            )


# Hard cap so a hung server start fails fast instead of eating the CI
# job's default 6-hour limit.
_TIMEOUT_SECONDS = 120


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--command",
        help="server command to execute (default: checkout-based uv run)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(asyncio.wait_for(main(args.command), timeout=_TIMEOUT_SECONDS))
    except AssertionError as e:
        print(f"SMOKE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    except asyncio.TimeoutError:  # alias of TimeoutError on 3.11+, distinct on 3.10
        print(f"SMOKE FAILED: timed out after {_TIMEOUT_SECONDS}s (server hang?)", file=sys.stderr)
        sys.exit(1)
