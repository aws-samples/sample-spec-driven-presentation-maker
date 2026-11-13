# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Parse XML that does not come from this repository.

Imported and template PPTX parts, the XML fragments a slide JSON carries for round trips,
and SVG files all go through here, so the parser settings are written down once instead of
depending on the defaults of the installed lxml: no entity substitution, no DTD loading, no
network access, and libxml2's normal size limits (``huge_tree=False``).

The checks run on the parsed tree, so they hold whatever encoding the document uses.
A document that declares entities is refused. A DOCTYPE is refused too, except for SVG
(``allow_doctype=True``), whose exporters commonly write the SVG 1.1 DOCTYPE; OOXML parts
never carry one.
"""
from pathlib import Path

from lxml import etree

PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


class UnsafeXMLError(etree.XMLSyntaxError):
    """The document declares entities, or a DOCTYPE where none is accepted."""


def _check(tree: etree._ElementTree, allow_doctype: bool) -> None:
    docinfo = tree.docinfo
    dtd = docinfo.internalDTD
    if dtd is not None and any(True for _ in dtd.iterentities()):
        raise UnsafeXMLError("XML entity declarations are not accepted", 0, 0, 0)
    if docinfo.doctype and not allow_doctype:
        raise UnsafeXMLError("XML DOCTYPE is not accepted", 0, 0, 0)


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
    """Parse the file at ``path`` with ``parser`` (default: :data:`PARSER`)."""
    tree = etree.parse(str(path), parser)
    _check(tree, allow_doctype)
    return tree
