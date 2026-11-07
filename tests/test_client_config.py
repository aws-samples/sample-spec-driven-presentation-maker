# SPDX-License-Identifier: MIT-0
"""`servers/local/client_config.py` — one server template, rendered per client and OS.

Guards the onboarding contract: every client configuration points at the absolute
uv and checkout paths, never at a launcher or PATH lookup; registration goes
through the client's own CLI; nothing is written to another app's config files. The
Kiro CLI agents (orchestrator + composer) are files both engines (V2 and V3) load without
converting them.
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
        "args": ["run", "--directory", "/home/u/.sdpm/checkout/servers/local", "--frozen", "python", "server.py"],
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


@pytest.mark.parametrize("definition", [cc.kiro_agent_definition, cc.kiro_composer_definition],
                         ids=["orchestrator", "composer"])
def test_kiro_agents_are_wiring_only(definition):
    agent = definition(POSIX)
    assert agent["mcpServers"]["sdpm"]["command"] == POSIX.uv
    assert agent["mcpServers"]["sdpm"]["args"] == cc.server_config(POSIX)["args"]
    assert "prompt" not in agent and "file://" not in json.dumps(agent)
    assert "@sdpm" in agent["allowedTools"]
    assert not {"write", "shell", "execute_bash"} & set(agent["tools"])
    assert cc.KIRO_AGENT_MARKER in agent["description"]


def test_kiro_composer_has_no_delegation():
    # A composer that could delegate would start the chain again one level down.
    composer = cc.kiro_composer_definition(POSIX, "sdpm-dev")
    assert composer["name"] == "sdpm-dev-composer"
    assert composer["tools"] == composer["allowedTools"] == ["@sdpm", "read", "glob", "grep"]
    assert "toolsSettings" not in composer
    assert composer["permissions"]["rules"] == [
        {"capability": "mcp", "match": ["sdpm/*"], "effect": "allow"},
        {"capability": "fs_read", "effect": "allow"},
    ]


@pytest.mark.parametrize("name", ["sdpm", "sdpm-dev"])
def test_kiro_agent_loads_in_v2_and_v3_without_conversion(name):
    agent = cc.kiro_agent_definition(POSIX, name)
    composer = f"{name}-composer"
    # V2 fields stay: kiro-cli 2.x and `--v2` read them.
    assert agent["allowedTools"] == cc._KIRO_AGENT_TOOLS
    assert agent["toolsSettings"]["subagent"] == {"availableAgents": [composer], "trustedAgents": [composer]}
    # V3 fields: a definition with `permissions` is loaded as-is (no rejection, no rewrite + .bak).
    assert "kiroUpgrade" not in agent
    # The composer agent only: V3 shows each sub-agent up front while it defers the MCP tools,
    # so `subagent/<name>` made the agent hand the whole job to a copy of itself (M1).
    assert [t for t in agent["tools"] if t.startswith("subagent/")] == [f"subagent/{composer}"]
    rules = agent["permissions"]["rules"]
    assert all(r["effect"] == "allow" for r in rules)
    assert {r["capability"] for r in rules} == {"mcp", "subagent", "fs_read", "web_search", "web_fetch"}
    by_cap = {r["capability"]: r for r in rules}
    assert by_cap["mcp"]["match"] == ["sdpm/*"]
    assert by_cap["subagent"]["match"] == [composer]  # its composer agent only, as availableAgents in V2
    # Same trust in both engines: nothing that writes files or runs shell commands.
    assert not {"fs_write", "shell", "skill"} & set(by_cap)


def test_unregister_kiro_removes_our_upgrade_backups_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    cc.write_kiro_agent(POSIX, root=tmp_path)
    agents = tmp_path / "agents"
    ours = (agents / "sdpm.json").read_text()
    (agents / "sdpm.json.bak").write_text(ours)
    (agents / "sdpm.json.bak.1").write_text(ours)
    (agents / "sdpm.json.bak.2").write_text('{"name": "sdpm", "prompt": "mine"}')
    (agents / "sdpm-composer.json.bak").write_text((agents / "sdpm-composer.json").read_text())
    (agents / "sdpm-dev.json.bak").write_text(ours)  # another agent's backup
    cc.remove_kiro_agent(dry_run=True, root=tmp_path)
    assert (agents / "sdpm.json.bak").exists() and "[dry-run] remove" in capsys.readouterr().out
    cc.remove_kiro_agent(root=tmp_path)
    assert sorted(p.name for p in agents.iterdir()) == ["sdpm-dev.json.bak", "sdpm.json.bak.2"]

def test_write_kiro_agent_creates_refreshes_and_respects_foreign_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)  # no kiro-cli validate step
    assert cc.write_kiro_agent(POSIX, root=tmp_path) == 0
    path = tmp_path / "agents" / "sdpm.json"
    assert json.loads(path.read_text()) == cc.kiro_agent_definition(POSIX)
    assert json.loads((tmp_path / "agents" / "sdpm-composer.json").read_text()) == cc.kiro_composer_definition(POSIX)
    assert cc.kiro_agent_registered(root=tmp_path) is True
    # refresh with a new target overwrites our own file
    other = cc.Target(uv="/new/uv", checkout="/new/checkout", platform="linux")
    assert cc.write_kiro_agent(other, root=tmp_path) == 0
    assert json.loads(path.read_text())["mcpServers"]["sdpm"]["command"] == "/new/uv"
    # a user's own agent of the same name is never touched
    path.write_text('{"name": "sdpm", "prompt": "mine"}')
    assert cc.write_kiro_agent(POSIX, root=tmp_path) == 0
    assert json.loads(path.read_text()) == {"name": "sdpm", "prompt": "mine"}
    assert "not managed by sdpm" in capsys.readouterr().out
    assert cc.kiro_agent_registered(root=tmp_path) is False
    cc.remove_kiro_agent(root=tmp_path)
    assert path.exists()  # still theirs


# What kirocrew and kiro-cli's own conversion add to an agent file, as found on a machine
# after `sdpm update` (#529) had dropped them: another MCP server and its tool, shell
# settings for kiro-cli 2.x and their 3.x rules, kiroUpgrade.
FOREIGN_SERVER = {"command": "/opt/aim", "args": ["mcp", "start-server", "creds"], "x-kirocrew": {"managed": True}}
DENY_V2 = {"deniedCommands": ["git reset --hard.*"]}
DENY_V3 = {"capability": "shell", "match": ["git reset --hard*"], "effect": "deny"}


def _agent_with_additions(target: cc.Target) -> dict:
    agent = cc.kiro_agent_definition(target)
    agent["mcpServers"]["sdpm"]["env"] = {"SDPM_X": "1"}
    agent["mcpServers"]["creds-agent"] = FOREIGN_SERVER
    agent["tools"] = ["@creds-agent", *agent["tools"], "web"]
    agent["toolsSettings"]["execute_bash"] = DENY_V2
    agent["toolsSettings"]["shell"] = DENY_V2
    agent["permissions"]["rules"] = [DENY_V3, *agent["permissions"]["rules"], {"capability": "skill", "effect": "allow"}]
    agent["kiroUpgrade"] = {"revision": 2, "fingerprint": "sha256:x"}
    return agent


def test_write_kiro_agent_keeps_what_other_tools_added(tmp_path, monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    path = tmp_path / "agents" / "sdpm.json"
    path.parent.mkdir()
    path.write_text(json.dumps(_agent_with_additions(POSIX)))
    moved = cc.Target(uv="/new/uv", checkout="/new/checkout", platform="linux")
    assert cc.write_kiro_agent(moved, root=tmp_path) == 0
    agent = json.loads(path.read_text())
    ours = cc.kiro_agent_definition(moved)
    # Ours, brought up to date.
    assert agent["mcpServers"]["sdpm"] == {**ours["mcpServers"]["sdpm"], "env": {"SDPM_X": "1"}}
    assert all(t in agent["tools"] for t in ours["tools"])
    assert all(r in agent["permissions"]["rules"] for r in ours["permissions"]["rules"])
    # Theirs, untouched and in their place.
    assert agent["mcpServers"]["creds-agent"] == FOREIGN_SERVER
    assert agent["tools"][0] == "@creds-agent" and "web" in agent["tools"]
    assert agent["toolsSettings"]["execute_bash"] == DENY_V2 and agent["toolsSettings"]["shell"] == DENY_V2
    assert agent["permissions"]["rules"][0] == DENY_V3
    assert {"capability": "skill", "effect": "allow"} in agent["permissions"]["rules"]
    assert agent["kiroUpgrade"] == {"revision": 2, "fingerprint": "sha256:x"}
    # Writing again changes nothing (no duplicated entries).
    before = path.read_text()
    assert cc.write_kiro_agent(moved, root=tmp_path) == 0
    assert path.read_text() == before


def test_write_kiro_agent_gives_v2_additions_their_v3_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    path = tmp_path / "agents" / "sdpm.json"
    path.parent.mkdir()
    old = {"name": "sdpm", "description": "SDPM " + cc.KIRO_AGENT_MARKER,
           "mcpServers": {"creds-agent": FOREIGN_SERVER}, "tools": ["@sdpm", "@creds-agent"],
           "allowedTools": ["@sdpm", "@creds-agent"],
           "toolsSettings": {"subagent": {"availableAgents": ["sdpm", "helper"], "trustedAgents": ["sdpm", "helper"]}}}
    path.write_text(json.dumps(old))
    assert cc.write_kiro_agent(POSIX, root=tmp_path) == 0
    agent = json.loads(path.read_text())
    rules = agent["permissions"]["rules"]
    # Trusted in 2.x, so trusted in 3.x: the meaning is kept, not widened or dropped.
    assert {"capability": "mcp", "match": ["creds-agent/*"], "effect": "allow"} in rules
    assert {"capability": "subagent", "match": ["helper"], "effect": "allow"} in rules
    assert agent["allowedTools"][:2] == ["@sdpm", "@creds-agent"]
    # The self-delegation is sdpm's and goes; the other agent stays where it was.
    assert agent["toolsSettings"]["subagent"]["trustedAgents"] == ["sdpm-composer", "helper"]
    assert {"capability": "subagent", "match": ["sdpm"], "effect": "allow"} not in rules
    assert agent["mcpServers"]["creds-agent"] == FOREIGN_SERVER


def test_write_kiro_agent_leaves_v2_additions_without_a_v3_form_and_names_them(tmp_path, monkeypatch, capsys):
    # Writing `permissions` would make kiro-cli 3.x ignore the 2.x deny list: a denied command would run.
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    path = tmp_path / "agents" / "sdpm.json"
    path.parent.mkdir()
    old = {"name": "sdpm", "description": "SDPM " + cc.KIRO_AGENT_MARKER, "tools": ["@sdpm", "execute_bash"],
           "allowedTools": ["@sdpm", "execute_bash"], "toolsSettings": {"execute_bash": DENY_V2}}
    path.write_text(json.dumps(old))
    assert cc.write_kiro_agent(POSIX, root=tmp_path) == 0
    assert json.loads(path.read_text()) == old
    out = capsys.readouterr().out
    assert "allowedTools: execute_bash" in out and "toolsSettings.execute_bash" in out
    assert "left" in out and "sdpm register kiro-cli" in out
    assert cc._kiro_agent_ours(root=tmp_path) is True  # still ours; unregister removes it
    assert not (tmp_path / "agents" / "sdpm-composer.json").exists()  # the two are written together


def test_write_kiro_agent_dry_run_and_remove(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    assert cc.write_kiro_agent(POSIX, dry_run=True, root=tmp_path) == 0
    assert not (tmp_path / "agents").exists()
    out = capsys.readouterr().out
    assert "[dry-run] write " + str(tmp_path / "agents" / "sdpm-composer.json") in out
    assert "[dry-run] write " + str(tmp_path / "agents" / "sdpm.json") in out
    cc.write_kiro_agent(POSIX, root=tmp_path)
    cc.remove_kiro_agent(root=tmp_path)
    assert list((tmp_path / "agents").iterdir()) == []  # both files of the unit


# What `sdpm register` wrote before the composer agent (0.12 and main up to 845865c2): the
# agent delegated to itself.
def _self_delegating_agent(target: cc.Target, name: str = "sdpm") -> dict:
    agent = cc.kiro_agent_definition(target, name)
    agent["tools"] = [*cc._KIRO_AGENT_TOOLS, f"subagent/{name}"]
    agent["toolsSettings"] = {"subagent": {"availableAgents": [name], "trustedAgents": [name]}}
    agent["permissions"]["rules"][1] = {"capability": "subagent", "match": [name], "effect": "allow"}
    return agent


@pytest.mark.parametrize("name", ["sdpm", "sdpm-dev"])
def test_refreshing_a_self_delegating_agent_removes_the_self_delegation(tmp_path, monkeypatch, name):
    # `_with` only adds: without the swap, `sdpm update` would keep `subagent/sdpm` (M1).
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / f"{name}.json").write_text(json.dumps(_self_delegating_agent(POSIX, name)))
    assert cc.kiro_agent_registered(name, root=tmp_path) is False  # status: register again
    assert cc.write_kiro_agent(POSIX, name=name, root=tmp_path) == 0
    agent = json.loads((agents / f"{name}.json").read_text())
    assert agent == cc.kiro_agent_definition(POSIX, name)
    assert f"subagent/{name}" not in agent["tools"]
    assert name not in agent["toolsSettings"]["subagent"]["availableAgents"]
    assert {"capability": "subagent", "match": [name], "effect": "allow"} not in agent["permissions"]["rules"]
    assert json.loads((agents / f"{name}-composer.json").read_text()) == cc.kiro_composer_definition(POSIX, name)
    assert cc.kiro_agent_registered(name, root=tmp_path) is True


def test_refreshing_a_self_delegating_agent_keeps_what_other_tools_added(tmp_path, monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    path = tmp_path / "agents" / "sdpm.json"
    path.parent.mkdir()
    old = _self_delegating_agent(POSIX)
    old["tools"].append("subagent/helper")
    old["toolsSettings"]["subagent"]["availableAgents"].append("helper")
    old["permissions"]["rules"].append({"capability": "subagent", "match": ["helper"], "effect": "allow"})
    path.write_text(json.dumps(old))
    assert cc.write_kiro_agent(POSIX, root=tmp_path) == 0
    agent = json.loads(path.read_text())
    assert [t for t in agent["tools"] if t.startswith("subagent/")] == ["subagent/sdpm-composer", "subagent/helper"]
    assert agent["toolsSettings"]["subagent"] == {"availableAgents": ["sdpm-composer", "helper"],
                                                  "trustedAgents": ["sdpm-composer"]}
    subagent_rules = [r["match"] for r in agent["permissions"]["rules"] if r["capability"] == "subagent"]
    assert subagent_rules == [["sdpm-composer"], ["helper"]]


def test_write_kiro_agent_replaces_the_old_installers_composer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    composer = tmp_path / "agents" / "sdpm-composer.json"
    composer.parent.mkdir()
    composer.write_text('{"name": "sdpm-composer", "prompt": "file:///old/skills/sdpm-composer/SKILL.md"}')
    assert cc.write_kiro_agent(POSIX, root=tmp_path) == 0
    assert json.loads(composer.read_text()) == cc.kiro_composer_definition(POSIX)
    assert "previous Kiro installer" in capsys.readouterr().out
    assert cc.kiro_leftovers(tmp_path) == []


def test_write_kiro_agent_leaves_a_users_composer_alone_and_does_not_delegate(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    agents = tmp_path / "agents"
    agents.mkdir()
    theirs = '{"name": "sdpm-composer", "prompt": "You compose sdpm slides.", "model": "x"}'
    (agents / "sdpm-composer.json").write_text(theirs)
    (agents / "sdpm.json").write_text(json.dumps(_self_delegating_agent(POSIX)))
    assert cc.write_kiro_agent(POSIX, root=tmp_path) == 0
    assert (agents / "sdpm-composer.json").read_text() == theirs
    out = capsys.readouterr().out
    assert "not managed by sdpm" in out and "without a composer agent" in out
    # Variant B: no delegation at all, so neither itself nor their agent is picked.
    agent = json.loads((agents / "sdpm.json").read_text())
    assert agent == cc.kiro_agent_definition(POSIX, with_composer=False)
    assert "use_subagent" not in agent["tools"] and not any(t.startswith("subagent/") for t in agent["tools"])
    assert "toolsSettings" not in agent
    assert {r["capability"] for r in agent["permissions"]["rules"]} == {"mcp", "fs_read", "web_search", "web_fetch"}
    assert cc.kiro_agent_registered(root=tmp_path) is True
    cc.remove_kiro_agent(root=tmp_path)
    assert sorted(p.name for p in agents.iterdir()) == ["sdpm-composer.json"]  # still theirs


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
    clients = [cc.by_id("claude-code"), cc.by_id("cursor"), cc.by_id("claude-desktop")]
    failures = cc.register(clients, POSIX, dry_run=True, run=ran.append, open_url=opened.append)
    assert failures == 0 and ran == [] and opened == []
    out = capsys.readouterr().out
    assert "[dry-run] claude mcp add" in out
    assert "[dry-run] open cursor://" in out
    assert "Claude Desktop" in out and "sdpm.mcpb" in out  # manual clients are listed, never executed


def test_register_runs_cli_and_reports_failures(capsys):
    calls = []

    def run(argv):
        calls.append(argv[0])
        return 1 if argv[0] == "codex" else 0

    clients = [cc.by_id("claude-code"), cc.by_id("codex")]
    failures = cc.register(clients, POSIX, assume_yes=True, run=run, open_url=lambda _u: True)
    assert calls == ["claude", "codex"] and failures == 1
    out = capsys.readouterr().out
    assert "Codex" in out and "failed" in out and "sdpm mcp-config codex" in out
    assert "Claude Code" in out and "registered" in out


def test_register_nothing_chosen_runs_nothing_and_says_skipped(capsys):
    ran = []
    assert cc.register([cc.by_id("claude-code")], POSIX, run=ran.append, chosen=[]) == 0
    assert ran == []
    out = capsys.readouterr().out
    assert "skipped" in out and "sdpm register claude-code" in out


def test_picker_fallback_line_input(monkeypatch, capsys):
    import picker

    monkeypatch.setattr(picker, "_tty_available", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _p: "2")
    opts = [picker.Option("a", "A"), picker.Option("b", "B"), picker.Option("c", "C", enabled=False)]
    assert picker.pick(opts, title="t") == ["b"]
    monkeypatch.setattr("builtins.input", lambda _p: "")
    assert picker.pick(opts, title="t") == ["a", "b"]  # Enter = defaults (all checked)
    monkeypatch.setattr("builtins.input", lambda _p: "none")
    assert picker.pick(opts, title="t") == []
    assert "C" in capsys.readouterr().out  # disabled rows are shown


def test_unregister_uses_client_cli_or_explains(capsys):
    ran = []
    cc.unregister([cc.by_id("claude-code"), cc.by_id("vscode")], run=lambda a: (ran.append(a), 0)[1])
    assert ran == [["claude", "mcp", "remove", "--scope", "user", "sdpm"]]
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
    captured = capsys.readouterr()
    assert "codex" in captured.err and "by hand" in captured.out


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
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "sdpm-composer").symlink_to(tmp_path / "nowhere")
    cc.register([cc.by_id("kiro-cli")], POSIX, assume_yes=True, run=lambda _a: 0)
    assert json.loads(agent.read_text()) == cc.kiro_composer_definition(POSIX)  # replaced by ours
    assert not (tmp_path / "skills" / "sdpm-composer").is_symlink()
    assert (tmp_path / "agents" / "sdpm.json").exists()
    assert "previous Kiro installer" in capsys.readouterr().out


def test_register_kiro_dry_run_keeps_leftovers(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))
    (tmp_path / "agents").mkdir()
    agent = tmp_path / "agents" / "sdpm-composer.json"
    agent.write_text('{"prompt": "file:///c/skills/sdpm-composer/SKILL.md"}')
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    cc.register([cc.by_id("kiro-cli")], POSIX, dry_run=True, run=lambda _a: 0)
    assert agent.exists() and not (tmp_path / "agents" / "sdpm.json").exists()
    assert "[dry-run] remove" in capsys.readouterr().out


def test_unregister_kiro_removes_leftovers(tmp_path, monkeypatch):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "sdpm-create").symlink_to(tmp_path / "gone")
    cc.unregister([cc.by_id("kiro-cli")], run=lambda _a: 0)
    assert not (tmp_path / "skills" / "sdpm-create").is_symlink()


def test_unregister_kiro_removes_both_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    cc.write_kiro_agent(POSIX)
    assert sorted(p.name for p in (tmp_path / "agents").iterdir()) == ["sdpm-composer.json", "sdpm.json"]
    cc.unregister([cc.by_id("kiro-cli")], run=lambda _a: 0)
    assert list((tmp_path / "agents").iterdir()) == []


def test_register_kiro_offers_to_remove_global_entry(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings" / "mcp.json").write_text('{"mcpServers": {"sdpm": {"command": "uv"}}}')
    ran = []
    cc.register([cc.by_id("kiro-cli")], POSIX, assume_yes=True, run=lambda a: (ran.append(a), 0)[1])
    assert ran == [["kiro-cli", "mcp", "remove", "--scope", "global", "--name", "sdpm"]]
    assert "redundant" in capsys.readouterr().out


def test_register_claude_code_offers_plugin_uninstall(monkeypatch, capsys):
    monkeypatch.setattr(cc, "claude_plugin_installed", lambda: True)
    ran = []
    cc.register([cc.by_id("claude-code")], POSIX, assume_yes=True, run=lambda a: (ran.append(a), 0)[1])
    assert ran == [
        ["claude", "mcp", "add", "--scope", "user", "sdpm", "--", *cc.server_argv(POSIX)],
        ["claude", "plugin", "uninstall", "sdpm@sdpm"],
    ]
    assert "appear twice" in capsys.readouterr().out


def test_register_claude_code_without_plugin_runs_only_add(monkeypatch):
    monkeypatch.setattr(cc, "claude_plugin_installed", lambda: False)
    ran = []
    cc.register([cc.by_id("claude-code")], POSIX, assume_yes=True, run=lambda a: (ran.append(a), 0)[1])
    assert len(ran) == 1


# ---------------------------------------------------------------------------
# refresh — the end of `sdpm update`
# ---------------------------------------------------------------------------

OLD_LAUNCHER = "#!/usr/bin/env bash\n# sdpm — the one launcher for a local SDPM installation (~/.sdpm).\necho old\n"
NEW_LAUNCHER = OLD_LAUNCHER.replace("echo old", "# ends with client_config.py refresh\necho new")


def _checkout_with_launchers(root: Path) -> Path:
    install = root / "checkout" / "scripts" / "install"
    install.mkdir(parents=True)
    (install / "launcher.sh").write_text(NEW_LAUNCHER)
    (install / "launcher.ps1").write_text(NEW_LAUNCHER)
    return root / "checkout"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes and inodes")
def test_refresh_launcher_renames_a_new_file_over_the_old_and_keeps_its_mode(tmp_path):
    checkout = _checkout_with_launchers(tmp_path)
    installed = tmp_path / "bin" / "sdpm"
    installed.parent.mkdir()
    installed.write_text(OLD_LAUNCHER)
    installed.chmod(0o755)
    running = installed.open("rb")  # what a running bash holds
    inode = installed.stat().st_ino
    assert cc.refresh_launcher(installed, checkout) == "updated"
    assert installed.read_text() == NEW_LAUNCHER
    assert installed.stat().st_ino != inode and installed.stat().st_mode & 0o777 == 0o755
    assert running.read().decode() == OLD_LAUNCHER  # the running copy is untouched
    running.close()
    assert sorted(p.name for p in installed.parent.iterdir()) == ["sdpm"]  # no temp file left
    assert cc.refresh_launcher(installed, checkout) == "up to date"


def test_refresh_launcher_leaves_links_and_foreign_files_alone(tmp_path):
    checkout = _checkout_with_launchers(tmp_path)
    (tmp_path / "bin").mkdir()
    foreign = tmp_path / "bin" / "sdpm"
    foreign.write_text("#!/bin/sh\necho my own sdpm\n")
    assert "not an SDPM launcher" in cc.refresh_launcher(foreign, checkout)
    assert foreign.read_text() == "#!/bin/sh\necho my own sdpm\n"
    if sys.platform != "win32":
        link = tmp_path / "bin" / "sdpm-dev"
        link.symlink_to(checkout / "scripts" / "install" / "launcher.sh")
        assert "is a link" in cc.refresh_launcher(link, checkout)
        assert link.is_symlink()
    assert "not refreshed" in cc.refresh_launcher(tmp_path / "bin" / "missing", checkout)


def test_refresh_launcher_ps1_is_written_with_a_bom(tmp_path):
    checkout = _checkout_with_launchers(tmp_path)
    installed = tmp_path / "sdpm.ps1"
    installed.write_bytes(b"\xef\xbb\xbf" + OLD_LAUNCHER.replace("\n", "\r\n").encode())  # Set-Content -Encoding UTF8
    assert cc.refresh_launcher(installed, checkout) == "updated"
    assert installed.read_bytes() == b"\xef\xbb\xbf" + NEW_LAUNCHER.encode()
    assert cc.refresh_launcher(installed, checkout) == "up to date"


def test_update_leftovers_lists_old_environments_and_our_files_only(tmp_path, monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    checkout, kiro = tmp_path / "checkout", tmp_path / "kiro"
    for venv in ("servers/local/.venv", "sdpm/.venv"):
        (checkout / venv).mkdir(parents=True)
        (checkout / venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (checkout / ".venv").mkdir()  # the workspace environment in use
    (checkout / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (checkout / "agent" / ".venv").mkdir(parents=True)  # not in the list
    cc.write_kiro_agent(POSIX, root=kiro)
    (kiro / "agents" / "sdpm.json.bak").write_text((kiro / "agents" / "sdpm.json").read_text())
    found = cc.update_leftovers(checkout, root=kiro)
    assert found == [checkout / "servers/local/.venv", checkout / "sdpm/.venv", kiro / "agents" / "sdpm.json.bak"]
    (checkout / "sdpm/.venv/pyvenv.cfg").unlink()  # a directory that is not an environment stays
    assert checkout / "sdpm/.venv" not in cc.update_leftovers(checkout, root=kiro)


def _listing(monkeypatch, outputs: dict):
    """What each client's `mcp list` prints; a client absent from ``outputs`` cannot tell."""
    monkeypatch.setattr(cc, "_list_output", lambda c: outputs.get(c.id) if c.list_cmd else None)


