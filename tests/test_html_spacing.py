"""CJK↔Latin auto spacing for HTML slides (sdpm.engine.html.spacing)."""
import pytest
from lxml import html as lxml_html

from sdpm.engine.html.spacing import space_section
from sdpm.utils.text import parse_styled_text

from test_html_assemble import _assemble, _make_deck


def _spaced(markup: str) -> str:
    section = lxml_html.fragment_fromstring(f"<section>{markup}</section>")
    space_section(section)
    return lxml_html.tostring(section, encoding="unicode", method="html")[len("<section>"):-len("</section>")]


@pytest.mark.parametrize("src, expected", [
    ("<p>AWSのLambdaで、DBを3台</p>", "<p>AWS の Lambda で、DB を 3 台</p>"),
    ("<p><strong>AWS</strong>の新機能</p>", "<p><strong>AWS </strong>の新機能</p>"),
    ("<p>新しい<span>Lambda</span>関数</p>", "<p>新しい <span>Lambda </span>関数</p>"),
    ("<p><b>東京</b><i>Region</i></p>", "<p><b>東京 </b><i>Region</i></p>"),
    ("<p><strong>AWS</strong>、<em>S3</em>。</p>", "<p><strong>AWS</strong>、<em>S3</em>。</p>"),
])
def test_text_and_inline_boundaries_match_pptx(src, expected):
    assert _spaced(src) == expected


def test_matches_the_pptx_styled_text_result():
    pptx = "".join(s["text"] for s in parse_styled_text("{{bold:AWS}}の新機能と{{#FF9900:Lambda}}関数"))
    html = lxml_html.fromstring(_spaced("<p><strong>AWS</strong>の新機能と<span>Lambda</span>関数</p>")).text_content()
    assert html == pptx


@pytest.mark.parametrize("src", [
    "<pre>echo 日本語abc</pre>",
    "<p><code>npm</code>を実行</p>",
    "<p>押す<kbd>Ctrl</kbd></p>",
    '<svg viewbox="0 0 10 10"><text>図A</text></svg>',
    "<style>.a::after{content:'日本語a'}</style>",
    '<p title="属性abc" data-x="値1">文</p>',
])
def test_verbatim_elements_and_attributes_are_unchanged(src):
    assert _spaced(src) == src


@pytest.mark.parametrize("src", [
    "<div>AWS</div><div>の</div>",
    "<p>AWS<br>の</p>",
    "<li>AWS</li><li>日本</li>",
])
def test_runs_stop_at_blocks_and_breaks(src):
    assert _spaced(src) == src


def test_comments_are_skipped_but_their_tail_is_text():
    assert _spaced("<p><!-- 注記a -->AWSの</p>") == "<p><!-- 注記a -->AWS の</p>"


def test_speaker_notes_are_spaced():
    assert _spaced('<aside class="notes">AWSの説明です</aside>') == '<aside class="notes">AWS の説明です</aside>'


def test_assemble_spaces_output_unless_auto_spacing_is_off(tmp_path):
    deck = _make_deck(tmp_path)
    slides = {"s": '<section data-layout="Blank"><p>AWSの<strong>Lambda</strong>関数</p></section>'}
    on = _assemble(deck, slides=slides)
    assert "<p>AWS の <strong>Lambda </strong>関数</p>" in on.html
    off = _assemble(deck, slides=slides, auto_spacing=False)
    assert "<p>AWSの<strong>Lambda</strong>関数</p>" in off.html
