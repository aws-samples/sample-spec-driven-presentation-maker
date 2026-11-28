# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""What this SPEC deliberately did not build, asserted so it cannot creep back.

The superseded design made "structure" and "writing" resource types of their own, each with
a directory, an environment variable, a listing tool, a default and a copy written into the
deck. One collection classified by role tags replaces all of it, and nothing here may
reappear by accident — a second way to reach a guide is how the tool surface grew last time.
"""

import inspect
import os
import re
import tempfile
from pathlib import Path

import pytest

from sdpm import entry, tools
from sdpm.config import REFERENCES_DIR, _DEFAULTS
from sdpm.knowledge.reference import always_guides, guides_listing, select_guides

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("sdpm/sdpm", "servers", "shared", "api", "agent", "scripts")
WEB_UI = ROOT / "web-ui" / "src"

# Symbols, state keys and environment variables of the design that was dropped.
FORBIDDEN = (
    "apply_guides",
    "set_default",
    "list_structures",
    "list_writings",
    "SDPM_STRUCTURES_DIR",
    "SDPM_WRITINGS_DIR",
    "default_structure",
    "default_writing",
    "pinned_guides",
    "guide_pins",
    "get_guide_pins",
    "put_guide_pins",
    "default_guide",
)


def source_files() -> list[Path]:
    files: list[Path] = []
    for directory in SOURCE_DIRS:
        files.extend(p for p in (ROOT / directory).rglob("*.py") if "__pycache__" not in p.parts)
    files.extend(p for p in WEB_UI.rglob("*.ts") if "node_modules" not in p.parts)
    return files


@pytest.fixture(scope="module")
def sources() -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8") for p in source_files()}


class TestNoSecondResourceType:
    @pytest.mark.parametrize("symbol", FORBIDDEN)
    def test_the_symbol_exists_nowhere(self, symbol: str, sources) -> None:
        hits = [str(p.relative_to(ROOT)) for p, text in sources.items() if symbol in text]
        assert hits == [], (symbol, hits)

    def test_no_structures_or_writings_directory_is_resolved(self, sources) -> None:
        for path, text in sources.items():
            for word in ("structures", "writings"):
                assert f'"{word}"' not in text, (path, word)

    @pytest.mark.parametrize("name", ["list_structures", "list_writings", "apply_guides", "set_default"])
    def test_the_contract_exposes_no_such_tool(self, name: str) -> None:
        assert not hasattr(tools, name)

    def test_the_two_guide_tools_are_the_whole_surface(self) -> None:
        guide_tools = [n for n in dir(tools) if "guide" in n and not n.startswith("_")]
        assert sorted(guide_tools) == ["list_guides", "read_guides"]


class TestNoPinsAndNoDefaults:
    def test_config_gains_no_key(self) -> None:
        # The bundled guides are not surfaced in config.json, and no guide default lives there.
        assert not [k for k in _DEFAULTS if "guide" in k]

    def test_no_guide_pin_endpoint(self) -> None:
        api = (ROOT / "api" / "index.py").read_text(encoding="utf-8")
        assert "/guides/pin" not in api
        assert "/styles/pin" in api  # styles keep theirs

    def test_the_web_ui_has_no_guide_pin_route(self) -> None:
        assert not (WEB_UI / "app" / "api" / "guides" / "pin").exists()


class TestRoleDocumentsAreNotGuides:
    FIVE = ("composer-html.md", "composer.md", "orchestrator.md", "style.md", "translate.md")

    def test_the_workflows_directory_holds_exactly_five_files(self) -> None:
        assert sorted(p.name for p in (REFERENCES_DIR / "workflows").iterdir()) == list(self.FIVE)

    def test_a_role_document_is_read_by_name_from_that_directory(self) -> None:
        for role in ("orchestrator", "composer", "composer-html", "style", "translate"):
            assert entry._workflow(role) == (REFERENCES_DIR / "workflows" / f"{role}.md").read_text(encoding="utf-8")

    def test_no_role_document_is_in_the_collection(self) -> None:
        listed = {g["name"] for g in guides_listing(entry.guide_collection())["guides"]}
        assert listed.isdisjoint({p.stem for p in (REFERENCES_DIR / "workflows").iterdir()} - {"style"})
        # `style` is a tag, never a guide name.
        assert "style" not in listed


class TestNoLanguageInSelection:
    """REQ-3.6 / REQ-9.10: selection is by tag alone."""

    @pytest.mark.parametrize("func", [select_guides, always_guides, guides_listing])
    def test_no_selection_signature_takes_a_language(self, func) -> None:
        assert "lang" not in str(inspect.signature(func)).lower()

    def test_no_caller_passes_a_language_into_selection(self, sources) -> None:
        call = re.compile(r"(select_guides|always_guides|guides_listing)\(([^)]*)\)")
        for path, text in sources.items():
            for match in call.finditer(text):
                assert "lang" not in match.group(2).lower(), (path, match.group(0))

    def test_the_payload_builder_takes_tags_and_a_collection(self) -> None:
        assert list(inspect.signature(entry.guide_payload).parameters) == ["collection", "tags"]


class TestNoGuideIsCopiedIntoADeck:
    """REQ-1.8 / REQ-9.11: a resolved guide never lands in a deck."""

    BASE_SPECS = {"brief.md", "outline.md"}

    @pytest.fixture
    def deck(self, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setenv("SDPM_OUTPUT_DIR", tempfile.mkdtemp())
        return Path(tools.init_deck_workspace("prohibitions")["output_dir"])

    def test_initialization_writes_only_the_two_spec_files(self, deck: Path) -> None:
        assert {p.name for p in (deck / "specs").iterdir()} == self.BASE_SPECS

    def test_apply_style_adds_only_the_art_direction(self, deck: Path) -> None:
        tools.apply_style(str(deck), style="typographic", template="blank-dark")
        assert {p.name for p in (deck / "specs").iterdir()} == self.BASE_SPECS | {"art-direction.html"}

    def test_no_start_call_writes_a_guide_into_the_deck(self, deck: Path) -> None:
        tools.apply_style(str(deck), style="typographic", template="blank-dark")
        before = {p.name for p in (deck / "specs").iterdir()}
        tools.start_presentation()
        tools.start_composing(str(deck), ["intro"])
        tools.start_composing(str(deck), ["intro"], mode="html")
        tools.start_style()
        assert {p.name for p in (deck / "specs").iterdir()} == before

    def test_neither_structure_md_nor_writing_md_is_ever_created(self, deck: Path) -> None:
        tools.apply_style(str(deck), style="typographic", template="blank-dark")
        tools.start_presentation()
        tools.start_composing(str(deck), ["intro"])
        for name in ("structure.md", "writing.md"):
            assert not (deck / "specs" / name).exists()
            assert not (deck / name).exists()

    def test_the_user_guides_directory_is_outside_every_deck(self, monkeypatch, tmp_path) -> None:
        from sdpm.api import get_guides_dirs

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        monkeypatch.delenv("SDPM_GUIDES_DIR", raising=False)
        assert get_guides_dirs()[0] == tmp_path / "sdpm" / "guides"
        assert "decks" not in str(get_guides_dirs()[0])


class TestTheEnvironmentVariableIsTheOnlyOverride:
    def test_only_sdpm_guides_dir_is_read(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from sdpm.api import get_guides_dirs

        for name in ("SDPM_STRUCTURES_DIR", "SDPM_WRITINGS_DIR"):
            monkeypatch.setenv(name, str(tmp_path / "nope"))
        monkeypatch.setenv("SDPM_GUIDES_DIR", str(tmp_path / "yes"))
        dirs = get_guides_dirs()
        assert dirs[0] == tmp_path / "yes"
        assert all("nope" not in str(d) for d in dirs)

    def test_nothing_in_the_environment_names_a_default_guide(self) -> None:
        assert not [k for k in os.environ if "SDPM" in k and "DEFAULT" in k.upper()]
