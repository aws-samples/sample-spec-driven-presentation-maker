# SPDX-License-Identifier: MIT-0
"""Every ``sdpm`` subcommand except ``update`` (status, webui, mcp, register, doctor, …).

The installed ``sdpm`` command is a bootstrap (``scripts/install/launcher.sh`` /
``launcher.ps1``) that hands everything to this file, so the commands are written once for
every OS and change with the checkout, never with the launcher. ``sdpm update`` goes to
``checkout_update.py`` instead. Standard library only (it runs before any environment is
synced): ``uv run --no-project --isolated --python ">=3.11" python sdpm_command.py``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checkout_update as cu  # noqa: E402

DEFAULT_PORT = 3000

HELP_TEXT = """Usage: sdpm [COMMAND]

Surfaces
  webui                 Start the browser Web UI and open it
  open DECK             Open a deck (its folder or name) in the Web UI, starting it if needed
  mcp                   Run the MCP server on stdio (terminal check)

MCP clients
  register [CLIENT..]   Register the server with detected (or named) clients
  unregister [CLIENT..] Remove it again
  mcp-config [CLIENT..] Print the configuration with this machine's paths (--json, --all)

Maintenance
  update [--with-webui] [--channel release|main]
                        Move to the latest release (or main), sync, rebuild what is
                        installed, refresh this command and the registered MCP clients
  doctor                Check the local environment
  uninstall             Remove SDPM from this machine
  version | path | help

