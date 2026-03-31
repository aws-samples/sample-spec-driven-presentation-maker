# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Minimal output filter — strips defaults, internal keys, and font tags."""
import re

from sdpm.schema.defaults import (
    ELEMENT_DEFAULTS,
    GRADIENT_DEFAULTS,
    PARAGRAPH_INTERNAL_KEYS,
    sort_element_keys,
)

_FONT_TAG_RE = re.compile(r',?font=[^:,}]+')


def minimize(elements: list) -> list:
    """Apply all minimal-output transformations to elements."""
    elements = _strip_internal_keys(elements)
    for elem in elements:
        _strip_defaults(elem)
        _strip_gradient_defaults(elem)
        _strip_paragraph_internals(elem)
        _strip_conditional(elem)
        elem.pop("fontFamily", None)
        if elem.get("type") == "image" and "src" not in elem:
            elem["src"] = "<asset>"
    elements = _strip_font_tags(elements)
    return [sort_element_keys(e) for e in elements]


def _strip_defaults(elem: dict) -> None:
    defaults = ELEMENT_DEFAULTS.get(elem.get("type", ""), {})
    for k, v in defaults.items():
        if elem.get(k) == v:
            elem.pop(k)


def _strip_gradient_defaults(elem: dict) -> None:
    for key in ("gradient", "lineGradient"):
        g = elem.get(key)
        if isinstance(g, dict):
            for k, v in GRADIENT_DEFAULTS.items():
                if g.get(k) == v:
                    g.pop(k)


def _strip_paragraph_internals(elem: dict) -> None:
    for p in elem.get("paragraphs") or []:
        if isinstance(p, dict):
            for k in PARAGRAPH_INTERNAL_KEYS:
                p.pop(k, None)
            if p.get("bullet") is False:
                p.pop("bullet")


def _strip_conditional(elem: dict) -> None:
    if "lineGradient" in elem:
        elem.pop("color", None)


def _strip_internal_keys(obj):
    if isinstance(obj, dict):
        return {k: _strip_internal_keys(v) for k, v in obj.items() if not k.startswith('_')}
    if isinstance(obj, list):
        return [_strip_internal_keys(i) for i in obj]
    return obj


def _strip_font_tags(obj):
    if isinstance(obj, str):
        s = _FONT_TAG_RE.sub('', obj)
        s = re.sub(r'\{\{:((?:[^}]|\}(?!\}))*)\}\}', r'\1', s)
        s = s.replace('\\}\\}', '}}')
        return s
    if isinstance(obj, dict):
        return {k: _strip_font_tags(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_font_tags(i) for i in obj]
    return obj
