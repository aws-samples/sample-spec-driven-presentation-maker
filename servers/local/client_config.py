# SPDX-License-Identifier: MIT-0
"""Wire the local MCP server into the MCP clients installed on this machine.

This is the single implementation behind ``sdpm mcp-config``, ``sdpm register``,
``sdpm unregister``, ``sdpm`` (status) and the end of ``sdpm update`` (``refresh``) on
every OS; the shell and PowerShell launchers only delegate here. It knows about clients,
not about slides, so it lives with the local adapter rather than in ``sdpm.tools``.

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
import re
import shutil
import stat
import subprocess
import sys
import tempfile
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


# Kiro's unit of configuration is the agent (tools, allowed tools, MCP servers), so SDPM is a
# dedicated agent rather than an entry in the global mcp.json that would put 20 tools and an
# approval prompt per run_python into every session. The agent is wiring only: no prompt, no
# file:// pointer — the role documents come from the server (start_* tools).
KIRO_AGENT_MARKER = "(managed by `sdpm register`)"
DEFAULT_KIRO_AGENT = "sdpm"
_KIRO_AGENT_TOOLS = ["@sdpm", "use_subagent", "read", "glob", "grep", "web_search", "web_fetch"]


def _kiro_permission_rules(name: str) -> list[dict]:
    """The V3 form of allowedTools + trustedAgents: the same tools run without approval."""
    return [
        {"capability": "mcp", "match": [f"{SERVER_NAME}/*"], "effect": "allow"},
        {"capability": "subagent", "match": [name], "effect": "allow"},
        {"capability": "fs_read", "effect": "allow"},  # read, glob, grep
        {"capability": "web_search", "effect": "allow"},
        {"capability": "web_fetch", "effect": "allow"},
    ]


def kiro_agent_definition(t: Target, name: str = DEFAULT_KIRO_AGENT) -> dict:
    """One file both Kiro CLI engines load as-is.

    The V2 engine reads ``tools`` / ``allowedTools`` / ``toolsSettings``; the V3 engine
    (kiro-cli 3.x) reads ``tools`` (``subagent/<name>``) and ``permissions`` and ignores
    the V2 fields. V3 rejects — or, with auto-upgrade on, rewrites and backs up — only a
    definition without ``permissions``, so this one is never converted.
    """
    cfg = server_config(t)
    return {
        "name": name,
        "description": (
            "Spec-Driven Presentation Maker — slides from material or dialogue. "
            "Prompts: /sdpm-vibe /sdpm-spec /sdpm-style /sdpm-translate. " + KIRO_AGENT_MARKER
        ),
        "mcpServers": {SERVER_NAME: {**cfg, "timeout": 120000}},
        # @sdpm is trusted: composing a deck is dozens of run_python calls, and run_python
        # is a local sandbox confined to the deck directory. Nothing here writes files or
        # runs shell commands outside that sandbox.
        "tools": [*_KIRO_AGENT_TOOLS, f"subagent/{name}"],
        "allowedTools": list(_KIRO_AGENT_TOOLS),
        # Composers are copies of this agent: spawning it needs no approval, and no other
        # agent (say, a stale one from an old installer) can be picked by mistake.
        "toolsSettings": {"subagent": {"availableAgents": [name], "trustedAgents": [name]}},
        "permissions": {"rules": _kiro_permission_rules(name)},
        "resources": [],
    }


def kiro_agent_path(name: str = DEFAULT_KIRO_AGENT, root: Optional[Path] = None) -> Path:
    return (root or kiro_home()) / "agents" / f"{name}.json"


def _is_our_agent_file(path: Path) -> bool:
    try:
        return KIRO_AGENT_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def write_kiro_agent(t: Target, *, name: str = DEFAULT_KIRO_AGENT, dry_run: bool = False,
                     root: Optional[Path] = None) -> int:
    """Create or refresh the agent file we own. A user's own agent of that name is left alone."""
    path = kiro_agent_path(name, root)
    if path.exists() and not _is_our_agent_file(path):
        print(f"{path} exists and is not managed by sdpm — leaving it alone.")
        print("  Use `sdpm register kiro-cli --agent-name <other>` or add the server to that agent yourself:")
        print("  " + json.dumps(server_config(t)))
        return 0
    text = json.dumps(kiro_agent_definition(t, name), indent=2, ensure_ascii=False) + "\n"
    if dry_run:
        print("[dry-run] write " + str(path))
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if shutil.which("kiro-cli"):
        rc = _run(["kiro-cli", "agent", "validate", "--path", str(path)])
        if rc != 0:
            print(f"  kiro-cli agent validate rejected {path}", file=sys.stderr)
            return 1
    return 0


