"""Contract tests for the bundled styles in ``sdpm/references/examples/styles``.

A style is a rulebook + reference + gallery sample in one HTML file
(see ``sdpm/references/workflows/style.md``). These tests pin the parts of that
document other code depends on — ``apply_style`` reads ``--color-text``, the
build-time font-size lint reads ``--fs-*``, the Web UI splits on
``<div class="slide`` and shows the first slide as the thumbnail — plus the
skeleton (cover, rules, message & outline, patterns, closing), the component and pattern
vocabulary, the style's own density on every slide, a size budget and writing principles the style workflow promises to every reader.
"""

from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path

import pytest

from sdpm import api, tools
from sdpm.engine.checks.font_size import _FS_TOKEN_RE
from sdpm.knowledge.reference import BUNDLED_STYLES_DIR

BUNDLED = sorted(p for p in BUNDLED_STYLES_DIR.glob("*.html"))
EXPECTED_NAMES = {
    # orthodox tier — pick one of these when in doubt
    "report", "briefing", "aws-light", "aws-dark",
    # concept tier — chosen by look
    "neo-brutalist", "typographic", "signal", "racing",
    "bento", "newspaper", "swiss-poster", "duotone",
    # gradient tier — the gradient is a pointer, everything else is flat
    "prism-dark", "prism-light",
    # product-UI tier — the deck looks like the AWS Management Console
    "aws-console",
}

REQUIRED_TOKENS = ("--color-text", "--color-bg", "--fs-cover-title", "--fs-slide-title", "--fs-body")
PARTS = ("Cover", "Rules", "Message & Outline", "Patterns", "Closing")
REQUIRED_FRAMES = ("content", "divider", "closing")
REQUIRED_PATTERNS = ("comparison", "columns", "process", "metric", "table", "chart", "diagram")
# Every composer receives the whole file; the skeleton plus its icon symbols fits under this.
MAX_STYLE_CHARS = 44_000
# Component vocabulary (workflows/style.md): roles every style must state, and all roles
REQUIRED_ROLES = ("container", "selected", "takeaway", "numbered", "metric", "step", "connector", "tag", "table", "chart", "icon")
ALL_ROLES = REQUIRED_ROLES + (
    "list", "lead", "quote", "delta", "before-after", "progress", "phase", "milestone",
    "hub", "hierarchy", "axis", "brace", "marker", "legend", "media", "code",
)
COMPONENT_RE = re.compile(r"<!--\s*Component:\s*([a-z-]+)")
PATTERN_RE = re.compile(r"<!--\s*Pattern:\s*([a-z-]+)(.*?)-->", re.DOTALL)
FRAME_RE = re.compile(r"<!--\s*Frame:\s*([a-z-]+)")
DENSITY_RE = re.compile(r"<!--\s*Density:\s*(\d+)\s*-->")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
BRAND_WORDS = ("McKinsey", "BCG", "Bain", "Accenture", "Deloitte", "Apple", "TED", "Amazon", "AWS", "Google")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")
ROOT_RE = re.compile(r":root\s*\{(.*?)\}", re.DOTALL | re.IGNORECASE)
SLIDE_RE = re.compile(r'<div class="slide[\s"]')
EL_STYLE_RE = re.compile(r'class="[^"]*\bel\b[^"]*"[^>]*style="([^"]*)"')
SYMBOL_RE = re.compile(r'<symbol id="([\w./-]+)"[^>]*>(.*?)</symbol>', re.DOTALL)
USE_RE = re.compile(r'<use href="#([\w./-]+)"')
ASSETS_DIR = Path(__file__).resolve().parents[1] / "sdpm" / "assets"


def _root(html: str) -> str:
    blocks = ROOT_RE.findall(html)
    assert len(blocks) == 1, f"expected one :root block, found {len(blocks)}"
    return blocks[0]


def test_bundled_lineup_is_exactly_the_expected_styles() -> None:
    assert {p.stem for p in BUNDLED} == EXPECTED_NAMES


