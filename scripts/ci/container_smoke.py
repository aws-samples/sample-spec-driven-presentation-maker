# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Smoke-check a running runtime container from CI (.github/workflows/ci.yml).

    container_smoke.py mcp  http://localhost:8000/mcp   # MCP initialize + tools/list
    container_smoke.py ping http://localhost:8080/ping  # HTTP 200

Retries until the container answers or --timeout seconds pass, so it can run right
after `docker run -d`. Exits non-zero with the last error when it never answers.
"""

from __future__ import annotations

import argparse
import asyncio
import http.client
import sys
import time
from urllib.parse import urlsplit


async def _mcp(url: str) -> str:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url) as (read, write, _), ClientSession(read, write) as session:
        init = await session.initialize()
        tools = await session.list_tools()
    if not tools.tools:
        raise RuntimeError("tools/list returned no tools")
    return f"{init.serverInfo.name}: {len(tools.tools)} tools"


def _ping(url: str) -> str:
    parts = urlsplit(url)
    conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=5)
    try:
        conn.request("GET", parts.path or "/")
        status = conn.getresponse().status
    finally:
        conn.close()
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    return f"HTTP {status}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["mcp", "ping"])
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    parts = urlsplit(args.url)
    if parts.scheme != "http" or not parts.hostname:
        parser.error(f"expected an http:// URL, got {args.url!r}")

    deadline = time.monotonic() + args.timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = asyncio.run(_mcp(args.url)) if args.mode == "mcp" else _ping(args.url)
        except Exception as exc:  # noqa: BLE001 — retry on anything until the deadline
            last = exc
            time.sleep(2)
            continue
        print(f"OK: {result}")
        return 0
    print(f"FAIL: {args.url} did not answer within {args.timeout:.0f}s: {last!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
