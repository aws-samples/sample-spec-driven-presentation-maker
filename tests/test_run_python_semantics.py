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
4. The legacy ``save`` argument is removed from every public surface.
5. Committed ``attachments/imports/`` bundles are readable but never writable or persisted.

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

    def test_repr_and_dunder_name_are_available(self, deck_dir: Path, monkeypatch):
        self._patch_generate(monkeypatch)
        out = json.loads(sandbox_tools.run_python(
            purpose="use repr and __name__",
            code='print(repr("a\\x0bb")); print(__name__)',
            deck_id=str(deck_dir),
        ))
        assert "'a\\x0bb'" in out["output"]
        assert "__main__" in out["output"]


    def test_committed_import_bundle_is_read_only(self, deck_dir: Path, monkeypatch):
        calls = self._patch_generate(monkeypatch)
        bundle_file = deck_dir / "attachments" / "imports" / "key" / "deck" / "deck.json"
        bundle_file.parent.mkdir(parents=True)
        bundle_file.write_text('{"name":"original"}')

        out = json.loads(sandbox_tools.run_python(
            purpose="attempt bundle mutation",
            code='write_json("attachments/imports/key/deck/deck.json", {"name": "changed"})',
            deck_id=str(deck_dir),
        ))

        assert "read-only" in out["output"]
        assert json.loads(bundle_file.read_text()) == {"name": "original"}
        assert calls == []

class TestLocalLintRewriteGuard:
    """Regression: the lint pass must not rewrite files whose sanitized
    content is unchanged — unconditional rewrites bumped mtimes on every
    call and rebuilt output.pptx even for read-only runs (found during the
    local compose one-pass check)."""

    _patch_generate = TestLocalRunPython._patch_generate

    def test_diagnostics_only_no_rewrite_no_rebuild(
        self, deck_dir: Path, monkeypatch
    ):
        # "missing-type" produces a diagnostic but sanitize changes nothing
        bad = deck_dir / "slides" / "bad.json"
        bad.write_text('{"elements": [{"x": 1}]}')
        mtime = bad.stat().st_mtime_ns
        calls = self._patch_generate(monkeypatch)

        out = json.loads(sandbox_tools.run_python(
            purpose="read only",
            code='print("noop")',
            deck_id=str(deck_dir),
        ))
        # Diagnostics are reported...
        assert out.get("errors", {}).get("lintDiagnostics")
        # ...but the file is untouched and no build was triggered
        assert bad.stat().st_mtime_ns == mtime
        assert calls == []

    def test_sanitization_rewrites_and_rebuilds_once(
        self, deck_dir: Path, monkeypatch
    ):
        # _spAutoFit is deprecated — sanitize removes it (content change)
        auto = deck_dir / "slides" / "auto.json"
        auto.write_text(json.dumps({"elements": [
            {"type": "textbox", "text": "t", "x": 1, "y": 1, "w": 10, "h": 10,
             "_spAutoFit": True},
        ]}))
        calls = self._patch_generate(monkeypatch)

        json.loads(sandbox_tools.run_python(
            purpose="read only", code='print("noop")', deck_id=str(deck_dir)))
        # Sanitization changed the file → rewrite + rebuild
        assert "_spAutoFit" not in auto.read_text()
        assert len(calls) == 1

        # Second read-only run: content now stable → no further rebuild
        json.loads(sandbox_tools.run_python(
            purpose="read only", code='print("noop")', deck_id=str(deck_dir)))
        assert len(calls) == 1


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

    def test_diagnostics_only_slide_not_reserialized(self):
        # A changed slide with diagnostics but no sanitize effect must be
        # written back byte-identical (pretty formatting preserved) —
        # mirrors the Local lint rewrite guard.
        pretty = '{\n  "elements": [\n    {\n      "x": 1\n    }\n  ]\n}'
        storage, changed = self._run(
            {"slides/bad.json": pretty}, {"slides/bad.json": "old"})
        assert changed == ["slides/bad.json"]
        assert storage.uploads["decks/deckX/slides/bad.json"] == pretty.encode()

    def test_committed_import_bundle_is_never_written_back(self):
        immutable = "attachments/imports/key/deck/deck.json"
        storage, changed = self._run(
            {immutable: '{"name":"changed"}', "specs/brief.md": "new"},
            {immutable: '{"name":"original"}', "specs/brief.md": "old"},
        )
        assert changed == ["specs/brief.md"]
        assert f"decks/deckX/{immutable}" not in storage.uploads


