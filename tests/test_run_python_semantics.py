# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Semantics contract tests for run_python — Local and Remote must agree.

The contract (decided 2026-08-01, see the run-python-unified-semantics SPEC):

1. File writes ALWAYS persist. There is no "unsaved" state and no flag
   that gates persistence.
2. The PPTX artifact rebuilds automatically whenever build-relevant files
   changed (deck.json / slides/ / includes/ / specs/outline.md).
3. ``measure_slides`` is the only trigger for the expensive verification
   pass (render + measure + preview).
4. The legacy ``save`` argument is accepted but ignored (deprecation note
   in the result), so older callers keep working.

These tests pin the semantics so an adapter cannot silently diverge again
(the v0.5.1 cloud E2E regression was exactly such a divergence).
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_root = Path(__file__).resolve().parent.parent
_local = str(_root / "servers" / "local")
if _local not in sys.path:
    sys.path.insert(0, _local)

import sandbox_tools  # noqa: E402  (servers/local)


# ---------------------------------------------------------------------------
# Local: _build_snapshot change detection
# ---------------------------------------------------------------------------


@pytest.fixture()
def deck_dir(tmp_path: Path) -> Path:
    (tmp_path / "slides").mkdir()
    (tmp_path / "specs").mkdir()
    (tmp_path / "includes").mkdir()
    (tmp_path / "deck.json").write_text('{"template": "t.pptx"}')
    (tmp_path / "specs" / "outline.md").write_text("- [title] Hello\n")
    (tmp_path / "slides" / "title.json").write_text('{"elements": []}')
    return tmp_path


class TestBuildSnapshot:
    def test_detects_slide_change(self, deck_dir: Path):
        before = sandbox_tools._build_snapshot(deck_dir)
        p = deck_dir / "slides" / "title.json"
        p.write_text('{"elements": [{"type": "textbox"}]}')
        assert sandbox_tools._build_snapshot(deck_dir) != before

    def test_detects_new_slide(self, deck_dir: Path):
        before = sandbox_tools._build_snapshot(deck_dir)
        (deck_dir / "slides" / "new.json").write_text("{}")
        assert sandbox_tools._build_snapshot(deck_dir) != before

    def test_detects_outline_change(self, deck_dir: Path):
        before = sandbox_tools._build_snapshot(deck_dir)
        (deck_dir / "specs" / "outline.md").write_text("- [title] Changed\n")
        assert sandbox_tools._build_snapshot(deck_dir) != before

    def test_ignores_non_build_files(self, deck_dir: Path):
        before = sandbox_tools._build_snapshot(deck_dir)
        (deck_dir / "specs" / "brief.md").write_text("# Brief\n")
        (deck_dir / "output.pptx").write_bytes(b"x")
        assert sandbox_tools._build_snapshot(deck_dir) == before


# ---------------------------------------------------------------------------
# Local: run_python persistence & build semantics
# ---------------------------------------------------------------------------


class TestLocalRunPython:
    def _patch_generate(self, monkeypatch):
        calls: list[dict] = []

        def fake_generate(json_path=None, output_path=None, **kw):
            calls.append({"json_path": json_path, "output_path": output_path, **kw})
            Path(output_path).write_bytes(b"pptx")
            return {"output_path": str(output_path), "warnings": [], "errors": {}}

        import sdpm.api
        monkeypatch.setattr(sdpm.api, "generate", fake_generate)
        return calls

    def test_write_persists_and_triggers_build_without_any_flag(
        self, deck_dir: Path, monkeypatch
    ):
        calls = self._patch_generate(monkeypatch)
        out = json.loads(sandbox_tools.run_python(
            purpose="write brief-independent slide",
            code='write_json("slides/added.json", {"elements": []})',
            deck_id=str(deck_dir),
        ))
        # Persistence is unconditional
        assert (deck_dir / "slides" / "added.json").exists()
        # Build followed the change automatically
        assert len(calls) == 1
        assert "pptx" in out

    def test_readonly_run_does_not_build(self, deck_dir: Path, monkeypatch):
        calls = self._patch_generate(monkeypatch)
        out = json.loads(sandbox_tools.run_python(
            purpose="read deck",
            code='print(read_json("deck.json")["template"])',
            deck_id=str(deck_dir),
        ))
        assert "t.pptx" in out["output"]
        assert calls == []
        assert "pptx" not in out

    def test_non_build_write_persists_without_build(self, deck_dir: Path, monkeypatch):
        calls = self._patch_generate(monkeypatch)
        json.loads(sandbox_tools.run_python(
            purpose="write brief",
            code='write_text("specs/brief.md", "# Brief")',
            deck_id=str(deck_dir),
        ))
        assert (deck_dir / "specs" / "brief.md").read_text() == "# Brief"
        assert calls == []

    def test_save_flag_is_ignored_with_deprecation_note(
        self, deck_dir: Path, monkeypatch
    ):
        calls = self._patch_generate(monkeypatch)
        out = json.loads(sandbox_tools.run_python(
            purpose="read only with legacy save flag",
            code='print("hi")',
            deck_id=str(deck_dir),
            save=True,
        ))
        # save no longer forces a build (nothing changed)
        assert calls == []
        assert "deprecated" in out


# ---------------------------------------------------------------------------
# Remote: diff-based always-persist write-back
# ---------------------------------------------------------------------------

from tools import sandbox as remote_sandbox  # noqa: E402  (servers/remote via conftest)


class _FakeStorage:
    def __init__(self):
        self.uploads: dict[str, bytes] = {}

    def upload_file(self, key: str, data: bytes, content_type: str = ""):
        self.uploads[key] = data


class TestRemoteSaveWorkspace:
    def _run(self, sandbox_files: dict[str, str], baseline: dict[str, str]):
        client = MagicMock()
        storage = _FakeStorage()
        # _save_deck_workspace reads the sandbox via _collect_stream(response)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(remote_sandbox, "_collect_stream",
                       lambda _resp: json.dumps(sandbox_files))
            warnings, lint, changed = remote_sandbox._save_deck_workspace(
                client, "session", storage, "deckX", baseline=baseline,
            )
        return storage, changed

    def test_only_changed_files_written_back(self):
        baseline = {"specs/brief.md": "old", "deck.json": "{}"}
        sandbox_files = {
            "specs/brief.md": "new",       # changed
            "deck.json": "{}",             # unchanged
            "specs/notes.md": "created",   # new
        }
        storage, changed = self._run(sandbox_files, baseline)
        assert changed == ["specs/brief.md", "specs/notes.md"]
        assert set(storage.uploads) == {
            "decks/deckX/specs/brief.md",
            "decks/deckX/specs/notes.md",
        }

    def test_unchanged_workspace_writes_nothing(self):
        baseline = {"specs/brief.md": "same"}
        storage, changed = self._run({"specs/brief.md": "same"}, baseline)
        assert changed == []
        assert storage.uploads == {}


class TestRemoteContractShape:
    def test_execute_in_sandbox_has_no_save_gate(self):
        import inspect
        sig = inspect.signature(remote_sandbox.execute_in_sandbox)
        assert "save" not in sig.parameters, (
            "execute_in_sandbox must not gate persistence on a save flag"
        )
        assert sig.parameters["persist_writes"].default is True

    def test_remote_run_python_still_accepts_save_for_compat(self):
        # The MCP-facing tool keeps the parameter (deprecated, ignored) so
        # existing callers don't break. Read by explicit path — both servers
        # ship a server.py, so module resolution is ambiguous here.
        src = (_root / "servers" / "remote" / "server.py").read_text(encoding="utf-8")
        assert "save: bool = False" in src
        assert "'save' is ignored" in src
