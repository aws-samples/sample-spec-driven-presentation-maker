# SPDX-License-Identifier: MIT-0
"""`servers/local/sdpm_command.py` — every `sdpm` subcommand the bootstrap hands over (but update)."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "servers" / "local"))
import checkout_update as cu  # noqa: E402
import sdpm_command as sc  # noqa: E402


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    home = tmp_path / "home"
    checkout = home / "checkout"
    (checkout / ".git").mkdir(parents=True)
    monkeypatch.delenv("SDPM_AGENT_NAME", raising=False)
    monkeypatch.delenv("SDPM_WEBUI_PORT", raising=False)
    cu.write_state(home, channel="release", profile="full", agent_name="work", commit="a" * 40, tag=None,
                   clients=[])
    (checkout / "web-ui" / "build").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(sc, "_call", lambda argv, **kwargs: (calls.append((argv, kwargs)), 0)[1])
    context = sc.Context(str(checkout), "/x/uv", str(tmp_path / "bin" / "sdpm"))
    context.calls = calls
    return context


def test_the_bootstraps_options_come_first_and_the_rest_is_the_users(ctx, monkeypatch):
    seen = []
    monkeypatch.setattr(sc, "dispatch", lambda context, rest: seen.append(rest) or 0)
    assert sc.main(["--checkout", str(ctx.checkout), "--uv", "/x/uv", "--launcher", "/l", "mcp-config", "--all"]) == 0
    assert seen == [["mcp-config", "--all"]]
    assert sc.main(["--uv", "/x/uv", "status"]) == 2


def test_dispatch_names_and_unknown(ctx, capsys):
    assert sc.dispatch(ctx, ["path"]) == 0
    assert capsys.readouterr().out.strip() == str(ctx.checkout)
    assert sc.dispatch(ctx, ["help"]) == 0 and "Usage: sdpm" in capsys.readouterr().out
    assert sc.dispatch(ctx, ["frobnicate"]) == 2


def test_agent_name_env_then_recorded(ctx, monkeypatch):
    assert ctx.agent_name == "work"
    monkeypatch.setenv("SDPM_AGENT_NAME", "other")
    assert ctx.agent_name == "other"
    monkeypatch.setenv("SDPM_AGENT_NAME", "a:b")
    assert ctx.agent_name == "work"


def test_register_passes_paths_and_records_the_clients(ctx, monkeypatch):
    def fake(argv, **_kwargs):
        record = argv[argv.index("--record") + 1]
        Path(record).write_text(json.dumps({"registered": ["kiro-cli"]}))
        return 0

    monkeypatch.setattr(sc, "_call", fake)
    assert sc.dispatch(ctx, ["register", "--yes"]) == 0
    assert cu.load_state(ctx.home)["clients"] == ["kiro-cli"]


def test_mcp_config_goes_to_print_with_the_agent_name(ctx):
    sc.dispatch(ctx, ["mcp-config", "--json"])
    argv = ctx.calls[-1][0]
    assert argv[argv.index("--agent-name") + 1] == "work"
    assert argv[-2:] == ["print", "--json"] and "--checkout" in argv and "/x/uv" in argv


def test_doctor_runs_in_the_servers_environment(ctx):
    sc.dispatch(ctx, ["doctor"])
    argv = ctx.calls[-1][0]
    assert argv[:5] == ["/x/uv", "run", "--frozen", "--directory", str(ctx.checkout / "servers" / "local")]
    assert argv[-1] == str(ctx.checkout / "scripts" / "doctor.py")


def test_webui_binds_loopback_on_a_valid_port(ctx, monkeypatch):
    monkeypatch.setattr(sc, "port_is_open", lambda _p: False)
    monkeypatch.setattr(sc.shutil, "which", lambda _n: "/x/npm")
    monkeypatch.setattr(sc, "_wait_and_open", lambda port, stop: None)
    monkeypatch.setenv("SDPM_WEBUI_PORT", "3100")
    assert sc.webui(ctx) == 0
    argv, kwargs = ctx.calls[-1]
    assert argv == ["/x/npm", "run", "start", "--", "--hostname", "127.0.0.1", "--port", "3100"]
    assert kwargs["env"]["NEXT_PUBLIC_MODE"] == "local"
    for bad in ("0", "70000", "abc"):
        monkeypatch.setenv("SDPM_WEBUI_PORT", bad)
        with pytest.raises(cu.Stop) as stop:
            sc.webui(ctx)
        assert stop.value.code == 2


def test_webui_opens_a_running_sdpm_and_refuses_another_program(ctx, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(sc, "open_url", opened.append)
    monkeypatch.setattr(sc, "port_is_open", lambda _p: True)
    monkeypatch.setattr(sc, "is_sdpm", lambda _p: True)
    assert sc.webui(ctx) == 0 and opened == ["http://localhost:3000"]
    monkeypatch.setattr(sc, "is_sdpm", lambda _p: False)
    assert sc.webui(ctx) == 1
    assert "used by another program" in capsys.readouterr().err
    assert ctx.calls == []  # npm never started


def test_is_sdpm_needs_the_engine_answer():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert sc.is_sdpm(port) is False  # it accepts, but never answers like SDPM
    finally:
        server.close()


def test_the_browser_waiter_stops_with_a_failed_start(monkeypatch):
    opened = []
    monkeypatch.setattr(sc, "open_url", opened.append)
    monkeypatch.setattr(sc, "port_is_open", lambda _p: False)
    stop = sc.threading.Event()
    stop.set()
    sc._wait_and_open(3000, stop)
    assert opened == []


def test_webui_not_installed_in_the_mcp_profile(ctx):
    cu.write_state(ctx.home, profile="mcp")
    ctx.state = cu.load_state(ctx.home)
    assert sc.webui(ctx) == 1


def test_mcp_runs_the_server_from_its_environment(ctx, monkeypatch):
    seen = []
    monkeypatch.setattr(sc.os, "execve", lambda exe, argv, env: seen.append(argv))
    monkeypatch.setattr(sc.os, "name", "posix")
    sc.mcp(ctx)
    assert seen[-1] == ["/x/uv", "run", "--frozen", "--directory", str(ctx.checkout / "servers" / "local"), "python",
                        "server.py"]


def test_uninstall_without_a_terminal_exits_2(ctx, monkeypatch, capsys):
    monkeypatch.setattr(cu, "tty_allowed", lambda *_a: False)
    assert sc.dispatch(ctx, ["uninstall"]) == 2
    assert "in a terminal" in capsys.readouterr().err
    assert ctx.home.exists()


def test_status_shows_the_channel(ctx, monkeypatch, capsys):
    monkeypatch.setattr(sc, "version", lambda _c: "v0.13.0 (1a2b3c4)")
    sc.status(ctx)
    assert capsys.readouterr().out.splitlines()[0] == "SDPM v0.13.0 (1a2b3c4) · release channel"
