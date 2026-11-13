# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Fingerprint of a chart element's structured fields.

The converter keeps the whole chart XML in ``_chartXml`` so an unedited chart
rebuilds exactly. It also stores ``_chartFingerprint``, a hash of the structured
fields it extracted; the builder restores ``_chartXml`` only while the fields
still hash the same, so an edit to them rebuilds the chart from the JSON.
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