CLAUDE_HERE = ("Checking MCP server health...\n\n"
               f"sdpm: {POSIX.uv} run --directory {POSIX.server_dir} python server.py - ✓ Connected\n")
CODEX_NONE = "Name  Command  Args\nother  npx  -y other-server\n"


def test_refresh_registrations_registers_again_only_what_is_registered(monkeypatch, tmp_path):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))  # no Kiro agent
    clients = [cc.by_id("claude-code"), cc.by_id("codex"), cc.by_id("vscode")]
    _listing(monkeypatch, {"claude-code": CLAUDE_HERE, "codex": CODEX_NONE})
    monkeypatch.setattr(cc, "claude_plugin_installed", lambda: pytest.fail("no cleanup offers during refresh"))
    removed, added = [], []
    failures, missing, elsewhere = cc.refresh_registrations(
        POSIX, clients=clients, run=lambda a: (added.append(a), 0)[1], run_quiet=lambda a: (removed.append(a), 0)[1])
    assert failures == 0 and elsewhere == []
    assert removed == [["claude", "mcp", "remove", "--scope", "user", "sdpm"]]  # `mcp add` refuses an existing name
    assert added == [cc.by_id("claude-code").register(POSIX)]
    assert [c.id for c in missing] == ["codex"]  # found, not registered: named, never added


