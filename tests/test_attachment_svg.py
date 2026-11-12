# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SVG content checks of enforce_content_limits: what an attached SVG may contain."""

from __future__ import annotations

import pytest

from sdpm.tools.attachment.errors import SourceValidationError
from sdpm.tools.attachment.source import enforce_content_limits

_NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'


def _check(tmp_path, body: str, *, wrap: bool = True) -> None:
    svg = tmp_path / "x.svg"
    svg.write_text(f"<svg {_NS}>{body}</svg>" if wrap else body, encoding="utf-8")
    enforce_content_limits(svg, "image/svg+xml")


@pytest.mark.parametrize("body", [
    '<style>@import "https://example.invalid/a.css";</style>',
    "<style>rect{fill:url(https://example.invalid/p.svg#g)}</style><rect/>",
    "<style>rect{background:image-set(\"https://example.invalid/t.png\" 1x)}</style>",
    '<rect style="fill:url(https://example.invalid/p.svg#g)"/>',
    '<rect fill="url(https://example.invalid/p.svg#g)"/>',
    '<rect stroke="url(\'//example.invalid/p.svg#g\')"/>',
    '<rect filter="url(data:image/svg+xml;base64,AAAA)"/>',
    '<rect fill="&#117;rl(https://example.invalid/p.svg#g)"/>',
    r"<style>rect{fill:\75rl(https://example.invalid/p.svg#g)}</style>",
    '<image href="&#104;ttps://example.invalid/a.png"/>',
    '<image href="data:image/svg+xml;base64,PHN2Zy8+"/>',
    '<image xlink:href=" DATA:image/SVG+xml,%3Csvg/%3E"/>',
    '<defs><g id="s"/></defs><use href="data:image/png;base64,iVBORw0KGgo=#s"/>',
    '<a href="data:image/png;base64,iVBORw0KGgo="><text>x</text></a>',
], ids=["import", "style-url", "style-image-set", "style-attr", "fill-attr", "stroke-attr",
        "data-url", "entity-encoded", "css-escape", "entity-href",
        "nested-svg-image", "nested-svg-xlink", "data-url-use", "data-url-link"])
def test_references_outside_the_document_are_rejected(tmp_path, body):
    with pytest.raises(SourceValidationError, match="external resource"):
        _check(tmp_path, body)


@pytest.mark.parametrize("body", [
    '<a href="#x"><set attributeName="href" to="#y"/><text>x</text></a>',
    '<a xlink:href="#x"><animate attributeName="xlink:href" values="#y;#z"/></a>',
    '<rect><set attributeName="onclick" to="x"/></rect>',
    '<g><animateTransform attributeName="href" type="rotate" from="0" to="1"/></g>',
], ids=["set-href", "animate-xlink-href", "set-event", "animate-transform-href"])
def test_animation_of_links_and_handlers_is_rejected(tmp_path, body):
    with pytest.raises(SourceValidationError, match="active content"):
        _check(tmp_path, body)


def test_animated_values_follow_the_reference_rules(tmp_path):
    with pytest.raises(SourceValidationError, match="external resource"):
        _check(tmp_path, '<rect><set attributeName="fill" to="url(https://example.invalid/p#g)"/></rect>')


def test_malformed_svg_is_rejected(tmp_path):
    with pytest.raises(SourceValidationError, match="well-formed"):
        _check(tmp_path, '<svg xmlns="http://www.w3.org/2000/svg"><g></svg>', wrap=False)


@pytest.mark.parametrize("body", [
    # Illustrator-style class rules
    '<defs><style>.cls-1{fill:#232f3e;}.cls-2{fill:none;stroke:#fff;stroke-width:2px}</style></defs>'
    '<rect class="cls-1" width="10" height="10"/><path class="cls-2" d="M0 0L10 10"/>',
    # gradients, clip paths, masks, filters and markers by id, quoted or not
    '<defs><linearGradient id="g"><stop offset="0" stop-color="#f90"/></linearGradient>'
    '<clipPath id="c"><rect width="5" height="5"/></clipPath><filter id="f"><feGaussianBlur stdDeviation="1"/></filter>'
    '<marker id="m"><path d="M0 0L1 1"/></marker></defs>'
    '<rect fill="url(#g)" clip-path="url( \'#c\' )" filter=\'url("#f")\' width="10" height="10"/>'
    '<path marker-end="url(#m)" style="fill:url(#g);stroke:URL(#g)" d="M0 0L5 5"/>',
    # reuse, links and embedded images inside the document
    '<defs><symbol id="s"><circle r="2"/></symbol></defs><use href="#s"/><use xlink:href="#s"/>'
    '<a href="#s"><text>jump</text></a><image href="data:image/png;base64,iVBORw0KGgo="/>',
    # harmless animation
    '<circle r="3"><animate attributeName="opacity" values="0;1;0" dur="2s" repeatCount="indefinite"/>'
    '<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="4s"/></circle>',
    # editor metadata in other namespaces
    '<metadata><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/></metadata>'
    '<sodipodi:namedview xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" pagecolor="#ffffff"/>'
    '<text font-family="\'Amazon Ember\', sans-serif">Q4: 42% → 58%</text>',
    # Inkscape on Windows: a path in editor metadata is not CSS
    '<g xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
    ' inkscape:export-filename="C:\\Users\\me\\icon.png" inkscape:label="Layer 1"/>',
    # a raster image embedded in a filter
    '<filter id="f"><feImage href="data:image/png;base64,iVBORw0KGgo="/></filter>',
], ids=["illustrator-classes", "local-paint-servers", "local-links", "animation", "metadata",
        "inkscape-windows-path", "filter-image"])
def test_ordinary_svg_passes(tmp_path, body):
    _check(tmp_path, body)


def test_svg_with_xml_declaration_and_comments_passes(tmp_path):
    _check(
        tmp_path,
        '<?xml version="1.0" encoding="UTF-8"?>\n<!-- Generator: Adobe Illustrator -->\n'
        f'<svg {_NS} viewBox="0 0 24 24"><path d="M12 2L2 22h20z"/></svg>',
        wrap=False,
    )


def test_generated_qr_code_passes(tmp_path):
    from sdpm.utils.svg import generate_qr_svg

    svg = tmp_path / "qr.svg"
    svg.write_bytes(generate_qr_svg("https://example.com/deck?id=1", color="#FF9900"))
    enforce_content_limits(svg, "image/svg+xml")


def test_css_escape_in_a_presentation_attribute_is_rejected(tmp_path):
    with pytest.raises(SourceValidationError, match="external resource"):
        _check(tmp_path, '<rect fill="\\75rl(https://example.invalid/p.svg#g)"/>')
