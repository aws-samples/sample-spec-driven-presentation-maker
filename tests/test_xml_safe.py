# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""sdpm.utils.xml_safe: the one parser for XML that does not come from the repository."""

from __future__ import annotations

import pytest
from lxml import etree

from sdpm.tools.attachment.errors import SourceValidationError
from sdpm.utils import xml_safe
from sdpm.utils.svg import get_svg_dimensions

_SVG_NS = "http://www.w3.org/2000/svg"
_SVG11_DOCTYPE = ('<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
                  '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">')


def _nested_entities() -> str:
    decls = '<!ENTITY e0 "xxxxxxxxxx">' + "".join(
        f'<!ENTITY e{i} "{f"&e{i - 1};" * 10}">' for i in range(1, 9))
    return f"<!DOCTYPE r [{decls}]><r>&e8;</r>"


_EXTERNAL = '<!DOCTYPE r [<!ENTITY ext SYSTEM "file:///etc/hosts">]><r>&ext;</r>'
_PARAMETER = '<!DOCTYPE r [<!ENTITY % p SYSTEM "file:///etc/hosts"> %p;]><r/>'


def _encode(doc: str, encoding: str) -> bytes:
    return f'<?xml version="1.0" encoding="{encoding}"?>{doc}'.encode(encoding)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
@pytest.mark.parametrize("doc", [_nested_entities(), _EXTERNAL, _PARAMETER],
                         ids=["nested-entities", "external-entity", "parameter-entity"])
@pytest.mark.parametrize("allow_doctype", [False, True])
def test_entity_declarations_are_refused(doc, encoding, allow_doctype):
    with pytest.raises(etree.XMLSyntaxError):
        xml_safe.fromstring(_encode(doc, encoding), allow_doctype=allow_doctype)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_entity_declarations_are_refused_from_files(tmp_path, encoding):
    path = tmp_path / "x.svg"
    path.write_bytes(_encode(_EXTERNAL, encoding))
    with pytest.raises(etree.XMLSyntaxError):
        xml_safe.parse(path, allow_doctype=True)


def test_doctype_is_refused_unless_allowed():
    doc = f'{_SVG11_DOCTYPE}<svg xmlns="{_SVG_NS}" viewBox="0 0 10 10"/>'
    with pytest.raises(xml_safe.UnsafeXMLError):
        xml_safe.fromstring(doc)
    root = xml_safe.fromstring(doc, allow_doctype=True)
    assert root.get("viewBox") == "0 0 10 10"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_ordinary_documents_parse(encoding):
    doc = '<a:lstStyle xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:lvl1pPr/></a:lstStyle>'
    root = xml_safe.fromstring(_encode(doc, encoding))
    assert etree.QName(root).localname == "lstStyle"
    assert len(root) == 1


def test_caller_parser_is_used():
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, remove_comments=True)
    root = xml_safe.fromstring(f'<svg xmlns="{_SVG_NS}"><!-- c --><g/></svg>', allow_doctype=True, parser=parser)
    assert [etree.QName(el).localname for el in root] == ["g"]


# Adobe Illustrator declares its namespace URIs as entities inside the SVG 1.1 DOCTYPE.
_ILLUSTRATOR_SVG = (
    '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
    '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" [\n'
    '\t<!ENTITY ns_extend "http://ns.adobe.com/Extensibility/1.0/">\n'
    '\t<!ENTITY ns_ai "http://ns.adobe.com/AdobeIllustrator/10.0/">\n'
    '\t<!ENTITY label "Hello">\n'
    ']>\n'
    f'<svg xmlns:x="&ns_extend;" xmlns:i="&ns_ai;" xmlns="{_SVG_NS}" '
    'width="120px" height="80px" viewBox="0 0 120 80">'
    '<text>a &label; b<tspan/>c &label;</text></svg>'
)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_illustrator_svg_entities_are_expanded(encoding):
    root = xml_safe.fromstring(_encode(_ILLUSTRATOR_SVG, encoding), allow_doctype=True)
    assert root.nsmap["x"] == "http://ns.adobe.com/Extensibility/1.0/"
    assert root.nsmap["i"] == "http://ns.adobe.com/AdobeIllustrator/10.0/"
    text = root[0]
    assert text.text == "a Hello b"
    assert text[0].tail == "c Hello"
    assert b"&" not in etree.tostring(root)


def test_illustrator_svg_file_has_its_size(tmp_path):
    path = tmp_path / "artwork.svg"
    path.write_text(_ILLUSTRATOR_SVG, encoding="utf-8")
    assert get_svg_dimensions(path) == (120, 80)


def test_entities_are_refused_outside_svg():
    with pytest.raises(xml_safe.UnsafeXMLError, match="entity declarations"):
        xml_safe.fromstring(_ILLUSTRATOR_SVG)


@pytest.mark.parametrize("decl", [
    '<!ENTITY e "<g/>">',
    '<!ENTITY e "&#60;g/&#62;">',
    f'<!ENTITY e "{"x" * (xml_safe.MAX_ENTITY_LENGTH + 1)}">',
    "".join(f'<!ENTITY e{i} "x">' for i in range(xml_safe.MAX_ENTITIES + 1)),
    '<!ENTITY e SYSTEM "logo.gif" NDATA gif>',
], ids=["markup", "char-ref-markup", "too-long", "too-many", "unparsed"])
def test_svg_entities_must_be_plain_text(decl):
    with pytest.raises(xml_safe.UnsafeXMLError):
        xml_safe.fromstring(f'<!DOCTYPE svg [{decl}]><svg xmlns="{_SVG_NS}"/>', allow_doctype=True)


def test_file_errors_name_the_file(tmp_path):
    path = tmp_path / "part.xml"
    path.write_text(_EXTERNAL, encoding="utf-8")
    with pytest.raises(xml_safe.UnsafeXMLError) as info:
        xml_safe.parse(path)
    assert str(info.value) == f"XML entity declarations are not accepted: {path}"


def test_attached_svg_dtd_is_refused_by_the_parser(tmp_path):
    # The token scan runs first; call the parser-level check directly.
    from sdpm.tools.attachment.source import _check_svg_tree
    with pytest.raises(SourceValidationError):
        _check_svg_tree(f'{_SVG11_DOCTYPE}<svg xmlns="{_SVG_NS}"/>')