def test_refresh_register_missing_adds_the_clients_without_the_server(monkeypatch, tmp_path, capsys):
    # The installer's --register over an existing install: refresh, then add what is missing.
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    target = cc.Target(uv=POSIX.uv, checkout=str(checkout), platform="linux")
    here = f"sdpm: {target.uv} run --directory {target.server_dir} --frozen python server.py - ✓ Connected\n"
    _listing(monkeypatch, {"claude-code": here, "codex": CODEX_NONE})
    added = []
    rc = cc.refresh(target, launcher=None, since=None, clients=[cc.by_id("claude-code"), cc.by_id("codex")],
                    run=lambda a: (added.append(a), 0)[1], run_quiet=lambda a: 0, register_missing=True)
    assert rc == 0
    assert added == [cc.by_id("claude-code").register(target), cc.by_id("codex").register(target)]
    assert "add with: sdpm register" not in capsys.readouterr().out


def test_refresh_registrations_leaves_an_entry_for_another_checkout_alone(monkeypatch, tmp_path):
    # `make register-dev CLIENTS=claude-code` registers the same name with a working tree.
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))
    dev = cc.Target(uv=POSIX.uv, checkout="/home/u/.sdpm/checkout-dev", platform="linux")
    clients = [cc.by_id("claude-code"), cc.by_id("codex")]
    _listing(monkeypatch, {
        "claude-code": f"sdpm: {dev.uv} run --directory {dev.server_dir} python server.py - ✓ Connected\n",
        "codex": f"Name  Command  Args\nsdpm  {dev.uv}  run --directory {dev.server_dir} python server.py\n"
                 f"sdpm-dev  {POSIX.uv}  run --directory {POSIX.server_dir} python server.py\n",
    })
    calls = []
    failures, missing, elsewhere = cc.refresh_registrations(
        POSIX, clients=clients, run=lambda a: (calls.append(a), 0)[1], run_quiet=lambda a: (calls.append(a), 0)[1])
    assert calls == []  # neither removed nor added
    assert failures == 0 and missing == []
    assert [c.id for c in elsewhere] == ["claude-code", "codex"]


