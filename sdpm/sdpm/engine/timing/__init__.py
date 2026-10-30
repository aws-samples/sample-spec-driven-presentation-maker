# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""PowerPoint animation and slide-transition contracts."""

from .catalog import CATALOG_SCHEMA_VERSION, CatalogError, load_catalog, validate_catalog
from .model import (
    AFTER_EFFECT_TYPES,
    ANIMATION_CATEGORIES,
    BEHAVIOR_TYPES,
    MAX_TIMING_XML_DEPTH,
    MAX_TIMING_XML_ELEMENTS,
    MODE_VALUES,
    MORPH_OPTIONS,
    MotionDiagnostic,
    TimingXmlLimitError,
    normalize_mode,
    resolve_enabled,
    validate_deck_switches,
    validate_slide_motion,
    validate_xml_resource_limits,
)

__all__ = [
    "AFTER_EFFECT_TYPES",
    "ANIMATION_CATEGORIES",
    "BEHAVIOR_TYPES",
    "CATALOG_SCHEMA_VERSION",
    "CatalogError",
    "MAX_TIMING_XML_DEPTH",
    "MAX_TIMING_XML_ELEMENTS",
    "MODE_VALUES",
    "MORPH_OPTIONS",
    "MotionDiagnostic",
    "TimingXmlLimitError",
    "load_catalog",
    "normalize_mode",
    "resolve_enabled",
    "validate_catalog",
    "validate_deck_switches",
    "validate_slide_motion",
    "validate_xml_resource_limits",
]
