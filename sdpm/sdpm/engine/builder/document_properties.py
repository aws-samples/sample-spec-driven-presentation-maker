# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Start every built deck with its own document properties, not the template's.

python-pptx opens the template and saves it under a new name, so without this the deck
keeps the template's ``docProps``: its author and last editor, its description, created /
modified dates and revision (``core.xml``), the template's slide titles and word counts
(``app.xml``) and, for the bundled templates, their custom properties (``custom.xml``).

A user template's custom properties (for example a sensitivity label the organisation
applies) stay on the deck: they are the user's policy, not leftover authoring data.
"""
import hashlib
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from lxml import etree
from pptx.oxml.ns import qn

from sdpm.config import TEMPLATES_DIR
from sdpm.utils import xml_safe

# Core properties that describe the template file. The deck sets ``title`` / ``language``
# itself when it has them, after this reset.
_CORE_TEXT = (
    "author", "last_modified_by", "title", "subject", "keywords", "category",
    "comments", "content_status", "identifier", "language", "version",
)

# app.xml statistics and identity that describe the template; PowerPoint recomputes the
# statistics on its next save. Every one of them is optional in the schema.
_EP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
_APP_DROP = (
    "TotalTime", "Words", "Paragraphs", "Slides", "Notes", "HiddenSlides", "MMClips",
    "HeadingPairs", "TitlesOfParts", "Company", "Manager", "HyperlinkBase",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes(), usedforsecurity=False).hexdigest()


@lru_cache(maxsize=1)
def _bundled_digests() -> frozenset[str]:
    return frozenset(_sha256(p) for p in TEMPLATES_DIR.glob("*.pptx"))


def is_bundled_template(template_path: Path) -> bool:
    """True when the template's bytes are one of the templates shipped in ``sdpm/templates``.

    Compared by content, not location: the remote server downloads the bundled templates
    from S3 (uploaded unchanged from ``sdpm/templates``) into a temp ``template.pptx``.
    """
    return _sha256(Path(template_path)) in _bundled_digests()


def reset_document_properties(prs, *, bundled: bool) -> None:
    """Clear what ``prs`` inherited from its template and date it now."""
    props = prs.core_properties
    for name in _CORE_TEXT:
        if getattr(props, name):  # setting an absent one would add an empty element
            setattr(props, name, "")
    printed = props._element.find(qn("cp:lastPrinted"))
    if printed is not None:
        props._element.remove(printed)
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    props.created = now
    props.modified = now
    props.revision = 1

    _rewrite_part(prs, "/docProps/app.xml", _clean_app)
    if bundled:
        _rewrite_part(prs, "/docProps/custom.xml", _clear_children)


def _clean_app(root: etree._Element) -> None:
    for name in _APP_DROP:
        for el in root.findall(f"{{{_EP}}}{name}"):
            root.remove(el)


def _clear_children(root: etree._Element) -> None:
    for el in list(root):
        root.remove(el)


def _rewrite_part(prs, partname: str, edit) -> None:
    # app.xml / custom.xml load as plain blob parts (python-pptx has no API for them),
    # so the blob is parsed, edited and stored back.
    for part in prs.part.package.iter_parts():
        if str(part.partname) == partname:
            root = xml_safe.fromstring(part.blob)
            edit(root)
            part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            return