def _kiro_upgrade_backups(name: str, root: Optional[Path] = None) -> list[Path]:
    """`<name>.json.bak[.N]` copies of our file that kiro-cli 3.x left when it converted the
    pre-V3 definition at launch. Only copies that still carry our marker are ours."""
    path = kiro_agent_path(name, root)
    try:
        candidates = sorted(path.parent.iterdir())
    except OSError:
        return []
    prefix = path.name + ".bak"
    return [p for p in candidates
            if p.is_file() and (p.name == prefix or p.name.startswith(prefix + ".")) and _is_our_agent_file(p)]


def remove_kiro_agent(*, name: str = DEFAULT_KIRO_AGENT, dry_run: bool = False, root: Optional[Path] = None) -> None:
    path = kiro_agent_path(name, root)
    ours = [path] if path.exists() and _is_our_agent_file(path) else []
    for p in ours + _kiro_upgrade_backups(name, root):
        print(("[dry-run] remove " if dry_run else "removed ") + str(p))
        if not dry_run:
            p.unlink()


def kiro_agent_registered(name: str = DEFAULT_KIRO_AGENT, root: Optional[Path] = None) -> bool:
    return _is_our_agent_file(kiro_agent_path(name, root))


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
        label="Kiro CLI",
        detect=lambda: _which("kiro-cli"),
        manual_target="~/.kiro/agents/sdpm.json",
        note="Creates a dedicated agent: start it with `kiro-cli chat --agent sdpm` (or /agent sdpm).",
    ),
    Client(
        id="claude-code",
        label="Claude Code",
        detect=lambda: _which("claude"),
        register=_claude_code_register,
        unregister=lambda: ["claude", "mcp", "remove", "--scope", "user", SERVER_NAME],
        list_cmd=["claude", "mcp", "list"],
        manual_target="~/.claude.json",
        note="Composers run as Claude Code sub-agents (Task), which inherit the server. Approve the sdpm "
             "tools once, or launch with `claude --allowedTools \"mcp__sdpm__*\"`.",
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

    The generated ``agents/sdpm-composer.json`` pointed its prompt at
    ``skills/sdpm-composer/SKILL.md``, which no longer exists, so the agent cannot start —
    yet its name makes an orchestrator pick it. Only that exact fingerprint is reported: a
    user's own agent of the same name (own prompt, own model) is theirs and is left alone.
    """
    root = root or kiro_home()
    found: list[Path] = []
    agent = root / "agents" / "sdpm-composer.json"
    if agent.is_file():
        try:
            text = agent.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if "skills/sdpm-composer/SKILL.md" in text:
            found.append(agent)
    for name in _LEGACY_SKILLS:
        entry = root / "skills" / name
        if entry.is_symlink() or (entry.is_dir() and (entry / "SKILL.md").exists()):
            found.append(entry)
    return found


def kiro_global_entry(root: Optional[Path] = None) -> bool:
    """True when the global mcp.json carries an `sdpm` server (old installer, or our #396 era)."""
    path = (root or kiro_home()) / "settings" / "mcp.json"
    try:
        return SERVER_NAME in json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
    except (OSError, ValueError, AttributeError):
        return False


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
    lines.append("They point at files that no longer exist, so an orchestrator that picks the")
    lines.append("sdpm-composer agent fails. Nothing in SDPM needs them any more.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def manual_json(target: Target) -> str:
    return json.dumps({"mcpServers": {SERVER_NAME: server_config(target)}}, indent=2)


def render_client(client: Client, target: Target, agent_name: str = DEFAULT_KIRO_AGENT) -> str:
    lines = [f"## {client.label}"]
    if client.id == "kiro-cli":
        lines.append(f"`sdpm register kiro-cli` writes this agent to {kiro_agent_path(agent_name)}:")
        lines.extend("  " + ln for ln in json.dumps(kiro_agent_definition(target, agent_name), indent=2).splitlines())
        lines.append(client.note)
        return "\n".join(lines)
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


def config_document(clients: list[Client], target: Target, agent_name: str = DEFAULT_KIRO_AGENT) -> dict:
    return {
        "server": {SERVER_NAME: server_config(target)},
        "clients": [
            {
                "id": c.id,
                "label": c.label,
                "register": c.register(target) if c.register else None,
                "agent": kiro_agent_definition(target, agent_name) if c.id == "kiro-cli" else None,
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


@dataclass
class Outcome:
    client: Client
    status: str          # "registered" | "opened" | "skipped" | "failed" | "manual"
    detail: str


def _pick_hint(client: Client, agent_name: str) -> str:
    return {
        "kiro-cli": f"creates agent `{agent_name}`  →  kiro-cli chat --agent {agent_name}",
        "claude-code": "claude mcp add (user scope)",
        "vscode": "code --add-mcp",
        "codex": "codex mcp add",
        "cursor": "opens an Install link in Cursor",
        "kiro-ide": "not here — paste `sdpm mcp-config kiro-ide` into ~/.kiro/settings/mcp.json",
        "claude-desktop": "not here — double-click sdpm.mcpb from the release page",
    }.get(client.id, "")


def _selectable(client: Client) -> bool:
    return client.id == "kiro-cli" or client.register is not None or client.deeplink is not None


def choose_clients(clients: list[Client], *, agent_name: str, assume_yes: bool, dry_run: bool) -> list[Client]:
    """Checkbox picker over the detected clients; all pre-checked. Non-interactive → all."""
    from picker import Option, pick

    if assume_yes or dry_run:
        return [c for c in clients if _selectable(c)]
    options = [Option(key=c.id, label=c.label, hint=_pick_hint(c, agent_name), checked=True, enabled=_selectable(c))
               for c in clients]
    chosen = pick(options, title="Connect SDPM to your MCP clients")
    if chosen is None:
        return []
    return [c for c in clients if c.id in chosen]


def register(
    clients: list[Client],
    target: Target,
    *,
    dry_run: bool = False,
    assume_yes: bool = False,
    run: Callable[[list[str]], int] = _run,
    open_url: Callable[[str], bool] = webbrowser.open,
    agent_name: str = DEFAULT_KIRO_AGENT,
    chosen: Optional[list[Client]] = None,
    cleanup: bool = True,
) -> int:
    """Pick clients, register with each, print one result table. Returns the number of failures.

    ``cleanup`` offers to remove what older setups left in the client (Kiro installer files,
    the global Kiro entry, the Claude Code plugin); ``refresh`` turns it off.
    """
    if chosen is None:
        chosen = choose_clients(clients, agent_name=agent_name, assume_yes=assume_yes, dry_run=dry_run)
    chosen_ids = {c.id for c in chosen}
    outcomes: list[Outcome] = []
    for client in clients:
        if not _selectable(client):
            outcomes.append(Outcome(client, "manual", _pick_hint(client, agent_name).replace("not here — ", "")))
            continue
        if client.id not in chosen_ids:
            outcomes.append(Outcome(client, "skipped", f"sdpm register {client.id}"))
            continue
        if client.id == "kiro-cli":
            if write_kiro_agent(target, name=agent_name, dry_run=dry_run) == 0:
                outcomes.append(Outcome(client, "registered", f"agent `{agent_name}`  {next_step(client, agent_name)}"))
            else:
                outcomes.append(Outcome(client, "failed", "sdpm mcp-config kiro-cli"))
            if cleanup:
                _offer_leftover_cleanup(dry_run=dry_run, assume_yes=assume_yes, run=run)
            continue
        if client.register is not None:
            argv = client.register(target)
            if dry_run:
                print("[dry-run] " + _shell_join(argv))
                outcomes.append(Outcome(client, "registered", next_step(client, agent_name)))
                continue
            if run(argv) != 0:
                outcomes.append(Outcome(client, "failed", f"add it by hand: sdpm mcp-config {client.id}"))
            else:
                outcomes.append(Outcome(client, "registered", next_step(client, agent_name)))
            if client.id == "claude-code" and cleanup:
                _offer_claude_plugin_cleanup(dry_run=dry_run, assume_yes=assume_yes, run=run)
        elif client.deeplink is not None:
            url = client.deeplink(target)
            if dry_run:
                print("[dry-run] open " + url)
                outcomes.append(Outcome(client, "opened", next_step(client, agent_name)))
            elif open_url(url):
                outcomes.append(Outcome(client, "opened", next_step(client, agent_name)))
            else:
                outcomes.append(Outcome(client, "failed", f"open the link from: sdpm mcp-config {client.id}"))
    print_outcomes(outcomes)
    return sum(1 for o in outcomes if o.status == "failed")


_MARK = {"registered": "\x1b[32m✓\x1b[0m", "opened": "\x1b[32m✓\x1b[0m", "skipped": "–",
         "failed": "\x1b[31m✗\x1b[0m", "manual": " "}
_WORD = {"registered": "registered", "opened": "link opened", "skipped": "skipped", "failed": "failed", "manual": ""}


def print_outcomes(outcomes: list[Outcome]) -> None:
    if not outcomes:
        return
    print()
    width = max(len(o.client.label) for o in outcomes) + 2
    for o in outcomes:
        print(f"  {_MARK[o.status]} {o.client.label:<{width}}{_WORD[o.status]:<12} {o.detail}")
    print()


def next_step(client: Client, agent_name: str = DEFAULT_KIRO_AGENT) -> str:
    if client.id == "kiro-cli":
        return f"→ kiro-cli chat --agent {agent_name}"
    if client.id == "cursor":
        return "→ confirm the Install dialog in Cursor"
    if client.id == "claude-code":
        return "→ approve the sdpm tools once, or: claude --allowedTools \"mcp__sdpm__*\""
    return "→ restart it if running, then ask for slides"


def _print_leftover_warning() -> None:
    leftovers = kiro_leftovers()
    if leftovers:
        print()
        print("  ! " + leftover_notice(leftovers).replace("\n", "\n    "))
        print("    Remove with: sdpm register kiro-cli   (or sdpm unregister kiro-cli)")


CLAUDE_PLUGIN = "sdpm@sdpm"


def claude_plugin_installed() -> bool:
    """The pre-installer Claude Code plugin — its bundled server and skills duplicate ours."""
    try:
        out = subprocess.run(["claude", "plugin", "list"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return CLAUDE_PLUGIN in out.stdout


def _offer_claude_plugin_cleanup(*, dry_run: bool, assume_yes: bool, run: Callable[[list[str]], int] = _run) -> None:
    if not claude_plugin_installed():
        return
    print(f"The Claude Code plugin {CLAUDE_PLUGIN} (pre-installer) is still installed. It bundles its own")
    print("copy of the server and skills, so every sdpm tool would appear twice.")
    argv = ["claude", "plugin", "uninstall", CLAUDE_PLUGIN]
    if dry_run:
        print("[dry-run] " + _shell_join(argv))
    elif assume_yes or _confirm("Uninstall it?"):
        run(argv)


def _offer_leftover_cleanup(*, dry_run: bool, assume_yes: bool, run: Callable[[list[str]], int] = _run) -> None:
    leftovers = kiro_leftovers()
    if leftovers:
        print(leftover_notice(leftovers))
        if dry_run or assume_yes or _confirm("Remove them?"):
            remove_leftovers(leftovers, dry_run=dry_run)
    if kiro_global_entry():
        print(f"The global ~/.kiro/settings/mcp.json has an '{SERVER_NAME}' server. With the sdpm agent it is")
        print("redundant and puts the tools into every session (an old installer wrote it).")
        argv = ["kiro-cli", "mcp", "remove", "--scope", "global", "--name", SERVER_NAME]
        if dry_run:
            print("[dry-run] " + _shell_join(argv))
        elif assume_yes or _confirm("Remove it?"):
            run(argv)


def unregister(clients: list[Client], *, dry_run: bool = False, run: Callable[[list[str]], int] = _run,
               agent_name: str = DEFAULT_KIRO_AGENT) -> int:
    failures = 0
    for client in clients:
        if client.id == "kiro-cli":
            remove_kiro_agent(name=agent_name, dry_run=dry_run)
            leftovers = kiro_leftovers()
            if leftovers:
                remove_leftovers(leftovers, dry_run=dry_run)
            continue
        if client.unregister is None:
            print(f"{client.label}: remove '{SERVER_NAME}' from {client.manual_target}")
            continue
        argv = client.unregister()
        print(("[dry-run] " if dry_run else "") + _shell_join(argv))
        if not dry_run and run(argv) != 0:
            failures += 1
    return failures


def registered(clients: list[Client], agent_name: str = DEFAULT_KIRO_AGENT) -> dict[str, Optional[bool]]:
    """Best effort: True/False when the client CLI can tell us, None otherwise."""
    result: dict[str, Optional[bool]] = {}
    for client in clients:
        if client.id == "kiro-cli":
            result[client.id] = kiro_agent_registered(agent_name)
            continue
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
# After `sdpm update`: bring the rest of the install up to date (refresh)
# ---------------------------------------------------------------------------
#
# Both launchers end `sdpm update` with `client_config.py refresh`, after the pull, so this
# runs the new checkout's code. Launchers from before this step reach it once through
# sdpm._launcher_bridge.

# Present in every launcher this project has shipped (header comment), absent from anything else.
LAUNCHER_FINGERPRINT = "the one launcher for a local SDPM installation"
_UTF8_BOM = b"\xef\xbb\xbf"


def _run_quiet(argv: list[str]) -> int:
    try:
        return subprocess.run(argv, capture_output=True, check=False).returncode
    except OSError:
        return 127


def refresh_launcher(installed: Path, checkout: Path) -> str:
    """Replace the installed ``sdpm`` command with the checkout's launcher; say what happened.

    The new file is written next to the old one and renamed over it. A running bash keeps
    reading the old file (its open inode), so the ``sdpm update`` that calls this is not
    corrupted. Only a launcher we installed is replaced: a link (a developer pointing
    ``sdpm`` at a working tree) or a foreign file is left alone.
    """
    ps1 = installed.suffix.lower() == ".ps1"
    source = checkout / "scripts" / "install" / ("launcher.ps1" if ps1 else "launcher.sh")
    if installed.is_symlink():
        return f"left alone ({installed} is a link)"
    try:
        current = installed.read_bytes()
        new = source.read_bytes()
    except OSError as error:
        return f"not refreshed ({error.strerror or error})"
    if LAUNCHER_FINGERPRINT.encode() not in current:
        return f"left alone ({installed} is not an SDPM launcher)"
    if ps1 and not new.startswith(_UTF8_BOM):
        new = _UTF8_BOM + new  # Windows PowerShell 5.1 reads a file without a BOM as ANSI
    if current == new:
        return "up to date"
    fd, tmp = tempfile.mkstemp(prefix=".sdpm-", dir=str(installed.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(new)
        os.chmod(tmp, stat.S_IMODE(installed.stat().st_mode))
        os.replace(tmp, installed)
    except OSError as error:
        Path(tmp).unlink(missing_ok=True)
        return f"not refreshed ({error.strerror or error}); the next `sdpm update` retries"
    return "updated"


def update_leftovers(checkout: Path, agent_name: str = DEFAULT_KIRO_AGENT, root: Optional[Path] = None) -> list[Path]:
    """What earlier versions left that nothing uses any more. An explicit list, each item
    identified by its contents, so a user's own file of the same name is never matched:

    - ``servers/local/.venv`` and ``sdpm/.venv`` — per-package environments before 0.12
      (now ``<checkout>/.venv``); only directories that are virtual environments
    - the files of the old Kiro installer (:func:`kiro_leftovers`)
    - ``<agent>.json.bak[.N]`` copies kiro-cli 3.x made of our pre-V3 agent file
    """
    venvs = [checkout / "servers" / "local" / ".venv", checkout / "sdpm" / ".venv"]
    found = [p for p in venvs if p.is_dir() and not p.is_symlink() and (p / "pyvenv.cfg").is_file()]
    return found + kiro_leftovers(root) + _kiro_upgrade_backups(agent_name, root)


def refresh_registrations(
    target: Target,
    *,
    agent_name: str = DEFAULT_KIRO_AGENT,
    clients: Optional[list[Client]] = None,
    run: Callable[[list[str]], int] = _run,
    run_quiet: Callable[[list[str]], int] = _run_quiet,
) -> tuple[int, list[Client]]:
    """Register again every client that already has the server; add none.

    Returns the number of failures and the detected clients that do not have it (for one
    "add with sdpm register" line). The Kiro agent file is the registration itself, so it is
    refreshed even when kiro-cli is not on PATH. A client whose CLI can remove the server is
    cleared first: ``claude mcp add`` refuses a name that exists.
    """
    clients = detect() if clients is None else list(clients)
    if not any(c.id == "kiro-cli" for c in clients) and kiro_agent_registered(agent_name):
        clients.insert(0, by_id("kiro-cli"))
    status = registered(clients, agent_name)
    ours = [c for c in clients if status.get(c.id) is True]
    missing = [c for c in clients if status.get(c.id) is False and _selectable(c)]
    if not ours:
        return 0, missing
    for client in ours:
        if client.unregister is not None:
            run_quiet(client.unregister())
    failures = register(ours, target, run=run, agent_name=agent_name, chosen=ours, cleanup=False)
    return failures, missing


# Upgrading notes. In CHANGELOG.md, the bullets that follow a paragraph
# `**Local installs (`sdpm update`).**` inside an Upgrading section are written for people
# who run `sdpm update`, each as what to do. refresh prints those the previous checkout's
# CHANGELOG did not contain yet, so a release's notes are shown once, whichever version the
# install came from.
_LOCAL_NOTES = re.compile(r"^\*\*Local installs\b.*\*\*\s*$")
_REVISION = re.compile(r"^[0-9a-fA-F]{7,64}$")


def local_install_notes(changelog: str) -> list[tuple[str, str]]:
    """``(version, bullet)`` for every bullet of a Local installs block, bullets on one line."""
    notes: list[tuple[str, str]] = []
    version, inside, bullet = "", False, None

    def flush() -> None:
        nonlocal bullet
        if bullet:
            notes.append((version, " ".join(bullet)))
        bullet = None

    for line in changelog.splitlines():
        if line.startswith("#"):
            flush()
            inside = False
            if line.startswith("## "):
                heading = line[3:].strip()
                version = heading[1:heading.index("]")] if heading.startswith("[") and "]" in heading else heading
        elif _LOCAL_NOTES.match(line):
            flush()
            inside = True
        elif not inside:
            continue
        elif line.startswith("- "):
            flush()
            bullet = [line[2:].strip()]
        elif line.startswith("  ") and line.strip() and bullet is not None:
            bullet.append(line.strip())
        elif not line.strip():
            flush()
        else:
            flush()
            inside = False
    flush()
    return notes


def upgrade_notes(checkout: Path, since: Optional[str]) -> list[tuple[str, str]]:
    """Local installs notes that are new since revision ``since`` of the checkout."""
    if not since or not _REVISION.match(since):
        return []
    try:
        new = (checkout / "CHANGELOG.md").read_text(encoding="utf-8")
        old = subprocess.run(["git", "-C", str(checkout), "show", f"{since}:CHANGELOG.md"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    except OSError:
        return []
    if old.returncode != 0:
        return []
    seen = " ".join(old.stdout.split())
    return [(v, text) for v, text in local_install_notes(new) if " ".join(text.split()) not in seen]


def print_upgrade_notes(notes: list[tuple[str, str]], checkout: Path) -> None:
    if not notes:
        return
    import textwrap

    print()
    print("  What to do after this update:")
    shown = None
    for version, text in notes:
        if version != shown:
            print(f"    {version}")
            shown = version
        print(textwrap.fill(text.replace("**", ""), width=92, initial_indent="    - ", subsequent_indent="      "))
    print(f"    All changes: {Path(checkout) / 'CHANGELOG.md'}")


def refresh(
    target: Target,
    *,
    launcher: Optional[Path],
    since: Optional[str],
    agent_name: str = DEFAULT_KIRO_AGENT,
    run: Callable[[list[str]], int] = _run,
    run_quiet: Callable[[list[str]], int] = _run_quiet,
    clients: Optional[list[Client]] = None,
) -> int:
    """The end of ``sdpm update``: launcher, registered clients, leftovers, upgrading notes."""
    checkout = Path(target.checkout)
    if launcher is not None:
        print(f"  sdpm command: {refresh_launcher(launcher, checkout)}")
    failures, missing = refresh_registrations(target, agent_name=agent_name, clients=clients,
                                              run=run, run_quiet=run_quiet)
    if missing:
        print(f"  Also found {', '.join(c.label for c in missing)} — add with: "
              f"sdpm register {' '.join(c.id for c in missing)}")
    remove_leftovers(update_leftovers(checkout, agent_name))
    print_upgrade_notes(upgrade_notes(checkout, since), checkout)
    return 1 if failures else 0


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
    parser.add_argument("--agent-name", default=None,
                        help="name of the Kiro CLI agent (default: SDPM_AGENT_NAME or sdpm)")
    sub = parser.add_subparsers(dest="command", required=True)

    def agent_name_option(sp: argparse.ArgumentParser) -> None:
        # Accepted after the subcommand too (`sdpm register kiro-cli --agent-name x`);
        # SUPPRESS keeps a value given before the subcommand from being reset.
        sp.add_argument("--agent-name", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    p = sub.add_parser("print", help="show configuration for detected (or named) clients")
    p.add_argument("clients", nargs="*", choices=[*CLIENT_IDS, []])
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true", help="every supported client, detected or not")
    agent_name_option(p)

    p = sub.add_parser("register", help="register with detected (or named) clients")
    p.add_argument("clients", nargs="*", choices=[*CLIENT_IDS, []])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", "-y", action="store_true", help="do not ask per client")
    agent_name_option(p)

    p = sub.add_parser("unregister", help="remove the server from detected (or named) clients")
    p.add_argument("clients", nargs="*", choices=[*CLIENT_IDS, []])
    p.add_argument("--dry-run", action="store_true")
    agent_name_option(p)

    p = sub.add_parser("status", help="which detected clients have the server registered")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("refresh", help="end of `sdpm update`: launcher, registered clients, leftovers, notes")
    p.add_argument("--launcher", help="the installed sdpm command to replace with the checkout's launcher")
    p.add_argument("--since", help="commit the update started from (selects the upgrading notes)")
    agent_name_option(p)

    args = parser.parse_args(argv)
    if not getattr(args, "agent_name", None):
        args.agent_name = os.environ.get("SDPM_AGENT_NAME") or DEFAULT_KIRO_AGENT
    target = _default_target(args)

    if args.command == "print":
        clients = list(CLIENTS) if args.all else detect(args.clients or None)
        if args.json:
            print(json.dumps(config_document(clients, target, args.agent_name), indent=2))
        else:
            if not clients:
                print("No supported MCP client detected. Generic configuration:")
                print(manual_json(target))
            for c in clients:
                print(render_client(c, target, args.agent_name))
                print()
        return 0

    if args.command == "register":
        clients = detect(args.clients or None)
        if not clients:
            print("No supported MCP client detected. Add this to your client's MCP configuration:")
            print(manual_json(target))
            return 0
        # Named clients on the command line are the selection; no picker.
        chosen = clients if args.clients else None
        return 1 if register(clients, target, dry_run=args.dry_run, assume_yes=args.yes,
                             agent_name=args.agent_name, chosen=chosen) else 0

    if args.command == "unregister":
        return 1 if unregister(detect(args.clients or None), dry_run=args.dry_run, agent_name=args.agent_name) else 0

    if args.command == "refresh":
        return refresh(target, launcher=Path(args.launcher).absolute() if args.launcher else None,
                       since=args.since, agent_name=args.agent_name)

    if args.command == "status":
        clients = detect()
        rows = [{"id": c.id, "label": c.label, "registered": r}
                for c, r in zip(clients, registered(clients, args.agent_name).values())]
        if args.json:
            print(json.dumps({"checkout": target.checkout, "uv": target.uv, "clients": rows}, indent=2))
        elif not rows:
            print("  No MCP client detected on this machine.")
            _print_leftover_warning()
        else:
            print("  MCP clients:")
            for row in rows:
                mark = {
                    True: "registered" + (f"   → kiro-cli chat --agent {args.agent_name}" if row["id"] == "kiro-cli" else ""),
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
