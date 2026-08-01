# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Tests for the Kiro installer's legacy-cleanup behavior.

v0.5.x removed the pre-registered composer agent (composers are self-spawned
via the persona's spawn template). The installer must remove the legacy
generated ``~/.kiro/agents/sdpm-composer.json`` — but ONLY when it matches
the known generated form (for whatever checkout rendered it — leftovers
from moved checkouts are stale and removed too); user-edited files are
left in place with a warning.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_INSTALL_PY = Path(__file__).resolve().parent.parent / "clients" / "kiro" / "install.py"
_spec = importlib.util.spec_from_file_location("kiro_install", _INSTALL_PY)
kiro_install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_spec and kiro_install)


def _generated_config(checkout: Path) -> dict:
    """What the old installer template rendered for ``checkout``."""
    return kiro_install._expected_composer_config(checkout)


@pytest.fixture
def agents_dir(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    return d


def _write_legacy(agents_dir: Path, config) -> Path:
    p = agents_dir / "sdpm-composer.json"
    p.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return p


REPO_ROOT = kiro_install.REPO_ROOT


class TestCleanupLegacyComposerAgent:
    def test_removes_known_generated_form(self, agents_dir):
        p = _write_legacy(agents_dir, _generated_config(REPO_ROOT))
        kiro_install.cleanup_legacy_composer_agent(agents_dir)
        assert not p.exists()

    def test_formatting_differences_do_not_block_cleanup(self, agents_dir):
        # Old installer wrote the rendered template verbatim — indentation
        # and key order may differ across versions. Parsed equality decides.
        p = agents_dir / "sdpm-composer.json"
        p.write_text(json.dumps(_generated_config(REPO_ROOT)), encoding="utf-8")
        kiro_install.cleanup_legacy_composer_agent(agents_dir)
        assert not p.exists()

    def test_removes_other_checkouts_generated_file(self, agents_dir, tmp_path):
        # A leftover from a moved/old checkout would win over self-spawn
        # (personas prefer a registered sdpm-composer) — exactly the
        # boundary-crossing staleness this cleanup removes.
        other = tmp_path / "elsewhere" / "checkout"
        p = _write_legacy(agents_dir, _generated_config(other))
        kiro_install.cleanup_legacy_composer_agent(agents_dir)
        assert not p.exists()

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda c: c.update(description="MY CUSTOM DESCRIPTION"),
            lambda c: c.update(tools=["read", "glob", "grep", "@sdpm", "shell"]),
            lambda c: c["mcpServers"]["sdpm"].update(timeout=999),
            lambda c: c["mcpServers"]["sdpm"].update(env={"FOO": "1"}),
            lambda c: c.update(useLegacyMcpJson=True),
            lambda c: c.update(model="my-model"),
        ],
        ids=["description", "tools", "timeout", "extra-mcp-field", "useLegacyMcpJson", "extra-field"],
    )
    def test_keeps_any_user_edit(self, agents_dir, mutate):
        cfg = _generated_config(REPO_ROOT)
        mutate(cfg)
        p = _write_legacy(agents_dir, cfg)
        kiro_install.cleanup_legacy_composer_agent(agents_dir)
        assert p.exists()

    def test_keeps_mismatched_prompt_and_mcp_roots(self, agents_dir, tmp_path):
        # prompt and MCP args must point at the SAME root to count as generated
        cfg = _generated_config(REPO_ROOT)
        cfg["prompt"] = f"file://{tmp_path}/other/personas/composer.md"
        p = _write_legacy(agents_dir, cfg)
        kiro_install.cleanup_legacy_composer_agent(agents_dir)
        assert p.exists()

    def test_keeps_malformed_null_mcp_server_without_crashing(self, agents_dir):
        cfg = _generated_config(REPO_ROOT)
        cfg["mcpServers"] = {"sdpm": None}
        p = _write_legacy(agents_dir, cfg)
        kiro_install.cleanup_legacy_composer_agent(agents_dir)  # must not raise
        assert p.exists()

    def test_keeps_unparseable_file(self, agents_dir):
        p = agents_dir / "sdpm-composer.json"
        p.write_text("{not json", encoding="utf-8")
        kiro_install.cleanup_legacy_composer_agent(agents_dir)
        assert p.exists()

    def test_noop_when_absent(self, agents_dir):
        kiro_install.cleanup_legacy_composer_agent(agents_dir)  # no raise
        assert list(agents_dir.iterdir()) == []


class TestInstallerShape:
    def test_render_composer_agent_is_gone(self):
        assert not hasattr(kiro_install, "render_composer_agent")

    def test_template_file_is_gone(self):
        assert not (_INSTALL_PY.parent / "sdpm-composer.json.tmpl").exists()
