#!/usr/bin/env python3
"""Install sdpm support for Kiro CLI.

Idempotent installer that wires this repository checkout into Kiro CLI:

1. Registers the ``sdpm`` MCP server in the global ``~/.kiro/settings/mcp.json``
   via ``kiro-cli mcp add`` (skipped if already registered). Use ``--agent NAME``
   to register it into a specific agent config instead.
2. Cleans up artifacts left behind by older installers (pre-v0.5 skill
   symlinks, the legacy ``~/.kiro/agents/sdpm-composer.json``) — conservatively:
   anything that does not match the known generated form is left in place
   with a warning.

No agent definitions are installed: mode behavior (vibe/spec/style/composer/
single) is served by the MCP server itself via the ``start_presentation(mode=...)``
tool, and composer sub-agents are self-spawned by the orchestrating agent
following the persona's spawn template.

The repository stays the single source of truth: ``git pull`` updates take
effect without re-running this script. Re-run only if you move the checkout.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent

KIRO_HOME = Path.home() / ".kiro"
AGENTS_DEST = KIRO_HOME / "agents"
GLOBAL_MCP_JSON = KIRO_HOME / "settings" / "mcp.json"

MCP_SERVER_NAME = "sdpm"


def info(msg: str) -> None:
    print(f"  {msg}")


def warn(msg: str) -> None:
    print(f"  WARNING: {msg}", file=sys.stderr)


def cleanup_stale_skill_links(kiro_home: Path = KIRO_HOME) -> None:
    """Remove dangling sdpm skill symlinks left by pre-v0.5 installs.

    v0.5 removed the skills/ directory (mode behavior is now served by the
    MCP server via start_presentation), so symlinks created by older
    installers now dangle after `git pull`.
    """
    skills_dest = kiro_home / "skills"
    if not skills_dest.is_dir():
        return
    for link in skills_dest.glob("sdpm-*"):
        if link.is_symlink() and not link.exists():
            link.unlink()
            info(f"{link} (removed dangling pre-v0.5 skill symlink)")


def _expected_composer_config(checkout: Path) -> dict:
    """The exact object the old installer (v0.5.0–v0.5.2) generated.

    This is the deleted ``sdpm-composer.json.tmpl`` with ``{{CHECKOUT}}``
    resolved — kept here verbatim so cleanup can require FULL equality.
    """
    return {
        "name": "sdpm-composer",
        "description": (
            "sdpm slide composer (dispatched by the sdpm-vibe skill). "
            "Composes assigned slides from approved specs via the sdpm MCP server. "
            "No user interaction."
        ),
        "prompt": f"file://{checkout}/personas/composer.md",
        "mcpServers": {
            "sdpm": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    f"{checkout}/servers/local",
                    "python",
                    "server.py",
                ],
                "timeout": 120000,
            }
        },
        "tools": ["read", "glob", "grep", "@sdpm"],
        "allowedTools": ["read", "glob", "grep", "@sdpm"],
        "useLegacyMcpJson": False,
    }


def _is_generated_composer_config(data: object) -> bool:
    """Return True iff ``data`` is byte-for-byte (as JSON objects) something
    the old installer generated — for ANY checkout location.

    The checkout root is recovered from the ``prompt`` field, then the whole
    object must equal the known generated form for that root (prompt and MCP
    args therefore must point at the SAME root). Any user edit — description,
    timeout, tools, extra fields — breaks equality and the file is kept.

    Old checkouts are deliberately included: ``make install-kiro`` switches
    the global ~/.kiro environment to THIS checkout, and personas prefer a
    registered ``sdpm-composer`` over self-spawn — a leftover pointing at a
    moved/stale checkout would silently win. That is the exact
    boundary-crossing staleness this cleanup exists to remove.
    """
    if not isinstance(data, dict):
        return False
    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        return False
    prefix, suffix = "file://", "/personas/composer.md"
    if not (prompt.startswith(prefix) and prompt.endswith(suffix)):
        return False
    checkout = Path(prompt[len(prefix) : -len(suffix)])
    if not checkout.is_absolute():
        return False
    return data == _expected_composer_config(checkout)


def cleanup_legacy_composer_agent(agents_dest: Path = AGENTS_DEST) -> None:
    """Remove the legacy generated ``sdpm-composer.json`` (v0.5.2 and earlier).

    Composer sub-agents are now self-spawned by the orchestrator via the
    persona's spawn template — no pre-registered agent is needed. Only a
    file exactly matching the known generated form (for whatever checkout
    it was rendered from) is deleted; anything else (user-edited, unknown
    format) is left in place with a warning.
    """
    legacy = agents_dest / "sdpm-composer.json"
    if not legacy.exists():
        return
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        warn(
            f"{legacy} exists but is not readable as JSON — left in place. "
            "It is no longer needed (composers are self-spawned); remove it "
            "manually if you did not customize it."
        )
        return
    if _is_generated_composer_config(data):
        legacy.unlink()
        info(f"{legacy} (removed legacy generated composer agent — composers are now self-spawned)")
    else:
        warn(
            f"{legacy} does not match the known generated form — left in "
            "place (it may be user-edited). It is no longer needed for sdpm "
            "compose; remove it manually when convenient."
        )


def _mcp_server_name_present(config_path: Path) -> bool:
    """Return True if an entry named sdpm exists (regardless of where it points)."""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return MCP_SERVER_NAME in data.get("mcpServers", {})


def _mcp_server_registered(config_path: Path, expected_dir: Path) -> bool:
    """Return True if the sdpm MCP server already points at this checkout.

    Checking the name alone is not enough: a registration left behind by a
    checkout that has since moved or been deleted would be treated as valid,
    so ``make install-kiro`` could not repair it (which is exactly what the
    README tells users to do after moving the checkout).
    """
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    server = data.get("mcpServers", {}).get(MCP_SERVER_NAME)
    if not isinstance(server, dict):
        return False
    return str(expected_dir) in [str(a) for a in server.get("args", [])]


def register_mcp_server(kiro_cli: str | None, agent: str | None) -> None:
    """Register the sdpm MCP server via `kiro-cli mcp add` (idempotent).

    Re-registers with ``--force`` when an entry exists but points elsewhere
    (moved checkout, or switching between multiple checkouts).
    """
    target = f"agent '{agent}'" if agent else "global ~/.kiro/settings/mcp.json"
    print(f"[1/1] Registering MCP server '{MCP_SERVER_NAME}' in {target}")

    config_path = AGENTS_DEST / f"{agent}.json" if agent else GLOBAL_MCP_JSON
    mcp_dir = REPO_ROOT / "servers" / "local"
    if _mcp_server_registered(config_path, mcp_dir):
        info(f"'{MCP_SERVER_NAME}' already registered in {config_path} (skipped)")
        return
    stale = _mcp_server_name_present(config_path)

    if kiro_cli is None:
        warn(
            "kiro-cli not found on PATH — skipped MCP registration. "
            "Install Kiro CLI and re-run `make install-kiro`."
        )
        return

    args = ["run", "--directory", str(mcp_dir), "python", "server.py"]
    cmd = [
        kiro_cli,
        "mcp",
        "add",
        "--name",
        MCP_SERVER_NAME,
        "--command",
        "uv",
        "--args",
        json.dumps(args),
        "--timeout",
        "120000",
    ]
    if stale:
        cmd.append("--force")
    if agent:
        cmd += ["--agent", agent]
    else:
        cmd += ["--scope", "global"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        warn(f"`{' '.join(cmd)}` failed:\n{result.stderr.strip() or result.stdout.strip()}")
        return
    info(f"'{MCP_SERVER_NAME}' {'updated' if stale else 'registered'} in {config_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--agent",
        metavar="NAME",
        help=(
            "register the sdpm MCP server into ~/.kiro/agents/NAME.json instead "
            "of the global ~/.kiro/settings/mcp.json"
        ),
    )
    opts = parser.parse_args()

    print(f"Installing sdpm for Kiro CLI (checkout: {REPO_ROOT})\n")
    kiro_cli = shutil.which("kiro-cli")
    if kiro_cli is None:
        warn("kiro-cli not found on PATH — cleanup will proceed anyway.")

    cleanup_stale_skill_links()
    cleanup_legacy_composer_agent()
    register_mcp_server(kiro_cli, opts.agent)

    print(
        "\nDone. Usage:\n"
        "  1. Make sure `uv` and LibreOffice/poppler are installed (previews need them).\n"
        "  2. Start a NEW session: kiro-cli chat\n"
        '  3. Ask for slides, e.g. "このURLをスライドにして https://..." — the agent calls\n'
        "     start_presentation(mode=...) and self-spawns composer sub-agents.\n"
        "\n"
        "Updates: `git pull` in this checkout is enough. Re-run `make install-kiro`\n"
        "only if you move the checkout."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