def test_refresh_names_the_entries_it_leaves_alone(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))
    _listing(monkeypatch, {"claude-code": "sdpm: uv run --directory /work/tree/servers/local python server.py\n"})
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    target = cc.Target(uv=POSIX.uv, checkout=str(checkout), platform="linux")
    calls = []
    rc = cc.refresh(target, launcher=None, since=None, clients=[cc.by_id("claude-code")],
                    run=lambda a: (calls.append(a), 0)[1], run_quiet=lambda a: (calls.append(a), 0)[1])
    assert rc == 0 and calls == []
    assert "Claude Code: its sdpm server runs another checkout — left alone" in capsys.readouterr().out


def test_refresh_registrations_refreshes_the_kiro_agent_without_kiro_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path))
    monkeypatch.setattr(cc.shutil, "which", lambda _n: None)
    (tmp_path / "agents").mkdir()
    old = {"name": "work", "description": "SDPM " + cc.KIRO_AGENT_MARKER, "tools": ["@sdpm"]}  # 2.x-only file
    (tmp_path / "agents" / "work.json").write_text(json.dumps(old))
    failures, missing, elsewhere = cc.refresh_registrations(POSIX, agent_name="work", clients=[], run=lambda _a: 0)
    assert failures == 0 and missing == [] and elsewhere == []
    agent = json.loads((tmp_path / "agents" / "work.json").read_text())
    assert agent == cc.kiro_agent_definition(POSIX, "work")
    assert json.loads((tmp_path / "agents" / "work-composer.json").read_text()) == cc.kiro_composer_definition(
        POSIX, "work")
    assert not (tmp_path / "agents" / "sdpm.json").exists()  # the name chosen at install, nothing else


