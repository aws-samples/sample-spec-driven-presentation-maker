# SPDX-License-Identifier: MIT-0
"""`servers/local/client_config.py` — one server template, rendered per client and OS.

Guards the onboarding contract: every client configuration points at the absolute
uv and checkout paths, never at a launcher or PATH lookup; registration goes
through the client's own CLI; nothing is written to another app's config files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "servers" / "local"))
import client_config as cc  # noqa: E402

POSIX = cc.Target(uv="/home/u/.local/bin/uv", checkout="/home/u/.sdpm/checkout", platform="linux")
WIN = cc.Target(uv=r"C:\Users\u\.local\bin\uv.exe", checkout=r"C:\Users\u\.sdpm\checkout", platform="win32")


def test_server_config_is_absolute_uv_plus_checkout_posix():
    assert cc.server_config(POSIX) == {
        "command": "/home/u/.local/bin/uv",
        "args": ["run", "--directory", "/home/u/.sdpm/checkout/servers/local", "python", "server.py"],
    }


def test_server_config_windows_notation():
    cfg = cc.server_config(WIN)
    assert cfg["command"] == r"C:\Users\u\.local\bin\uv.exe"
    assert cfg["args"][2] == r"C:\Users\u\.sdpm\checkout\servers\local"


@pytest.mark.parametrize("target", [POSIX, WIN], ids=["posix", "win32"])
def test_no_config_relies_on_launcher_uvx_or_path(target):
    doc = json.dumps(cc.config_document(list(cc.CLIENTS), target))
    for forbidden in ("uvx", "sdpm.cmd", "sdpm.ps1", "bin/sdpm", "launcher", "${", "~/.sdpm"):
        assert forbidden not in doc.replace("~/.sdpm/checkout", ""), forbidden
    # Only the manual_target hints may contain "~"; every command/arg is absolute.
    for client in cc.config_document(list(cc.CLIENTS), target)["clients"]:
        for argv in (client["register"], client["unregister"]):
            if argv:
                assert not any(a.startswith("~") for a in argv)


def test_every_client_has_cli_registration_or_manual_instructions():
    for client in cc.CLIENTS:
        assert client.register is not None or client.manual_target or client.deeplink, client.id
        rendered = cc.render_client(client, POSIX)
        assert client.label in rendered


def test_kiro_cli_registers_globally_with_force():
    argv = cc.by_id("kiro-cli").register(POSIX)
    assert argv[:3] == ["kiro-cli", "mcp", "add"]
    assert "--force" in argv and argv[argv.index("--scope") + 1] == "global"
    assert argv[argv.index("--command") + 1] == POSIX.uv
    assert json.loads(argv[argv.index("--args") + 1]) == cc.server_config(POSIX)["args"]


def test_claude_code_and_codex_use_double_dash_form():
    for cid in ("claude-code", "codex"):
        argv = cc.by_id(cid).register(POSIX)
        assert "--" in argv
        assert argv[argv.index("--") + 1:] == cc.server_argv(POSIX)
    assert cc.by_id("claude-code").register(POSIX)[3:5] == ["--scope", "user"]


def test_vscode_add_mcp_json_carries_name():
    argv = cc.by_id("vscode").register(POSIX)
    assert argv[:2] == ["code", "--add-mcp"]
    payload = json.loads(argv[2])
    assert payload["name"] == "sdpm" and payload["command"] == POSIX.uv


def test_cursor_deeplink_encodes_the_same_server_config():
    import base64

    url = cc.by_id("cursor").deeplink(POSIX)
    assert url.startswith("cursor://anysphere.cursor-deeplink/mcp/install?name=sdpm&config=")
    decoded = json.loads(base64.b64decode(url.split("config=")[1]))
    assert decoded == cc.server_config(POSIX)


def test_register_dry_run_runs_nothing_and_opens_nothing(capsys):
    ran, opened = [], []
    clients = [cc.by_id("kiro-cli"), cc.by_id("cursor"), cc.by_id("claude-desktop")]
    failures = cc.register(clients, POSIX, dry_run=True, run=ran.append, open_url=opened.append)
    assert failures == 0 and ran == [] and opened == []
    out = capsys.readouterr().out
    assert "[dry-run] kiro-cli mcp add" in out
    assert "[dry-run] open cursor://" in out
    assert "Claude Desktop" in out  # manual clients are printed, never executed


def test_register_runs_cli_and_reports_failures(capsys):
    calls = []

    def run(argv):
        calls.append(argv[0])
        return 1 if argv[0] == "codex" else 0

    clients = [cc.by_id("claude-code"), cc.by_id("codex")]
    failures = cc.register(clients, POSIX, assume_yes=True, run=run, open_url=lambda _u: True)
    assert calls == ["claude", "codex"] and failures == 1
    assert "failed" in capsys.readouterr().err


def test_register_declined_prompt_skips(monkeypatch):
    monkeypatch.setattr(cc, "_confirm", lambda _q: False)
    ran = []
    assert cc.register([cc.by_id("claude-code")], POSIX, run=ran.append) == 0
    assert ran == []


def test_unregister_uses_client_cli_or_explains(capsys):
    ran = []
    cc.unregister([cc.by_id("kiro-cli"), cc.by_id("vscode")], run=lambda a: (ran.append(a), 0)[1])
    assert ran == [["kiro-cli", "mcp", "remove", "--scope", "global", "--name", "sdpm"]]
    assert "Visual Studio Code" in capsys.readouterr().out


def test_detect_by_name_ignores_presence_and_unknown_is_rejected():
    assert [c.id for c in cc.detect(["codex", "cursor"])] == ["codex", "cursor"]
    with pytest.raises(KeyError):
        cc.detect(["notepad"])


def test_cli_print_json_and_all(tmp_path, capsys):
    rc = cc.main(["--uv", "/x/uv", "--checkout", str(tmp_path), "print", "--all", "--json"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert set(doc["server"]) == {"sdpm"}
    assert {c["id"] for c in doc["clients"]} == set(cc.CLIENT_IDS)
    assert doc["server"]["sdpm"]["args"][2] == str(tmp_path / "servers" / "local")


def test_cli_without_uv_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.delenv("SDPM_UV", raising=False)
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    with pytest.raises(SystemExit) as e:
        cc.main(["--checkout", str(tmp_path), "print", "--all"])
    assert "uv not found" in str(e.value)


def test_missing_client_executable_is_a_failure_not_a_traceback(monkeypatch, capsys):
    def raise_missing(*_a, **_k):
        raise FileNotFoundError(2, "No such file or directory", "codex")

    monkeypatch.setattr(cc.subprocess, "run", raise_missing)
    failures = cc.register([cc.by_id("codex")], POSIX, assume_yes=True)  # default runner
    assert failures == 1
    err = capsys.readouterr().err
    assert "codex" in err and "manually" in err


def test_kiro_leftovers_detects_only_our_files(tmp_path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "agents" / "sdpm-composer.json").write_text(
        '{"name": "sdpm-composer", "prompt": "file:///old/skills/sdpm-composer/SKILL.md"}')
    (tmp_path / "agents" / "other.json").write_text('{"name": "other"}')
    (tmp_path / "skills" / "sdpm-composer").symlink_to(tmp_path / "nowhere")
    (tmp_path / "skills" / "sdpm-style").mkdir()
    (tmp_path / "skills" / "sdpm-style" / "SKILL.md").write_text("x")
    (tmp_path / "skills" / "unrelated").mkdir()
    found = {p.name for p in cc.kiro_leftovers(tmp_path)}
    assert found == {"sdpm-composer.json", "sdpm-composer", "sdpm-style"}


def test_kiro_leftovers_leaves_a_user_authored_agent_of_the_same_name(tmp_path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "sdpm-composer.json").write_text(
        '{"name": "sdpm-composer", "prompt": "You compose sdpm slides.", "model": "x", "mcpServers": {"sdpm": {}}}')
    assert cc.kiro_leftovers(tmp_path) == []


def test_register_kiro_offers_and_removes_leftovers(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))
    (tmp_path / "agents").mkdir()
    agent = tmp_path / "agents" / "sdpm-composer.json"
    agent.write_text('{"prompt": "file:///c/skills/sdpm-composer/SKILL.md"}')
    cc.register([cc.by_id("kiro-cli")], POSIX, assume_yes=True, run=lambda _a: 0)
    assert not agent.exists()
    assert "previous Kiro installer" in capsys.readouterr().out


def test_register_kiro_dry_run_keeps_leftovers(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))
    (tmp_path / "agents").mkdir()
    agent = tmp_path / "agents" / "sdpm-composer.json"
    agent.write_text('{"prompt": "file:///c/skills/sdpm-composer/SKILL.md"}')
    cc.register([cc.by_id("kiro-cli")], POSIX, dry_run=True, run=lambda _a: 0)
    assert agent.exists()
    assert "[dry-run] remove" in capsys.readouterr().out


def test_unregister_kiro_removes_leftovers(tmp_path, monkeypatch):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "sdpm-create").symlink_to(tmp_path / "gone")
    cc.unregister([cc.by_id("kiro-cli")], run=lambda _a: 0)
    assert not (tmp_path / "skills" / "sdpm-create").is_symlink()
