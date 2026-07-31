#!/usr/bin/env python3
"""Install sdpm support for Kiro CLI.

Idempotent installer that wires this repository checkout into Kiro CLI:

1. Renders ``clients/kiro/sdpm-composer.json.tmpl`` (resolving ``{{CHECKOUT}}``
   to this checkout's absolute path) into ``~/.kiro/agents/sdpm-composer.json``
   so the orchestrator can dispatch composer sub-agents via the subagent tool.
2. Registers the ``sdpm`` MCP server in the global ``~/.kiro/settings/mcp.json``
   via ``kiro-cli mcp add`` (skipped if already registered). Use ``--agent NAME``
   to register it into a specific agent config instead.

The repository stays the single source of truth: the composer prompt is a
``file://`` reference into ``personas/``, so ``git pull`` updates take effect
without re-running this script. Re-run only if you move the checkout.

Mode behavior (vibe/spec/style) is served by the MCP server itself via the
``start_presentation(mode=...)`` tool — no skill files are installed.
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
TEMPLATE = HERE / "sdpm-composer.json.tmpl"

KIRO_HOME = Path.home() / ".kiro"
AGENTS_DEST = KIRO_HOME / "agents"
GLOBAL_MCP_JSON = KIRO_HOME / "settings" / "mcp.json"

MCP_SERVER_NAME = "sdpm"


def info(msg: str) -> None:
    print(f"  {msg}")


def warn(msg: str) -> None:
    print(f"  WARNING: {msg}", file=sys.stderr)


def cleanup_stale_skill_links() -> None:
    """Remove dangling sdpm skill symlinks left by pre-v0.5 installs.

    v0.5 removed the skills/ directory (mode behavior is now served by the
    MCP server via start_presentation), so symlinks created by older
    installers now dangle after `git pull`.
    """
    skills_dest = KIRO_HOME / "skills"
    if not skills_dest.is_dir():
        return
    for link in skills_dest.glob("sdpm-*"):
        if link.is_symlink() and not link.exists():
            link.unlink()
            info(f"{link} (removed dangling pre-v0.5 skill symlink)")


def render_composer_agent() -> Path:
    """Render the composer agent config template into ~/.kiro/agents/."""
    print("[1/2] Generating ~/.kiro/agents/sdpm-composer.json")
    rendered = TEMPLATE.read_text(encoding="utf-8").replace(
        "{{CHECKOUT}}", str(REPO_ROOT)
    )
    config = json.loads(rendered)  # validate JSON before writing
    AGENTS_DEST.mkdir(parents=True, exist_ok=True)
    dest = AGENTS_DEST / f"{config['name']}.json"
    if dest.exists() and dest.read_text(encoding="utf-8") == rendered:
        info(f"{dest} (up to date, skipped)")
    else:
        dest.write_text(rendered, encoding="utf-8")
        info(f"{dest} (written)")
    return dest


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
    print(f"[2/2] Registering MCP server '{MCP_SERVER_NAME}' in {target}")

    config_path = AGENTS_DEST / f"{agent}.json" if agent else GLOBAL_MCP_JSON
    mcp_dir = REPO_ROOT / "servers" / "local"
    if _mcp_server_registered(config_path, mcp_dir):
        info(f"'{MCP_SERVER_NAME}' already registered in {config_path} (skipped)")
        return
    stale = _mcp_server_name_present(config_path)

    if kiro_cli is None:
        warn(
            "kiro-cli not found on PATH — skipped MCP registration. "
            "Install Kiro CLI and re-run `make install-kiro` (files above were "
            "still generated)."
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
        warn("kiro-cli not found on PATH — file generation will proceed anyway.")

    cleanup_stale_skill_links()
    render_composer_agent()
    register_mcp_server(kiro_cli, opts.agent)

    print(
        "\nDone. Usage:\n"
        "  1. Make sure `uv` and LibreOffice/poppler are installed (previews need them).\n"
        "  2. Start a NEW session: kiro-cli chat\n"
        '  3. Ask for slides, e.g. "このURLをスライドにして https://..." — the agent calls\n'
        "     start_presentation(mode=...) and dispatches sdpm-composer sub-agents.\n"
        "\n"
        "Updates: `git pull` in this checkout is enough (the composer prompt is a\n"
        "file:// reference into personas/). Re-run `make install-kiro` only if you\n"
        "move the checkout."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
