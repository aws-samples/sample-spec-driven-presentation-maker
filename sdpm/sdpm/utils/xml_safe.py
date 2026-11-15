# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Parse XML that does not come from this repository.

Imported and template PPTX parts, the XML fragments a slide JSON carries for round trips,
and SVG files all go through here, so the parser settings are written down once instead of
depending on the defaults of the installed lxml: no entity substitution, no DTD loading, no
network access, and libxml2's normal size limits (``huge_tree=False``).

The checks run on the parsed tree, so they hold whatever encoding the document uses.
A DOCTYPE is refused, and with it any entity declaration, except for SVG
(``allow_doctype=True``): SVG exporters commonly write the SVG 1.1 DOCTYPE, and Adobe
Illustrator also declares its namespace URIs as entities (``<!ENTITY ns_ai "http://...">``).
SVG may therefore declare plain-text internal entities (:data:`MAX_ENTITIES` at most, each
value at most :data:`MAX_ENTITY_LENGTH` characters, with no ``<`` or ``&``), which are
expanded once the document is parsed. External, nested and markup-bearing entities are
refused. OOXML parts never carry a DOCTYPE.
"""
from pathlib import Path

from lxml import etree

PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)

#: Limits on the internal entities an SVG may declare.
MAX_ENTITIES = 64
MAX_ENTITY_LENGTH = 1024
_ENTITY_FORBIDDEN = frozenset("<&")


class UnsafeXMLError(etree.XMLSyntaxError):
    """The document has a DOCTYPE or an entity declaration that is not accepted."""

    def __init__(self, message: str, filename: str | None = None):
        super().__init__(message, 0, 0, 0, filename)
        self.message = message

    def __str__(self) -> str:
        return f"{self.message}: {self.filename}" if self.filename else self.message


def _plain_entities(dtd: etree.DTD, filename: str | None) -> dict[str, str]:
    """The internal subset's entities as ``{name: value}``, or UnsafeXMLError."""
    values: dict[str, str] = {}
    for entity in dtd.iterentities():
        value = entity.content
        if (entity.system_url is not None or value is None or len(value) > MAX_ENTITY_LENGTH
                or not _ENTITY_FORBIDDEN.isdisjoint(value)):
            raise UnsafeXMLError(f"XML entity '{entity.name}' is not accepted", filename)
        values[entity.name] = value
        if len(values) > MAX_ENTITIES:
            raise UnsafeXMLError(f"more than {MAX_ENTITIES} XML entities are not accepted", filename)
    return values


def _expand(root: etree._Element, values: dict[str, str]) -> None:
    """Replace references to ``values`` in element content with their text.

    libxml2 substitutes references in attribute values even with ``resolve_entities=False``;
    references in content stay entity nodes, which serialize as ``&name;`` and would be
    undeclared once the element is written out without its DOCTYPE.
    """
    for node in list(root.iter(etree.Entity)):
        value = values.get(node.name)
        parent = node.getparent()
        if value is None or parent is None:
            continue
        text = value + (node.tail or "")
        previous = node.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + text
        else:
            parent.text = (parent.text or "") + text
        parent.remove(node)


def _check(tree: etree._ElementTree, allow_doctype: bool, filename: str | None = None) -> None:
    docinfo = tree.docinfo
    dtd = docinfo.internalDTD
    has_entities = dtd is not None and any(True for _ in dtd.iterentities())
    if not allow_doctype:
        if has_entities:
            raise UnsafeXMLError("XML entity declarations are not accepted", filename)
        if docinfo.doctype:
            raise UnsafeXMLError("XML DOCTYPE is not accepted", filename)
        return
    if has_entities:
        _expand(tree.getroot(), _plain_entities(dtd, filename))


def fromstring(data: str | bytes, *, allow_doctype: bool = False,
               parser: etree.XMLParser = PARSER) -> etree._Element:
    """Parse ``data`` with ``parser`` (default: :data:`PARSER`) and return the root element.

    Raises:
        etree.XMLSyntaxError: Malformed XML, or :class:`UnsafeXMLError` (a subclass).
    """
    root = etree.fromstring(data, parser)
    _check(root.getroottree(), allow_doctype)
    return root


def parse(path: str | Path, *, allow_doctype: bool = False,
          parser: etree.XMLParser = PARSER) -> etree._ElementTree:
    """Parse the file at ``path`` with ``parser`` (default: :data:`PARSER`).

    Raises:
        etree.XMLSyntaxError: Malformed XML, or :class:`UnsafeXMLError` naming ``path``.
    """
    tree = etree.parse(str(path), parser)
    _check(tree, allow_doctype, str(path))
    return tree
