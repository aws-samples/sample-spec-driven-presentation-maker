# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""sdpm.utils.xml_safe: the one parser for XML that does not come from the repository."""

from __future__ import annotations

import pytest
from lxml import etree

from sdpm.tools.attachment.errors import SourceValidationError
from sdpm.tools.attachment.source import enforce_content_limits
from sdpm.utils import xml_safe

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


def test_utf16_svg_attachment_is_refused(tmp_path):
    # Attached SVGs must be UTF-8 (test_attachment_validation pins the error type).
    svg = tmp_path / "x.svg"
    svg.write_bytes(_encode(f'<svg xmlns="{_SVG_NS}"/>', "utf-16"))
    with pytest.raises(UnicodeDecodeError):
        enforce_content_limits(svg, "image/svg+xml")


def test_attached_svg_dtd_is_refused_by_the_parser(tmp_path):
    # The token scan runs first; call the parser-level check directly.
    from sdpm.tools.attachment.source import _check_svg_tree
    with pytest.raises(SourceValidationError):
        _check_svg_tree(f'{_SVG11_DOCTYPE}<svg xmlns="{_SVG_NS}"/>')