CHANGELOG_OLD = """# Changelog

## [0.12.0] - 2026-11-05

### Upgrading from 0.11

**AWS stack.** Deploy everything.

- **Self sign-up is off.** / Set `auth.selfSignUp`.

**Local installs (`sdpm update`).**

- **Old step.** Do the old
  thing once.
"""

CHANGELOG_NEW = """# Changelog

## [Unreleased]

### Upgrading from 0.12

**Local installs (`sdpm update`).**

- **Kiro CLI.** Start the agent itself:
  `kiro-cli chat --agent sdpm`.
- **Second.** Another thing.

**AWS stack.** Deploy.

- **Not for local installs.** / Deploy.

### Fixed

- A fix.

## [0.12.0] - 2026-11-05

### Upgrading from 0.11

**AWS stack.** Deploy everything.

- **Self sign-up is off.** / Set `auth.selfSignUp`.

**Local installs (`sdpm update`).**

- **Old step.** Do the old thing once.
"""


def test_local_install_notes_reads_only_the_local_installs_blocks():
    assert cc.local_install_notes(CHANGELOG_NEW) == [
        ("Unreleased", "**Kiro CLI.** Start the agent itself: `kiro-cli chat --agent sdpm`."),
        ("Unreleased", "**Second.** Another thing."),
        ("0.12.0", "**Old step.** Do the old thing once."),
    ]