@pytest.mark.parametrize("path", BUNDLED, ids=lambda p: p.stem)
class TestStyleContract:
    def test_root_tokens(self, path: Path) -> None:
        root = _root(path.read_text(encoding="utf-8"))
        for tok in REQUIRED_TOKENS:
            assert re.search(re.escape(tok) + r"\s*:", root), f"{path.stem}: missing {tok}"
        assert len(_FS_TOKEN_RE.findall(root)) >= 5, f"{path.stem}: font-size lint needs --fs-* tokens"
        assert not re.search(r"--size-[\w-]+\s*:", root), f"{path.stem}: --size-* is invisible to the lint"

    def test_title_is_name_and_description(self, path: Path) -> None:
        m = re.search(r"<title>(.*?)</title>", path.read_text(encoding="utf-8"), re.DOTALL)
        assert m and " — " in m.group(1)
        name, desc = m.group(1).split(" — ", 1)
        assert name.strip().lower() == path.stem
        assert len(desc) >= 100, f"{path.stem}: description must state audience, purpose, decision, look"

    def test_skeleton(self, path: Path) -> None:
        html = path.read_text(encoding="utf-8")
        positions = [html.find(f"<!-- Part: {name} -->") for name in PARTS]
        assert all(pos >= 0 for pos in positions), f"{path.stem}: missing part markers {PARTS}"
        assert positions == sorted(positions), f"{path.stem}: parts out of order"
        # first slide is the cover — the gallery shows it as the thumbnail
        first = SLIDE_RE.search(html)
        assert first and positions[0] < first.start() < positions[1]

    def test_style_toc_sees_every_slide(self, path: Path) -> None:
        # apply_style returns style_toc and agents read the file by line range, so every
        # slide must open on its own line (a minified file collapses the TOC).
        html = path.read_text(encoding="utf-8")
        toc = [e for e in api.style_toc(html) if e["kind"] == "slide"]
        assert len(toc) == len(SLIDE_RE.findall(html)), f"{path.stem}: slides share a line"

    def test_frames_patterns_components(self, path: Path) -> None:
        html = path.read_text(encoding="utf-8")
        frames = set(FRAME_RE.findall(html))
        assert set(REQUIRED_FRAMES) <= frames, f"{path.stem}: frames missing {set(REQUIRED_FRAMES) - frames}"
        patterns = {name: body for name, body in PATTERN_RE.findall(html)}
        missing = [p for p in REQUIRED_PATTERNS if p not in patterns]
        assert not missing, f"{path.stem}: required patterns missing {missing}"
        for name, body in patterns.items():
            assert "regions:" in body and "components:" in body, f"{path.stem}: pattern {name} lacks regions/components"
        roles = COMPONENT_RE.findall(html)
        unknown = sorted(set(roles) - set(ALL_ROLES))
        assert not unknown, f"{path.stem}: component roles not in the vocabulary: {unknown}"
        missing_roles = [r for r in REQUIRED_ROLES if r not in roles]
        assert not missing_roles, f"{path.stem}: required roles without a Component line: {missing_roles}"

    def test_slides_obey_the_style_density(self, path: Path) -> None:
        # the file is the gallery sample and the composer's model: no slide may be denser
        # than the style allows its decks to be
        html = path.read_text(encoding="utf-8")
        m = DENSITY_RE.search(html)
        assert m, f"{path.stem}: no <!-- Density: N --> marker"
        limit = int(m.group(1))
        body = COMMENT_RE.sub("", html.split("<body", 1)[-1])
        slides = re.split(r'<div class="slide[\s"]', body)[1:]
        for i, slide in enumerate(slides, 1):
            text = _html.unescape(re.sub(r"<[^>]+>", " ", slide))
            words = len(re.findall(r"[\w%$€£¥+−-]+", text))
            assert words <= limit, f"{path.stem}: slide {i} shows {words} words > density {limit}"

    def test_icons_are_self_contained_assets(self, path: Path) -> None:
        # the gallery renders the file alone (iframe srcdoc): icons are inline <symbol>s whose
        # id is the search_assets name, so the slide JSON src is "assets:" + id
        html = path.read_text(encoding="utf-8")
        symbols = dict(SYMBOL_RE.findall(html))
        used = set(USE_RE.findall(html))
        assert used <= set(symbols), f"{path.stem}: <use> without a symbol: {sorted(used - set(symbols))}"
        assert not re.search(r'src="\.\./', html), f"{path.stem}: relative asset paths do not resolve in the gallery"
        diagram = html.split("<!-- Pattern: diagram", 1)[1].split('<div class="slide', 2)[1]
        declares_none = re.search(r"<!--\s*Component:\s*icon[^>]*—\s*none", html)
        assert declares_none or USE_RE.search(diagram) or "<svg" in diagram, f"{path.stem}: diagram pattern draws no icon"
        for sid, body in symbols.items():
            source, _, name = sid.partition("/")
            asset = ASSETS_DIR / source / f"{name}.svg"
            if not asset.parent.is_dir():
                continue  # catalog not downloaded (CI); names are still checked where it exists
            assert asset.is_file(), f"{path.stem}: symbol {sid} is not a search_assets name"
            first = re.search(r'd="([^"]{24})', body)
            assert first and first.group(1) in asset.read_text(encoding="utf-8"), f"{path.stem}: {sid} path not copied from the asset"

    def test_size_budget(self, path: Path) -> None:
        size = len(path.read_text(encoding="utf-8"))
        assert size <= MAX_STYLE_CHARS, f"{path.stem}: {size} chars > {MAX_STYLE_CHARS}; cut duplication, not rules"

    def test_html_mechanics(self, path: Path) -> None:
        html = path.read_text(encoding="utf-8")
        assert re.search(r"zoom:\s*0\.7", html), f"{path.stem}: body must set zoom: 0.7"
        assert not re.search(r"font-size\s*:\s*\d+px", html), f"{path.stem}: font sizes must be pt"
        for m in EL_STYLE_RE.finditer(html):
            props = {p.split(":")[0].strip() for p in m.group(1).split(";") if p.strip()}
            extra = props - {"left", "top", "width", "height"}
            assert not extra, f"{path.stem}: inline style on .el carries {sorted(extra)}"
        body = html.split("<body", 1)[-1]
        assert not EMOJI_RE.search(body), f"{path.stem}: emoji in body"

    def test_describes_by_design_not_brand(self, path: Path) -> None:
        html = path.read_text(encoding="utf-8")
        words = BRAND_WORDS
        if path.stem.startswith("aws-"):  # AWS-themed styles may name AWS — this is an AWS repository
            words = tuple(w for w in words if w not in ("Amazon", "AWS"))
        for word in words:
            assert not re.search(rf"\b{word}\b", html), f"{path.stem}: names '{word}'"
        assert not re.search(r"\bAI\b", html.split("<body", 1)[-1]), f"{path.stem}: defines itself against 'AI'"

    def test_apply_style_reads_the_style(self, path: Path, tmp_path: Path) -> None:
        r = tools.init_deck_workspace(str(tmp_path / "deck"))
        deck = Path(r.get("output_dir", str(tmp_path / "deck")))
        result = api.apply_style(deck, path.stem, "blank-light")
        deck_json = json.loads((deck / "deck.json").read_text())
        assert result["sources"]["defaultTextColor"] == "style --color-text"
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", deck_json["defaultTextColor"])
        # --color-bg is the deck ground: every slide without its own background gets it
        assert result["sources"]["defaultBackground"] == "style --color-bg"
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", deck_json["defaultBackground"])
        assert _FS_TOKEN_RE.findall((deck / "specs" / "art-direction.html").read_text())


def test_sample_deck_outline_parses_with_every_style(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "style-sample-deck"
    for path in BUNDLED:
        r = tools.init_deck_workspace(str(tmp_path / path.stem))
        deck = Path(r.get("output_dir", str(tmp_path / path.stem)))
        (deck / "specs" / "outline.md").write_text((fixture / "outline.md").read_text())
        api.apply_style(deck, path.stem, "blank-light")
        result = tools.check_specs(str(deck))
        assert result["ok"], f"{path.stem}: {result['errors']}"
        assert len(result["slugs"]) == 10
