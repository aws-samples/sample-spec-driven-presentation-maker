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
    monkeypatch.setattr(sc, "_wait_and_open", lambda port, stop, path="": None)
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


# ---------------------------------------------------------------------------
# sdpm open DECK
# ---------------------------------------------------------------------------


@pytest.fixture
def decks(tmp_path, monkeypatch):
    """A deck root with one deck, `my-deck`; no config.json is read."""
    root = tmp_path / "decks"
    (root / "my-deck").mkdir(parents=True)
    (root / "my-deck" / "deck.json").write_text("{}")
    monkeypatch.setenv("SDPM_DECK_ROOT", str(root))
    monkeypatch.delenv("SDPM_OUTPUT_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "xdg"))
    return root


@pytest.mark.parametrize(("deck_root", "output_dir", "config_json", "expected"), [
    ("<tmp>/a", "<tmp>/b", {"output_dir": "<tmp>/c"}, "<tmp>/a"),
    ("", "<tmp>/b", {"output_dir": "<tmp>/c"}, "<tmp>/b"),
    (None, None, {"output_dir": "<tmp>/c"}, "<tmp>/c"),
    (None, None, {"output_dir": "~/cfg-decks"}, "~/cfg-decks"),
    (None, None, {"output_dir": "~"}, "~"),
    (None, None, {"output_dir": ""}, "~/Documents/SDPM-Presentations"),
    (None, None, {"output_dir": 3}, "~/Documents/SDPM-Presentations"),
    (None, None, "{not json", "~/Documents/SDPM-Presentations"),
    (None, None, None, "~/Documents/SDPM-Presentations"),
])
def test_deck_root_follows_the_web_ui_and_the_engine(monkeypatch, tmp_path, deck_root, output_dir, config_json,
                                                     expected):
    from sdpm import config
    from sdpm.api import _get_output_base_dir

    def value(text):
        return text.replace("<tmp>", str(tmp_path))

    for name, raw in (("SDPM_DECK_ROOT", deck_root), ("SDPM_OUTPUT_DIR", output_dir)):
        if raw is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value(raw))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "xdg"))
    (tmp_path / "xdg" / "sdpm").mkdir(parents=True)
    if config_json is not None:
        text = config_json if isinstance(config_json, str) else value(json.dumps(config_json))
        (tmp_path / "xdg" / "sdpm" / "config.json").write_text(text)
    want = Path(value(expected)).expanduser()
    assert sc.deck_root() == want
    # The engine's order is the same off WSL (an output_dir that is not a string is its own case).
    if config_json != {"output_dir": 3}:
        monkeypatch.setattr("sdpm.engine.preview.backend._is_wsl", lambda: False)
        config.invalidate_cache()
        try:
            assert _get_output_base_dir() == want
        finally:
            config.invalidate_cache()


def test_resolve_deck_by_name_and_by_path(decks, tmp_path, monkeypatch):
    assert sc.resolve_deck("my-deck") == "my-deck"
    assert sc.resolve_deck(str(decks / "my-deck")) == "my-deck"
    assert sc.resolve_deck(str(decks / "my-deck") + "/") == "my-deck"
    monkeypatch.chdir(decks / "my-deck")
    assert sc.resolve_deck(".") == "my-deck"
    monkeypatch.chdir(decks)
    assert sc.resolve_deck("./my-deck") == "my-deck"
    monkeypatch.setenv("HOME", str(tmp_path))
    assert sc.resolve_deck("~/decks/my-deck") == "my-deck"


@pytest.mark.parametrize(("arg", "code", "text"), [
    ("nope", 1, "No deck nope in"),
    (".hidden", 2, "usage: sdpm open"),
    ("a b", 2, "usage: sdpm open"),
    ("<tmp>/elsewhere/deck", 1, "The Web UI shows decks in"),
    ("<tmp>/decks/empty", 1, "(no deck.json)"),
    ("<tmp>/decks/bad name", 1, "cannot open a deck folder named"),
])
def test_resolve_deck_refuses(decks, tmp_path, arg, code, text):
    for path in (tmp_path / "elsewhere" / "deck", decks / "bad name"):
        path.mkdir(parents=True)
        (path / "deck.json").write_text("{}")
    (decks / "empty").mkdir()
    with pytest.raises(cu.Stop) as stop:
        sc.resolve_deck(arg.replace("<tmp>", str(tmp_path)))
    assert stop.value.code == code and text in stop.value.message


