#!/usr/bin/env python3
"""Install sdpm support for Kiro CLI.

Idempotent installer that wires this repository checkout into Kiro CLI:

1. Symlinks the skills under ``skills/`` (sdpm-vibe, sdpm-spec, ...) into
   ``~/.kiro/skills/`` so Kiro CLI discovers them.
2. Renders ``clients/kiro/sdpm-composer.json.tmpl`` (resolving ``{{CHECKOUT}}``
   to this checkout's absolute path) into ``~/.kiro/agents/sdpm-composer.json``
   so the sdpm-vibe skill can dispatch composer sub-agents via the subagent tool.
3. Registers the ``sdpm`` MCP server in the global ``~/.kiro/settings/mcp.json``
   via ``kiro-cli mcp add`` (skipped if already registered). Use ``--agent NAME``
   to register it into a specific agent config instead.

The repository stays the single source of truth: skills are symlinks and the
composer prompt is a ``file://`` reference, so ``git pull`` updates take effect
without re-running this script. Re-run only if you move the checkout.
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
SKILLS_SRC = REPO_ROOT / "skills"
TEMPLATE = HERE / "sdpm-composer.json.tmpl"

KIRO_HOME = Path.home() / ".kiro"
SKILLS_DEST = KIRO_HOME / "skills"
AGENTS_DEST = KIRO_HOME / "agents"
GLOBAL_MCP_JSON = KIRO_HOME / "settings" / "mcp.json"

MCP_SERVER_NAME = "sdpm"


def info(msg: str) -> None:
    print(f"  {msg}")


def warn(msg: str) -> None:
    print(f"  WARNING: {msg}", file=sys.stderr)


def symlink_skills() -> None:
    """Symlink each skill directory under skills/ into ~/.kiro/skills/."""
    print("[1/3] Linking skills into ~/.kiro/skills/")
    SKILLS_DEST.mkdir(parents=True, exist_ok=True)
    for src in sorted(SKILLS_SRC.iterdir()):
        if not src.is_dir() or not (src / "SKILL.md").is_file():
            continue
        link = SKILLS_DEST / src.name
        if link.is_symlink():
            if link.resolve() == src.resolve():
                info(f"{link} -> {src} (already linked, skipped)")
                continue
            link.unlink()
            link.symlink_to(src)
            info(f"{link} -> {src} (re-pointed stale symlink)")
        elif link.exists():
            warn(
                f"{link} exists and is not a symlink — left untouched. "
                f"Remove it and re-run to link {src}."
            )
        else:
            link.symlink_to(src)
            info(f"{link} -> {src} (linked)")


def render_composer_agent() -> Path:
    """Render the composer agent config template into ~/.kiro/agents/."""
    print("[2/3] Generating ~/.kiro/agents/sdpm-composer.json")
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


def _mcp_server_registered(config_path: Path) -> bool:
    """Return True if the sdpm MCP server is present in the given config file."""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return MCP_SERVER_NAME in data.get("mcpServers", {})


def register_mcp_server(kiro_cli: str | None, agent: str | None) -> None:
    """Register the sdpm MCP server via `kiro-cli mcp add` (idempotent)."""
    target = f"agent '{agent}'" if agent else "global ~/.kiro/settings/mcp.json"
    print(f"[3/3] Registering MCP server '{MCP_SERVER_NAME}' in {target}")

    config_path = AGENTS_DEST / f"{agent}.json" if agent else GLOBAL_MCP_JSON
    if _mcp_server_registered(config_path):
        info(f"'{MCP_SERVER_NAME}' already registered in {config_path} (skipped)")
        return

    if kiro_cli is None:
        warn(
            "kiro-cli not found on PATH — skipped MCP registration. "
            "Install Kiro CLI and re-run `make install-kiro` (files above were "
            "still generated)."
        )
        return

    args = ["run", "--directory", str(REPO_ROOT / "mcp-local"), "python", "server.py"]
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
    if agent:
        cmd += ["--agent", agent]
    else:
        cmd += ["--scope", "global"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        warn(f"`{' '.join(cmd)}` failed:\n{result.stderr.strip() or result.stdout.strip()}")
        return
    info(f"'{MCP_SERVER_NAME}' registered in {config_path}")


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

    symlink_skills()
    render_composer_agent()
    register_mcp_server(kiro_cli, opts.agent)

    print(
        "\nDone. Usage:\n"
        "  1. Make sure `uv` and LibreOffice/poppler are installed (previews need them).\n"
        "  2. Start a NEW session: kiro-cli chat\n"
        '  3. Ask for slides, e.g. "このURLをスライドにして https://..." — the sdpm-vibe\n'
        "     skill runs Phase 1 and dispatches sdpm-composer sub-agents for Phase 2.\n"
        "\n"
        "Updates: `git pull` in this checkout is enough (skills are symlinks; the\n"
        "composer prompt is a file:// reference). Re-run `make install-kiro` only if\n"
        "you move the checkout."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