def test_upgrade_notes_shows_what_the_previous_checkout_did_not_have(tmp_path, capsys):
    import subprocess

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG_OLD)
    git("add", "CHANGELOG.md")
    git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "old")
    since = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                           capture_output=True, text=True, check=True).stdout.strip()
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG_NEW)
    notes = cc.upgrade_notes(tmp_path, since)
    # "Old step" was re-wrapped, not changed: it is not shown again.
    assert [text.split("**")[1] for _v, text in notes] == ["Kiro CLI.", "Second."]
    assert cc.upgrade_notes(tmp_path, None) == [] and cc.upgrade_notes(tmp_path, "--output=x") == []
    cc.print_upgrade_notes(notes, tmp_path)
    out = capsys.readouterr().out
    assert "What to do after this update" in out and "Unreleased" in out and "**" not in out


def test_cli_refresh_runs_every_part(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KIRO_HOME", str(tmp_path / "kiro"))
    monkeypatch.setattr(cc, "detect", lambda *_a: [])
    checkout = _checkout_with_launchers(tmp_path)
    (checkout / "sdpm" / ".venv").mkdir(parents=True)
    (checkout / "sdpm" / ".venv" / "pyvenv.cfg").write_text("")
    installed = tmp_path / "sdpm"
    installed.write_text(OLD_LAUNCHER)
    rc = cc.main(["--uv", "/x/uv", "--checkout", str(checkout), "refresh", "--launcher", str(installed)])
    assert rc == 0
    assert installed.read_text() == NEW_LAUNCHER
    assert not (checkout / "sdpm" / ".venv").exists()
    out = capsys.readouterr().out
    assert "sdpm command: updated" in out and "removed" in out


def test_outcomes_print_on_a_narrow_windows_console(monkeypatch):
    # A piped Python on Windows writes the ANSI code page; ✓ must not stop the refresh.
    import io

    raw = io.BytesIO()
    narrow = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", narrow)
    cc.tolerate_narrow_console()
    cc.print_outcomes([cc.Outcome(cc.by_id("claude-code"), "registered", "→ ask for slides")])
    narrow.flush()
    assert b"Claude Code" in raw.getvalue() and b"registered" in raw.getvalue()