def test_open_opens_the_deck_page_of_a_running_sdpm(ctx, decks, monkeypatch):
    opened = []
    monkeypatch.setattr(sc, "open_url", opened.append)
    monkeypatch.setattr(sc, "port_is_open", lambda _p: True)
    monkeypatch.setattr(sc, "is_sdpm", lambda _p: True)
    assert sc.dispatch(ctx, ["open", "my-deck"]) == 0
    assert opened == ["http://localhost:3000/decks/#my-deck"]
    assert ctx.calls == []


def test_open_starts_the_web_ui_on_loopback_and_waits_for_the_deck_page(ctx, decks, monkeypatch):
    waited = []
    monkeypatch.setattr(sc, "port_is_open", lambda _p: False)
    monkeypatch.setattr(sc.shutil, "which", lambda _n: "/x/npm")
    monkeypatch.setattr(sc, "_wait_and_open", lambda port, stop, path="": waited.append((port, path)))
    monkeypatch.setenv("SDPM_WEBUI_PORT", "3310")
    assert sc.dispatch(ctx, ["open", str(decks / "my-deck")]) == 0
    argv, kwargs = ctx.calls[-1]
    assert argv == ["/x/npm", "run", "start", "--", "--hostname", "127.0.0.1", "--port", "3310"]
    assert kwargs["env"]["NEXT_PUBLIC_MODE"] == "local"
    assert waited == [(3310, "/decks/#my-deck")]


def test_the_waiter_opens_the_path(monkeypatch):
    opened = []
    monkeypatch.setattr(sc, "open_url", opened.append)
    monkeypatch.setattr(sc, "port_is_open", lambda _p: True)
    sc._wait_and_open(3000, sc.threading.Event(), "/decks/#my-deck")
    assert opened == ["http://localhost:3000/decks/#my-deck"]


def test_open_with_a_bad_deck_or_arguments_starts_nothing(ctx, decks, monkeypatch, capsys):
    monkeypatch.setattr(sc, "port_is_open", lambda _p: pytest.fail("nothing may start"))
    with pytest.raises(cu.Stop) as stop:
        sc.dispatch(ctx, ["open", "nope"])
    assert stop.value.code == 1
    assert sc.dispatch(ctx, ["open"]) == 2
    assert sc.dispatch(ctx, ["open", "my-deck", "other"]) == 2
    assert "usage: sdpm open" in capsys.readouterr().err
    assert ctx.calls == []


def test_open_in_the_mcp_profile(ctx, decks):
    cu.write_state(ctx.home, profile="mcp")
    ctx.state = cu.load_state(ctx.home)
    assert sc.dispatch(ctx, ["open", "my-deck"]) == 1
    assert ctx.calls == []


def test_main_reports_a_bad_deck(ctx, decks, capsys):
    assert sc.main(["--checkout", str(ctx.checkout), "--uv", "/x/uv", "open", "nope"]) == 1
    assert "No deck nope in" in capsys.readouterr().err


def test_open_hint_follows_the_same_rules(decks, tmp_path):
    assert sc.open_hint(decks / "my-deck", decks) == "sdpm open my-deck"
    elsewhere = tmp_path / "elsewhere" / "deck"
    elsewhere.mkdir(parents=True)
    (elsewhere / "deck.json").write_text("{}")
    assert sc.open_hint(elsewhere, decks) is None
    (decks / "empty").mkdir()
    assert sc.open_hint(decks / "empty", decks) is None
    (decks / "bad name").mkdir()
    (decks / "bad name" / "deck.json").write_text("{}")
    assert sc.open_hint(decks / "bad name", decks) is None
    link = tmp_path / "link-root"
    link.symlink_to(decks)
    assert sc.open_hint(link / "my-deck", decks) == "sdpm open my-deck"


def test_webui_installed_at_reads_the_profile_each_call(ctx):
    assert sc.webui_installed_at(ctx.checkout) is True
    cu.write_state(ctx.home, profile="mcp")
    assert sc.webui_installed_at(ctx.checkout) is False


def test_help_lists_open(ctx, capsys):
    sc.dispatch(ctx, ["help"])
    assert "open DECK" in capsys.readouterr().out