class TestRemoteContractShape:
    def test_execute_in_sandbox_has_no_save_gate(self):
        import inspect
        sig = inspect.signature(remote_sandbox.execute_in_sandbox)
        assert "save" not in sig.parameters, (
            "execute_in_sandbox must not gate persistence on a save flag"
        )
        assert sig.parameters["persist_writes"].default is True


# ---------------------------------------------------------------------------
# Remote: staged files must not shadow the persisted workspace
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Remote: run_python top-level post-processing contract (4-pattern matrix)
# ---------------------------------------------------------------------------

import os  # noqa: E402

os.environ.setdefault("DECKS_TABLE", "test-table")
os.environ.setdefault("PPTX_BUCKET", "test-pptx")
os.environ.setdefault("RESOURCE_BUCKET", "test-resource")

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "remote_server_under_test", _root / "servers" / "remote" / "server.py",
)
remote_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote_server)


class TestPostProcessingPlan:
    """The contract matrix, as a pure decision table."""

    @pytest.mark.parametrize("changed,measure,expected", [
        (False, None, {"build": False, "artifact": False, "verify": False}),
        (True, None, {"build": True, "artifact": True, "verify": False}),
        (False, ["a"], {"build": True, "artifact": False, "verify": True}),
        (True, ["a"], {"build": True, "artifact": True, "verify": True}),
    ])
    def test_matrix(self, changed, measure, expected):
        assert remote_server._post_processing_plan(changed, measure) == expected

    def test_build_relevant_paths(self):
        assert remote_server._build_relevant("deck.json")
        assert remote_server._build_relevant("slides/title.json")
        assert remote_server._build_relevant("includes/code.json")
        assert remote_server._build_relevant("specs/outline.md")
        assert not remote_server._build_relevant("specs/brief.md")
        assert not remote_server._build_relevant("attachments/x/data.csv")


class _ArtifactStorage(_FakeStorage):
    def __init__(self):
        super().__init__()
        self.deck_updates: list[dict] = []
        self.pptx_bucket = "test-pptx"
        self._s3 = MagicMock()
        self.fail_update = False
        self.previous_pptx_key: str | None = None

    def update_deck(self, deck_id, user_id, updates):
        if self.fail_update:
            raise RuntimeError("DynamoDB down")
        self.deck_updates.append(updates)
        # UPDATED_OLD semantics: previous values of the updated attributes
        return {"pptxS3Key": self.previous_pptx_key} if self.previous_pptx_key else {}

    def list_files(self, prefix="", bucket=""):
        return []


