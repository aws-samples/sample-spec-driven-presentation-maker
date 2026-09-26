# SPDX-License-Identifier: MIT-0
"""Wire the local MCP server into the MCP clients installed on this machine.

This is the single implementation behind ``sdpm mcp-config``, ``sdpm register``,
``sdpm unregister`` and ``sdpm`` (status) on every OS; the shell and PowerShell
launchers only delegate here. It knows about clients, not about slides, so it
lives with the local adapter rather than in ``sdpm.tools``.

Every generated configuration points at the **absolute path of uv and of the
checkout** — never at a launcher script, never at anything on ``PATH``. GUI
clients started from the Dock / Start Menu do not inherit a shell ``PATH``, and a
``.cmd`` hop on Windows cannot be spawned by every client; pointing at the real
executable removes both problems and keeps the server's stdio clean.

Registration goes through each client's own CLI where one exists. Clients
without a CLI get the exact JSON and the file it belongs in (and a deep link
where the client offers one); this tool never edits another application's
configuration files.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Optional

SERVER_NAME = "sdpm"

# ---------------------------------------------------------------------------
# The one template
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """Where the server lives on this machine, as absolute paths."""

    uv: str
    checkout: str
    platform: str = sys.platform  # "win32" renders backslashes

    def _join(self, *parts: str) -> str:
        cls = PureWindowsPath if self.platform == "win32" else PurePosixPath
        return str(cls(self.checkout, *parts))

    @property
    def server_dir(self) -> str:
        return self._join("servers", "local")


def server_config(target: Target) -> dict:
    """The stdio server definition every client receives (R3.1)."""
    return {
        "command": target.uv,
        "args": ["run", "--directory", target.server_dir, "python", "server.py"],
    }


def server_argv(target: Target) -> list[str]:
    cfg = server_config(target)
    return [cfg["command"], *cfg["args"]]


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


def _home() -> Path:
    return Path.home()


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def _dir_exists(*parts: str) -> Callable[[], bool]:
    return lambda: _home().joinpath(*parts).is_dir()


def _claude_desktop_dir() -> Callable[[], bool]:
    def probe() -> bool:
        if sys.platform == "darwin":
            return (_home() / "Library" / "Application Support" / "Claude").is_dir()
        if sys.platform == "win32":
            return (Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming")) / "Claude").is_dir()
        return (_home() / ".config" / "Claude").is_dir()

    return probe


@dataclass(frozen=True)
class Client:
    id: str
    label: str
    detect: Callable[[], bool]
    # argv that registers the server; None => manual (print JSON + target file)
    register: Optional[Callable[[Target], list[str]]] = None
    unregister: Optional[Callable[[], list[str]]] = None
    list_cmd: Optional[list[str]] = None  # output containing SERVER_NAME => registered
    manual_target: Optional[str] = None
    deeplink: Optional[Callable[[Target], str]] = None
    note: str = ""


def _kiro_cli_register(t: Target) -> list[str]:
    # --scope global: without it kiro-cli writes the *workspace* config of the cwd.
    return [
        "kiro-cli", "mcp", "add", "--force", "--scope", "global",
        "--name", SERVER_NAME,
        "--command", t.uv,
        "--args", json.dumps(server_config(t)["args"]),
    ]


def _claude_code_register(t: Target) -> list[str]:
    return ["claude", "mcp", "add", "--scope", "user", SERVER_NAME, "--", *server_argv(t)]


def _vscode_register(t: Target) -> list[str]:
    return ["code", "--add-mcp", json.dumps({"name": SERVER_NAME, **server_config(t)})]


def _codex_register(t: Target) -> list[str]:
    return ["codex", "mcp", "add", SERVER_NAME, "--", *server_argv(t)]


def _cursor_deeplink(t: Target) -> str:
    payload = base64.b64encode(json.dumps(server_config(t)).encode()).decode()
    return f"cursor://anysphere.cursor-deeplink/mcp/install?name={SERVER_NAME}&config={payload}"


CLIENTS: tuple[Client, ...] = (
    Client(
        id="kiro-cli",
        label="Kiro CLI (and Kiro IDE — they share ~/.kiro/settings/mcp.json)",
        detect=lambda: _which("kiro-cli"),
        register=_kiro_cli_register,
        unregister=lambda: ["kiro-cli", "mcp", "remove", "--scope", "global", "--name", SERVER_NAME],
        list_cmd=["kiro-cli", "mcp", "list"],
        manual_target="~/.kiro/settings/mcp.json",
    ),
    Client(
        id="claude-code",
        label="Claude Code",
        detect=lambda: _which("claude"),
        register=_claude_code_register,
        unregister=lambda: ["claude", "mcp", "remove", "--scope", "user", SERVER_NAME],
        list_cmd=["claude", "mcp", "list"],
        manual_target="~/.claude.json",
    ),
    Client(
        id="vscode",
        label="Visual Studio Code",
        detect=lambda: _which("code"),
        register=_vscode_register,
        manual_target="~/.config/Code/User/mcp.json (VS Code: Command Palette › MCP: Open User Configuration)",
        note="VS Code has no CLI to remove a server; use the MCP view.",
    ),
    Client(
        id="codex",
        label="Codex",
        detect=lambda: _which("codex"),
        register=_codex_register,
        unregister=lambda: ["codex", "mcp", "remove", SERVER_NAME],
        list_cmd=["codex", "mcp", "list"],
        manual_target="~/.codex/config.toml",
    ),
    Client(
        id="cursor",
        label="Cursor",
        detect=_dir_exists(".cursor"),
        manual_target="~/.cursor/mcp.json",
        deeplink=_cursor_deeplink,
        note="Cursor installs from a deep link: opening it shows an Install button.",
    ),
    Client(
        id="kiro-ide",
        label="Kiro IDE",
        detect=lambda: _dir_exists(".kiro")() and not _which("kiro-cli"),
        manual_target="~/.kiro/settings/mcp.json",
        note="Installing Kiro CLI lets `sdpm register` do this for you.",
    ),
    Client(
        id="claude-desktop",
        label="Claude Desktop",
        detect=_claude_desktop_dir(),
        manual_target="Settings › Extensions",
        note="Use the sdpm.mcpb from the GitHub release page (double-click to install) — "
             "Claude Desktop does not spawn uv reliably.",
    ),
)

CLIENT_IDS = tuple(c.id for c in CLIENTS)


def by_id(client_id: str) -> Client:
    for c in CLIENTS:
        if c.id == client_id:
            return c
    raise KeyError(client_id)


def detect(candidates: Optional[list[str]] = None) -> list[Client]:
    pool = [by_id(i) for i in candidates] if candidates else list(CLIENTS)
    return [c for c in pool if candidates or c.detect()]


# ---------------------------------------------------------------------------
# Leftovers of the previous Kiro installer (make install-kiro, removed in v0.10)
# ---------------------------------------------------------------------------

_LEGACY_SKILLS = ("sdpm-create", "sdpm-composer", "sdpm-style", "sdpm-translate")


def kiro_home() -> Path:
    env = os.environ.get("KIRO_HOME")
    return Path(env).expanduser() if env else _home() / ".kiro"


def kiro_leftovers(root: Optional[Path] = None) -> list[Path]:
    """Files the old installer wrote that now break sub-agent dispatch.

    ``agents/sdpm-composer.json`` points its prompt at ``skills/sdpm-composer/SKILL.md``,
    which no longer exists, and its MCP entry at a checkout that may be gone — yet its name
    makes an orchestrator pick it over a working general-purpose sub-agent. Only entries
    that are recognisably ours are reported.
    """
    root = root or kiro_home()
    found: list[Path] = []
    agent = root / "agents" / "sdpm-composer.json"
    if agent.is_file():
        try:
            text = agent.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if "sdpm" in text:
            found.append(agent)
    for name in _LEGACY_SKILLS:
        entry = root / "skills" / name
        if entry.is_symlink() or (entry.is_dir() and (entry / "SKILL.md").exists()):
            found.append(entry)
    return found


def remove_leftovers(paths: list[Path], *, dry_run: bool = False) -> None:
    for path in paths:
        print(("[dry-run] remove " if dry_run else "removed ") + str(path))
        if dry_run:
            continue
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path, ignore_errors=True)


def leftover_notice(paths: list[Path]) -> str:
    lines = ["Found files from the previous Kiro installer (make install-kiro):"]
    lines += [f"  {p}" for p in paths]
    lines.append("They point at files that no longer exist and make an orchestrator pick a broken")
    lines.append("sub-agent named sdpm-composer. Nothing in SDPM needs them any more.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def manual_json(target: Target) -> str:
    return json.dumps({"mcpServers": {SERVER_NAME: server_config(target)}}, indent=2)


def render_client(client: Client, target: Target) -> str:
    lines = [f"## {client.label}"]
    if client.register is not None:
        lines.append("Run:")
        lines.append("  " + _shell_join(client.register(target)))
        lines.append("or `sdpm register " + client.id + "`.")
    if client.deeplink is not None:
        lines.append("Open this link (or `sdpm register " + client.id + "` opens it for you):")
        lines.append("  " + client.deeplink(target))
    if client.manual_target and client.register is None:
        lines.append(f"Add to {client.manual_target}:")
        lines.extend("  " + ln for ln in manual_json(target).splitlines())
    if client.note:
        lines.append(client.note)
    return "\n".join(lines)


def _shell_join(argv: list[str]) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    import shlex

    return shlex.join(argv)


def config_document(clients: list[Client], target: Target) -> dict:
    return {
        "server": {SERVER_NAME: server_config(target)},
        "clients": [
            {
                "id": c.id,
                "label": c.label,
                "register": c.register(target) if c.register else None,
                "unregister": c.unregister() if c.unregister else None,
                "manual_target": c.manual_target,
                "deeplink": c.deeplink(target) if c.deeplink else None,
            }
            for c in clients
        ],
    }


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _confirm(question: str) -> bool:
    """Ask on the terminal. Under `curl … | bash` stdin is the script, so prefer /dev/tty."""
    prompt = f"{question} [y/N] "
    try:
        if sys.platform != "win32" and os.path.exists("/dev/tty"):
            with open("/dev/tty", "r+", encoding="utf-8", errors="replace") as tty:
                tty.write(prompt)
                tty.flush()
                return tty.readline().strip().lower() in {"y", "yes"}
        return input(prompt).strip().lower() in {"y", "yes"}
    except (EOFError, OSError):
        return False


def _run(argv: list[str]) -> int:
    """Run a client CLI; a missing executable is a failure, not a traceback."""
    try:
        return subprocess.run(argv, check=False).returncode
    except OSError as error:
        print(f"  {argv[0]}: {error.strerror or error}", file=sys.stderr)
        return 127


def register(
    clients: list[Client],
    target: Target,
    *,
    dry_run: bool = False,
    assume_yes: bool = False,
    run: Callable[[list[str]], int] = _run,
    open_url: Callable[[str], bool] = webbrowser.open,
) -> int:
    """Register with each client; returns the number of failures."""
    failures = 0
    for client in clients:
        if client.register is None and client.deeplink is None:
            print(render_client(client, target))
            print()
            continue
        if not assume_yes and not dry_run and not _confirm(f"Register SDPM with {client.label}?"):
            continue
        if client.register is not None:
            argv = client.register(target)
            print(("[dry-run] " if dry_run else "") + _shell_join(argv))
            if not dry_run and run(argv) != 0:
                failures += 1
                print(f"  failed — you can add it manually:\n{render_client(client, target)}", file=sys.stderr)
            if client.id == "kiro-cli":
                _offer_leftover_cleanup(dry_run=dry_run, assume_yes=assume_yes)
        elif client.deeplink is not None:
            url = client.deeplink(target)
            print(("[dry-run] open " if dry_run else "Opening ") + url)
            if not dry_run and not open_url(url):
                print(render_client(client, target))
    return failures


def _print_leftover_warning() -> None:
    leftovers = kiro_leftovers()
    if leftovers:
        print()
        print("  ! " + leftover_notice(leftovers).replace("\n", "\n    "))
        print("    Remove with: sdpm register kiro-cli   (or sdpm unregister kiro-cli)")


def _offer_leftover_cleanup(*, dry_run: bool, assume_yes: bool) -> None:
    leftovers = kiro_leftovers()
    if not leftovers:
        return
    print(leftover_notice(leftovers))
    if dry_run or assume_yes or _confirm("Remove them?"):
        remove_leftovers(leftovers, dry_run=dry_run)


def unregister(clients: list[Client], *, dry_run: bool = False, run: Callable[[list[str]], int] = _run) -> int:
    failures = 0
    for client in clients:
        if client.id == "kiro-cli":
            leftovers = kiro_leftovers()
            if leftovers:
                remove_leftovers(leftovers, dry_run=dry_run)
        if client.unregister is None:
            print(f"{client.label}: remove '{SERVER_NAME}' from {client.manual_target}")
            continue
        argv = client.unregister()
        print(("[dry-run] " if dry_run else "") + _shell_join(argv))
        if not dry_run and run(argv) != 0:
            failures += 1
    return failures


def registered(clients: list[Client]) -> dict[str, Optional[bool]]:
    """Best effort: True/False when the client CLI can tell us, None otherwise."""
    result: dict[str, Optional[bool]] = {}
    for client in clients:
        if client.list_cmd is None:
            result[client.id] = None
            continue
        try:
            out = subprocess.run(client.list_cmd, capture_output=True, text=True, timeout=20, check=False)
            result[client.id] = SERVER_NAME in (out.stdout + out.stderr)
        except (OSError, subprocess.TimeoutExpired):
            result[client.id] = None
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_target(args: argparse.Namespace) -> Target:
    checkout = Path(args.checkout).absolute() if args.checkout else Path(__file__).absolute().parents[2]
    uv = args.uv or os.environ.get("SDPM_UV") or shutil.which("uv")
    if not uv:
        sys.exit("uv not found. Pass --uv <path> or set SDPM_UV.")
    # Absolute, but symlinks untouched: /opt/homebrew/bin/uv survives `brew upgrade uv`,
    # the Cellar path behind it does not.
    return Target(uv=str(Path(uv).absolute()), checkout=str(checkout))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="sdpm mcp-config", description=__doc__.split("\n\n")[0])
    parser.add_argument("--uv", help="absolute path of uv (default: SDPM_UV, then PATH)")
    parser.add_argument("--checkout", help="checkout root (default: this file's repository)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("print", help="show configuration for detected (or named) clients")
    p.add_argument("clients", nargs="*", choices=[*CLIENT_IDS, []])
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true", help="every supported client, detected or not")

    p = sub.add_parser("register", help="register with detected (or named) clients")
    p.add_argument("clients", nargs="*", choices=[*CLIENT_IDS, []])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", "-y", action="store_true", help="do not ask per client")

    p = sub.add_parser("unregister", help="remove the server from detected (or named) clients")
    p.add_argument("clients", nargs="*", choices=[*CLIENT_IDS, []])
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("status", help="which detected clients have the server registered")
    p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    target = _default_target(args)

    if args.command == "print":
        clients = list(CLIENTS) if args.all else detect(args.clients or None)
        if args.json:
            print(json.dumps(config_document(clients, target), indent=2))
        else:
            if not clients:
                print("No supported MCP client detected. Generic configuration:")
                print(manual_json(target))
            for c in clients:
                print(render_client(c, target))
                print()
        return 0

    if args.command == "register":
        clients = detect(args.clients or None)
        if not clients:
            print("No supported MCP client detected. Add this to your client's MCP configuration:")
            print(manual_json(target))
            return 0
        return 1 if register(clients, target, dry_run=args.dry_run, assume_yes=args.yes) else 0

    if args.command == "unregister":
        return 1 if unregister(detect(args.clients or None), dry_run=args.dry_run) else 0

    if args.command == "status":
        clients = detect()
        rows = [{"id": c.id, "label": c.label, "registered": r}
                for c, r in zip(clients, registered(clients).values())]
        if args.json:
            print(json.dumps({"checkout": target.checkout, "uv": target.uv, "clients": rows}, indent=2))
        elif not rows:
            print("  No MCP client detected on this machine.")
            _print_leftover_warning()
        else:
            print("  MCP clients:")
            for row in rows:
                mark = {
                    True: "registered",
                    False: f"not registered   → sdpm register {row['id']}",
                    None: f"see: sdpm mcp-config {row['id']}",
                }[row["registered"]]
                label = row["label"].split(" (")[0]
                print(f"    {label:<22} {mark}")
            _print_leftover_warning()
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