No command: show status."""


class Context:
    def __init__(self, checkout: str, uv: str, launcher: str) -> None:
        self.checkout = Path(checkout)
        self.home = self.checkout.parent
        self.uv = uv
        self.launcher = Path(launcher) if launcher else None
        self.state = cu.load_state(self.home)

    @property
    def server_dir(self) -> Path:
        return self.checkout / "servers" / "local"

    @property
    def agent_name(self) -> str:
        """A valid SDPM_AGENT_NAME (per call), else the recorded name, else sdpm."""
        env = os.environ.get("SDPM_AGENT_NAME")
        if env and cu.valid_agent_name(env):
            return env
        if env:
            cu.warn(f"(SDPM_AGENT_NAME {env!r} is not a valid name; using {self.state['agent_name']})")
        return self.state["agent_name"]

    def client_config(self, *args: str) -> list[str]:
        return [self.uv, "run", "--frozen", "--directory", str(self.server_dir), "python",
                str(self.server_dir / "client_config.py"), "--uv", self.uv, "--checkout", str(self.checkout),
                "--agent-name", self.agent_name, *args]


def _call(argv: list[str], **kwargs) -> int:
    try:
        return subprocess.call(argv, **kwargs)  # nosec B603 - fixed argv
    except OSError as error:
        cu.warn(f"Could not run {argv[0]}: {error.strerror or error}")
        return 127
    except KeyboardInterrupt:
        return 130


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def version(ctx: Context) -> str:
    ref = cu._git(str(ctx.checkout), "describe", "--tags", "--always").stdout.strip() or "main"
    commit = cu._git(str(ctx.checkout), "rev-parse", "--short", "HEAD").stdout.strip()
    return f"{ref} ({commit})"


def _has_webui(profile: str, checkout: Path) -> bool:
    return profile == "full" and (checkout / "web-ui" / "build").is_dir()


def webui_installed_at(checkout: Path) -> bool:
    """The full profile (state.json next to the checkout; none means full) with a built Web UI.

    For the MCP server's hint: reads state.json on every call and prints nothing.
    """
    return _has_webui(cu.load_state(checkout.parent, warnings=False)["profile"], checkout)


def webui_installed(ctx: Context) -> bool:
    return _has_webui(ctx.state["profile"], ctx.checkout)


def status(ctx: Context) -> int:
    print(f"SDPM {version(ctx)} · {ctx.state['channel']} channel")
    print(f"  checkout   {ctx.checkout}")
    print(f"  profile    {ctx.state['profile']}")
    if webui_installed(ctx):
        print("  webui      installed        → sdpm webui")
    else:
        print("  webui      not installed    → sdpm update --with-webui")
    print("  mcp        installed        → sdpm register  (connect your MCP clients)")
    print(flush=True)
    _call(ctx.client_config("status"), stderr=subprocess.DEVNULL, env=cu.child_env())
    return 0


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


def clients_command(ctx: Context, command: str, rest: list[str]) -> int:
    """register / unregister through client_config.py; the ids it reports go to state.json."""
    if command not in ("register", "unregister"):
        return _call(ctx.client_config(command, *rest), env=cu.child_env())
    fd, record = tempfile.mkstemp(prefix="sdpm-clients-", suffix=".json")
    os.close(fd)
    try:
        rc = _call(ctx.client_config(command, *rest, "--record", record), env=cu.child_env())
        if cu.same_path(ctx.checkout, ctx.home / "checkout"):
            try:
                cu.record_clients(ctx.home, Path(record))
            except OSError as error:
                cu.warn(f"could not record the install state ({error.strerror or error})")
    finally:
        try:
            os.unlink(record)
        except OSError:
            pass
    return rc


# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------


def webui_port() -> int:
    value = os.environ.get("SDPM_WEBUI_PORT", str(DEFAULT_PORT))
    try:
        port = int(value)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise cu.Stop(2, f"SDPM_WEBUI_PORT must be a port number from 1 to 65535, not {value!r}.")
    return port


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def is_sdpm(port: int) -> bool:
    """The Local Web UI answers GET /api/agent/engine with its engine setting."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/agent/engine", timeout=3) as response:  # nosec B310
            data = json.loads(response.read(4096).decode("utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and "engine" in data


def open_url(url: str) -> None:
    try:
        opened = webbrowser.open(url)
    except webbrowser.Error:
        opened = False
    if not opened:
        print(f"Open {url} in your browser.", flush=True)


def _wait_and_open(port: int, stop: threading.Event, path: str = "") -> None:
    deadline = time.monotonic() + 120
    while not stop.is_set() and time.monotonic() < deadline:
        if port_is_open(port):
            if not stop.is_set():
                open_url(f"http://localhost:{port}{path}")
            return
        stop.wait(0.5)
    if not stop.is_set():
        cu.warn(f"SDPM did not become ready on port {port} within 120 seconds.")


def webui(ctx: Context, path: str = "") -> int:
    """Open the Web UI at ``path`` (``/decks/#<id>`` for ``sdpm open``), starting it if needed."""
    if not webui_installed(ctx):
        cu.warn(f"The browser Web UI is not installed in this profile ({ctx.state['profile']}).")
        cu.warn("Add it with:  sdpm update --with-webui   (needs Node.js 20+)")
        return 1
    port = webui_port()
    if port_is_open(port):
        if is_sdpm(port):
            print(f"SDPM is already running on port {port}; opening it.", flush=True)
            open_url(f"http://localhost:{port}{path}")
            return 0
        cu.warn(f"Port {port} is used by another program. Choose another port with SDPM_WEBUI_PORT "
                f"(for example SDPM_WEBUI_PORT={port + 1 if port < 65535 else 3001} sdpm webui).")
        return 1
    npm = shutil.which("npm")
    if npm is None:
        cu.warn("Node.js 20+ is required for the Web UI: https://nodejs.org/")
        return 1
    stop = threading.Event()
    # A daemon thread: it never outlives this process, so a failed start opens nothing.
    threading.Thread(target=_wait_and_open, args=(port, stop, path), daemon=True).start()
    # Loopback only; the Local API routes also refuse a non-loopback Host (web-ui/src/proxy.ts).
    rc = _call([npm, "run", "start", "--", "--hostname", "127.0.0.1", "--port", str(port)],
               cwd=str(ctx.checkout / "web-ui"), env=cu.child_env({"NEXT_PUBLIC_MODE": "local"}))
    stop.set()
    return rc


# A deck id as the Web UI accepts it (web-ui/src/lib/local/deck-paths.ts resolveDeckDir).
DECK_ID = re.compile(r"^[A-Za-z0-9._-]+$")
OPEN_USAGE = "usage: sdpm open DECK   (a deck folder, or its name in the deck root)"


def _valid_deck_id(name: str) -> bool:
    return bool(DECK_ID.match(name)) and not name.startswith(".")


def _user_config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "sdpm"


def deck_root() -> Path:
    """The Web UI's deck root, in its order (web-ui/src/lib/local/deck-paths.ts resolveDeckRoot,
    the same as sdpm.api._get_output_base_dir off WSL): SDPM_DECK_ROOT → SDPM_OUTPUT_DIR →
    ``output_dir`` in config.json (``~`` expanded) → ~/Documents/SDPM-Presentations."""
    for name in ("SDPM_DECK_ROOT", "SDPM_OUTPUT_DIR"):
        value = os.environ.get(name)
        if value:
            return Path(value)
    try:
        config = json.loads((_user_config_dir() / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = None
    configured = config.get("output_dir") if isinstance(config, dict) else None
    if isinstance(configured, str) and configured:
        return Path(configured).expanduser()
    return Path.home() / "Documents" / "SDPM-Presentations"


def _same_dir(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def open_hint(deck_dir: Path, root: Path) -> str | None:
    """``sdpm open <id>`` for a deck the Web UI can open (it has deck.json, sits directly in
    ``root`` and has a valid id); None otherwise, so a hint never names a command that fails."""
    real = Path(os.path.realpath(deck_dir))
    if not (real / "deck.json").is_file() or not _same_dir(real.parent, root) or not _valid_deck_id(real.name):
        return None
    return f"sdpm open {real.name}"


def _is_path(arg: str) -> bool:
    separators = ("/", "\\") if os.name == "nt" else ("/",)
    return arg in (".", "..") or arg.startswith("~") or any(s in arg for s in separators)


def resolve_deck(arg: str) -> str:
    """The Web UI id of ``arg`` (a deck folder, or a deck name in the deck root)."""
    root = deck_root()
    if _is_path(arg):
        real = Path(os.path.realpath(os.path.expanduser(arg)))
        if not (real / "deck.json").is_file():
            raise cu.Stop(1, f"No deck at {real} (no deck.json).")
        if not _same_dir(real.parent, root):
            raise cu.Stop(1, f"The Web UI shows decks in {root}; {real} is not there. "
                             f"Move it there, or run with SDPM_DECK_ROOT={real.parent}.")
        if not _valid_deck_id(real.name):
            raise cu.Stop(1, f"The Web UI cannot open a deck folder named {real.name!r}; rename it "
                             "to letters, digits, '.', '_' and '-'.")
        return real.name
    if not _valid_deck_id(arg):
        raise cu.Stop(2, OPEN_USAGE)
    if not (root / arg / "deck.json").is_file():
        raise cu.Stop(1, f"No deck {arg} in {root}.")
    return arg


def open_deck(ctx: Context, args: list[str]) -> int:
    """``sdpm open DECK``: the deck's page in the Web UI. A bad deck starts nothing."""
    if len(args) != 1 or not args[0]:
        cu.warn(OPEN_USAGE)
        return 2
    deck_id = resolve_deck(args[0])
    return webui(ctx, f"/decks/#{deck_id}")


def mcp(ctx: Context) -> int:
    """The stdio server for a terminal check; nothing of ours may touch stdout here."""
    argv = [ctx.uv, "run", "--frozen", "--directory", str(ctx.server_dir), "python", "server.py"]
    sys.stdout.flush()
    if os.name != "nt":
        os.execve(ctx.uv, argv, cu.child_env())
    return _call(argv, env=cu.child_env())


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------


def doctor(ctx: Context) -> int:
    # The server's own environment: running uv at the checkout root would sync the whole
    # workspace there, and the next `sdpm update` would remove it again.
    return _call([ctx.uv, "run", "--frozen", "--directory", str(ctx.server_dir), "python",
                  str(ctx.checkout / "scripts" / "doctor.py")], env=cu.child_env())


def _ask(question: str) -> bool:
    prompt = f"{question} [y/N] "
    try:
        if os.name != "nt":
            with open("/dev/tty", "r+", encoding="utf-8", errors="replace") as tty:
                tty.write(prompt)
                tty.flush()
                return tty.readline().strip().lower() in {"y", "yes"}
        return input(prompt).strip().lower() in {"y", "yes"}
    except (EOFError, OSError):
        return False


def uninstall(ctx: Context) -> int:
    if not cu.tty_allowed():
        cu.warn("Run sdpm uninstall in a terminal.")
        return 2
    print(f"This removes {ctx.home}, the sdpm command and desktop shortcuts.")
    if not _ask("Continue?"):
        print("Aborted.")
        return 0
    _call(ctx.client_config("unregister"), env=cu.child_env())
    paths: list[Path] = []
    if ctx.launcher is not None:
        paths.append(ctx.launcher)
        if os.name == "nt":
            paths.append(ctx.launcher.with_name("sdpm.cmd"))
    desktop = Path.home() / "Desktop"
    paths += [desktop / "SDPM.command", desktop / "SDPM.lnk",
              Path.home() / ".local" / "share" / "applications" / "sdpm.desktop"]
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            cu.warn(f"Could not remove {path}: {error.strerror or error}")
    shutil.rmtree(str(ctx.home), ignore_errors=True)
    print("SDPM removed.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def dispatch(ctx: Context, rest: list[str]) -> int:
    command = rest[0] if rest else ""
    args = rest[1:]
    if command == "":
        return status(ctx)
    if command in ("webui", "launch"):
        return webui(ctx)
    if command == "open":
        return open_deck(ctx, args)
    if command == "mcp":
        return mcp(ctx)
    if command in ("register", "unregister"):
        return clients_command(ctx, command, args)
    if command == "mcp-config":
        return clients_command(ctx, "print", args)
    if command == "doctor":
        return doctor(ctx)
    if command == "uninstall":
        return uninstall(ctx)
    if command in ("version", "--version", "-v"):
        print(version(ctx))
        return 0
    if command == "path":
        print(ctx.checkout)
        return 0
    if command in ("help", "--help", "-h"):
        print(HELP_TEXT)
        return 0
    if command == "update":
        cu.warn("Run sdpm update (the sdpm command fetches first).")
        return 2
    cu.warn(f"Unknown command: {command}")
    print(HELP_TEXT, file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    # The bootstrap's own options come first; everything after them is the user's.
    args = list(sys.argv[1:] if argv is None else argv)
    known = {"--checkout": "", "--uv": "", "--launcher": ""}
    while len(args) >= 2 and args[0] in known:
        known[args[0]] = args[1]
        args = args[2:]
    if not known["--checkout"] or not known["--uv"]:
        cu.warn("usage: sdpm_command.py --checkout C --uv U [--launcher L] [COMMAND ...]")
        return 2
    if not (Path(known["--checkout"]) / ".git").exists():
        cu.warn(f"SDPM is not installed at {known['--checkout']}. Re-run the installer.")
        return 1
    try:
        return dispatch(Context(known["--checkout"], known["--uv"], known["--launcher"]), args)
    except cu.Stop as stop:
        if stop.message:
            cu.warn(stop.message)
        return stop.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
