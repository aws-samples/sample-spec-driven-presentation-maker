"""Auto spacing beyond plain CJK↔ASCII: quotes and apostrophes, <> brackets, non-ASCII
Latin letters, styled-segment and HTML boundaries, charts, and the properties that hold
for any text (applying twice adds nothing; styling and HTML markup do not change where
the spaces go)."""
import html as htmlmod
import json
import random

import pytest
from lxml import html as lxml_html
from pptx import Presentation

from sdpm.api import generate
from sdpm.engine.html.spacing import space_section
from sdpm.utils.text import normalize_spacing, parse_styled_text
from test_roundtrip import _make_deck


def _pptx(text: str) -> str:
    return "".join(s["text"] for s in parse_styled_text(text))


def _html(markup: str) -> str:
    section = lxml_html.fragment_fromstring(f"<section>{markup}</section>")
    space_section(section)
    return lxml_html.tostring(section, encoding="unicode", method="html")[len("<section>"):-len("</section>")]


@pytest.mark.parametrize("src", [
    "It's fine", "don't", "AWS What's New", "rock 'n' roll", "the 'best' option",
    'the "best" option', 'He said "hi".', '"alice", "bob"', '{"sub": "alice"}', "5'10\"",
    "`a` and `b`",
])
def test_english_text_is_unchanged(src):
    assert normalize_spacing(src) == src


@pytest.mark.parametrize("src, expected", [
    ('"AWS"の', '"AWS" の'),
    ('説明"AWS"です', '説明 "AWS" です'),
    ('"設計"を見る', '"設計" を見る'),
    ('`npm`を実行', '`npm` を実行'),
    ('「"AWS"」', '「"AWS"」'),
    ('説明 "AWS" です', '説明 "AWS" です'),
    ("Amazon's新機能", "Amazon's 新機能"),
    ("O'Reilly本", "O'Reilly 本"),
    ("it's「AWS」の", "it's「AWS」の"),
])
def test_quotes_take_a_space_only_toward_japanese(src, expected):
    assert normalize_spacing(src) == expected


@pytest.mark.parametrize("src, expected", [
    ("<ファイル名>.md", "<ファイル名>.md"),
    ("パスの<ファイル名>です", "パスの <ファイル名> です"),
    ("リポジトリ>", "リポジトリ>"),
])
def test_angle_brackets_are_brackets(src, expected):
    assert normalize_spacing(src) == expected


@pytest.mark.parametrize("src, expected", [
    ("Caféで", "Café で"),
    ("naïveな", "naïve な"),
    ("Cafe\u0301で", "Cafe\u0301 で"),
    ("日本Ñ", "日本 Ñ"),
    ("α版", "α版"),
])
def test_non_ascii_latin_letters_are_latin_text(src, expected):
    assert normalize_spacing(src) == expected


@pytest.mark.parametrize("src, expected", [
    ("{{bold:サーバー}})", "サーバー)"),
    ("({{bold:サーバー}}", "(サーバー"),
    ('"{{bold:AWS}}"の', '"AWS" の'),
    ("{{bold:AWS}}'s機能", "AWS's 機能"),
    ("{{link:https://example.com:AWS}}の", "AWS の"),
    ("詳細は{{link:https://example.com:ドキュメント}}", "詳細はドキュメント"),
    ("説明{{baseline=30000:1}}です", "説明1です"),
    ("H{{baseline=-25000:2}}Oの", "H2O の"),
])
def test_segment_boundaries_follow_the_plain_text_rules(src, expected):
    assert _pptx(src) == expected


@pytest.mark.parametrize("src, expected", [
    ("<p>説明<sup>1</sup>です</p>", "<p>説明<sup>1</sup>です</p>"),
    ("<p>AWS<sup>1</sup>の</p>", "<p>AWS<sup>1</sup>の</p>"),
    ("<p>H<sub>2</sub>Oの</p>", "<p>H<sub>2</sub>O の</p>"),
    ("<p><ruby>漢<rt>kan</rt></ruby>字</p>", "<p><ruby>漢<rt>kan</rt></ruby>字</p>"),
    ("<p>It's <b>AWS</b>'s</p>", "<p>It's <b>AWS</b>'s</p>"),
    ("<p><b>サーバー</b>)</p>", "<p><b>サーバー</b>)</p>"),
    ('<p>"<b>AWS</b>"の</p>', '<p>"<b>AWS</b>" の</p>'),
])
def test_html_boundaries_and_verbatim_runs(src, expected):
    assert _html(src) == expected


_ALPHABET = list("漢かカー、。・「」（）：") + list("aZ09 '\"`()[]<>.,:;!?/-&%$#@+=~") + ["é", "😀"]


def _random_texts(n=3000, seed=0):
    rng = random.Random(seed)
    for _ in range(n):
        yield "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(1, 12)))


def test_applying_twice_adds_nothing():
    for s in _random_texts():
        once = normalize_spacing(s)
        assert normalize_spacing(once) == once, s


def test_styling_and_html_markup_do_not_move_the_spaces():
    rng = random.Random(1)
    for s in _random_texts(seed=2):
        k = rng.randint(1, len(s))
        a, b = s[:k], s[k:]
        if not b:
            continue
        plain = normalize_spacing(s)
        assert _pptx("{{bold:" + a + "}}" + b) == plain, (a, b)
        html = lxml_html.fromstring(_html(f"<p><b>{htmlmod.escape(a)}</b>{htmlmod.escape(b)}</p>")).text_content()
        assert html == plain, (a, b)


def _chart_texts(tmp_path, auto_spacing):
    deck = _make_deck(tmp_path, [{
        "type": "chart", "x": 100, "y": 100, "width": 800, "height": 500, "chartType": "bar",
        "title": "AWSの利用料", "categories": ["東京Region", "大阪Region", 2026],
        "series": [{"name": "EC2の費用", "values": [1, 2, 3]}],
    }])
    meta = json.loads((deck / "deck.json").read_text())
    meta["autoSpacing"] = auto_spacing
    (deck / "deck.json").write_text(json.dumps(meta))
    out = tmp_path / "out.pptx"
    generate(deck, output_path=out)
    chart = next(s for s in Presentation(str(out)).slides[0].shapes if s.has_chart).chart
    return (chart.chart_title.text_frame.text, list(chart.plots[0].categories),
            [s.name for s in chart.series])


def test_chart_text_is_spaced(tmp_path):
    title, categories, series = _chart_texts(tmp_path, True)
    assert title == "AWS の利用料"
    assert categories[:2] == ["東京 Region", "大阪 Region"]
    assert series == ["EC2 の費用"]


def test_chart_text_is_kept_when_auto_spacing_is_off(tmp_path):
    title, categories, series = _chart_texts(tmp_path, False)
    assert title == "AWSの利用料"
    assert categories[:2] == ["東京Region", "大阪Region"]
    assert series == ["EC2の費用"]
