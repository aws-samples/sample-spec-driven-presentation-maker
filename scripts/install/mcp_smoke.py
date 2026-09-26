# SPDX-License-Identifier: MIT-0
"""Speak MCP to a stdio command and confirm initialize + tools/list succeed.

Used by CI (and `sdpm doctor`) to prove the launcher path delivers clean JSON-RPC —
a launcher hop that writes anything of its own to stdout breaks every client.
Usage: python mcp_smoke.py <command> [args...]
"""

from __future__ import annotations

import json
import subprocess
import sys


def _send(proc: subprocess.Popen, msg: dict) -> None:
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def _recv(proc: subprocess.Popen, want_id: int) -> dict:
    while True:
        line = proc.stdout.readline()
        if not line:
            raise SystemExit(f"server closed stdout before answering id={want_id}")
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            raise SystemExit(f"non-JSON on stdout (launcher pollution?): {line[:200]!r}")
        if msg.get("id") == want_id:
            return msg


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "sdpm-smoke", "version": "0"}}})
        init = _recv(proc, 1)
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = _recv(proc, 2)["result"]["tools"]
        names = {t["name"] for t in tools}
        for required in ("start_presentation", "start_composing", "generate_pptx"):
            if required not in names:
                raise SystemExit(f"tool missing: {required}")
        print(f"OK: {init['result']['serverInfo']['name']} — {len(tools)} tools over {' '.join(argv)}")
        return 0
    finally:
        proc.kill()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
