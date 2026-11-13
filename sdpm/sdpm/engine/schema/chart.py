# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Fingerprint of a chart element's structured fields.

The converter keeps the whole chart XML in ``_chartXml`` so an unedited chart
rebuilds exactly. It also stores ``_chartFingerprint``, a hash of the structured
fields it extracted; the builder restores ``_chartXml`` only while the fields
still hash the same, so an edit to them rebuilds the chart from the JSON —
except for a chart the JSON cannot describe (``_chartRebuildable: false``),
which keeps its ``_chartXml`` and gets a lint diagnostic instead.
"""
import hashlib
import json

# Element keys that describe chart content (geometry lives on the graphic frame
# and is applied either way, so it is not part of the fingerprint).
CHART_CONTENT_KEYS = (
    "chartType", "stacked", "horizontal", "markers", "smooth", "title",
    "titleFontColor", "titleFontSize", "categories", "series", "valueAxis",
    "categoryAxis", "legend", "gapWidth", "overlap", "dataLabels",
    "numberFormat", "holeSize", "style", "_chartFontSize",
)


def _canonical(value):
    """Normalise numbers so 12 and 12.0 hash the same."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def chart_fingerprint(elem: dict) -> str:
    """Return a stable hash of the chart element's content keys."""
    content = {k: _canonical(elem[k]) for k in CHART_CONTENT_KEYS if k in elem}
    blob = json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def chart_edited(elem: dict) -> bool:
    """True when the content keys no longer match ``_chartFingerprint``.

    JSON without a fingerprint (extracted before it existed) counts as unedited.
    """
    fingerprint = elem.get("_chartFingerprint")
    return fingerprint is not None and fingerprint != chart_fingerprint(elem)


def chart_edit_ignored(elem: dict) -> bool:
    """True when the chart was edited but only its ``_chartXml`` can rebuild it.

    The converter marks such charts ``_chartRebuildable: false`` (a chart type or a
    combination of plots that ``chartType`` does not describe); the builder keeps
    the original chart for them rather than turning it into another type.
    """
    return (bool(elem.get("_chartXml")) and elem.get("_chartRebuildable") is False
            and chart_edited(elem))


def restores_chart_xml(elem: dict) -> bool:
    """Whether the builder rebuilds this chart from ``_chartXml``."""
    if not elem.get("_chartXml"):
        return False
    return not chart_edited(elem) or elem.get("_chartRebuildable") is False