@pytest.fixture()
def remote_rig(monkeypatch, tmp_path):
    """Monkeypatched harness to exercise run_python's real branch wiring."""
    calls = {"prepare": 0, "build": 0, "measure": 0, "export_svg": 0}
    storage = _ArtifactStorage()

    def fake_execute(code, storage, region, deck_id=None,
                     persist_writes=True, files=None):
        return ("ok", [], [], fake_execute.changed_paths)
    fake_execute.changed_paths = []

    def fake_prepare(deck_id, user_id, storage):
        calls["prepare"] += 1
        return tmp_path, [{"id": "a"}], {}

    def fake_build(tmpdir, slides, build_kwargs):
        calls["build"] += 1
        p = tmp_path / "out.pptx"
        p.write_bytes(b"pptx")
        return p, []

    def fake_measure(tmpdir, pptx_path, page_numbers, page_to_slug=None):
        calls["measure"] += 1
        return "{}"

    def fake_export_svg(tmpdir, pptx_path):
        calls["export_svg"] += 1
        return tmp_path / "measure.svg"  # never created → compose skipped

    import tools.generate as gen_mod
    monkeypatch.setattr(gen_mod, "_prepare_workspace", fake_prepare)
    monkeypatch.setattr(gen_mod, "generate_previews",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no lo")))
    monkeypatch.setattr(remote_server, "_build_pptx", fake_build)
    monkeypatch.setattr(remote_server, "_run_measure", fake_measure)
    monkeypatch.setattr(remote_server, "_export_svg", fake_export_svg)
    monkeypatch.setattr(remote_server, "_storage", storage)
    monkeypatch.setattr(remote_server, "_check_deck_access", lambda *a, **k: None)
    monkeypatch.setattr(remote_server, "_get_user_id", lambda: "user1")
    monkeypatch.setattr(remote_server.sandbox_mod, "execute_in_sandbox", fake_execute)
    return fake_execute, storage, calls


class TestRemoteRunPythonBranching:
    """Exercise the REAL run_python wiring for the 4-pattern contract matrix."""

    def _run(self, measure_slides=None):
        return json.loads(remote_server.run_python(
            purpose="t", code="print(1)", deck_id="d1",
            measure_slides=measure_slides,
        ))

    def test_no_change_no_measure_does_nothing(self, remote_rig):
        fake_execute, storage, calls = remote_rig
        fake_execute.changed_paths = []
        out = self._run()
        assert calls == {"prepare": 0, "build": 0, "measure": 0, "export_svg": 0}
        assert storage.uploads == {} and "measure" not in out

    def test_change_without_measure_builds_artifact_only(self, remote_rig):
        fake_execute, storage, calls = remote_rig
        fake_execute.changed_paths = ["slides/a.json"]
        out = self._run()
        assert calls["build"] == 1
        # Cheap path only — no render, no measure, no measure-error noise
        assert calls["measure"] == 0 and calls["export_svg"] == 0
        assert "measure" not in out
        # Artifact refreshed
        assert any(k.startswith("pptx/d1/") for k in storage.uploads)
        assert storage.deck_updates and "pptxS3Key" in storage.deck_updates[0]

    def test_measure_without_change_verifies_only(self, remote_rig):
        fake_execute, storage, calls = remote_rig
        fake_execute.changed_paths = ["specs/brief.md"]  # not build-relevant
        out = self._run(measure_slides=["a"])
        assert calls["build"] == 1 and calls["measure"] == 1
        assert "measure" in out
        # No artifact refresh without a build-relevant change
        assert not any(k.startswith("pptx/d1/") for k in storage.uploads)

    def test_change_with_measure_does_both(self, remote_rig):
        fake_execute, storage, calls = remote_rig
        fake_execute.changed_paths = ["slides/a.json"]
        out = self._run(measure_slides=["a"])
        assert calls["build"] == 1 and calls["measure"] == 1
        assert "measure" in out
        assert any(k.startswith("pptx/d1/") for k in storage.uploads)

    def test_artifact_failure_surfaces_and_compensates(self, remote_rig):
        fake_execute, storage, calls = remote_rig
        fake_execute.changed_paths = ["slides/a.json"]
        storage.fail_update = True
        out = self._run()
        assert "pptx_error" in out
        # The orphaned upload is deleted (best effort)
        assert storage._s3.delete_object.called

    def test_superseded_artifact_deleted_after_refresh(self, remote_rig):
        fake_execute, storage, calls = remote_rig
        fake_execute.changed_paths = ["slides/a.json"]
        storage.previous_pptx_key = "pptx/d1/old-artifact.pptx"
        out = self._run()
        assert "pptx_error" not in out
        # Auto-refresh must not accumulate orphaned PPTX objects
        storage._s3.delete_object.assert_called_once_with(
            Bucket="test-pptx", Key="pptx/d1/old-artifact.pptx")

    def test_first_artifact_deletes_nothing(self, remote_rig):
        fake_execute, storage, calls = remote_rig
        fake_execute.changed_paths = ["slides/a.json"]
        storage.previous_pptx_key = None
        self._run()
        assert not storage._s3.delete_object.called
