# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Canonical JSON contracts for PowerPoint animation and transitions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

MODE_VALUES = frozenset({"inherit", "on", "off"})
ANIMATION_CATEGORIES = frozenset({"entrance", "emphasis", "exit", "motionPath", "media", "custom"})
TRIGGER_TYPES = frozenset({"none", "onPageClick", "withPrevious", "afterPrevious", "onShapeClick"})
BEHAVIOR_TYPES = frozenset({"motion", "color", "scale", "rotation", "property", "command", "filter", "set", "none"})
MORPH_OPTIONS = frozenset({"byObject", "byWord", "byChar"})
AFTER_EFFECT_TYPES = frozenset({"none", "dim", "hide", "hideOnNextClick"})
RESTART_VALUES = frozenset({"always", "whenNotActive", "never"})

MAX_TIMING_XML_DEPTH = 256
MAX_TIMING_XML_ELEMENTS = 100_000

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class MotionDiagnostic:
    """One path-aware validation error in a slide motion contract."""

    path: str
    rule: str
    message: str


def normalize_mode(value: str | None, name: str) -> str:
    """Validate a caller override and return its canonical value."""
    mode = "inherit" if value is None else value
    if mode not in MODE_VALUES:
        raise ValueError(f"{name} must be one of {sorted(MODE_VALUES)}, got {mode!r}")
    return mode


def resolve_enabled(deck: Mapping[str, Any], feature: str, override: str | None = "inherit") -> bool:
    """Resolve caller override, then deck switch, then the backward-compatible false default."""
    mode = normalize_mode(override, f"{feature}_mode")
    if mode != "inherit":
        return mode == "on"
    config = deck.get(feature)
    return bool(config.get("enabled", False)) if isinstance(config, Mapping) else False


def validate_deck_switches(deck: Mapping[str, Any]) -> list[MotionDiagnostic]:
    """Validate optional deck-level animation and transition switches."""
    diagnostics: list[MotionDiagnostic] = []
    for feature in ("animations", "transitions"):
        value = deck.get(feature)
        if value is None:
            continue
        if not isinstance(value, Mapping):
            diagnostics.append(MotionDiagnostic(feature, "invalid-feature-config", f"{feature} must be an object"))
            continue
        extra = set(value) - {"enabled"}
        if extra:
            diagnostics.append(
                MotionDiagnostic(feature, "unknown-feature-config", f"{feature} has unknown keys: {sorted(extra)}")
            )
        if "enabled" not in value or not isinstance(value.get("enabled"), bool):
            diagnostics.append(
                MotionDiagnostic(f"{feature}.enabled", "invalid-enabled", f"{feature}.enabled must be boolean")
            )
    return diagnostics


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(_ID_RE.fullmatch(value))


def _number(value: object, *, minimum: float | None = None, maximum: float | None = None) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if minimum is not None and value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False
    return True


def _validate_sound(value: object, path: str) -> list[MotionDiagnostic]:
    if value is None:
        return []
    if not isinstance(value, Mapping):
        return [MotionDiagnostic(path, "invalid-sound", "sound must be null or an object")]
    diagnostics: list[MotionDiagnostic] = []
    src = value.get("src")
    media_type = value.get("mediaType")
    if not isinstance(src, str) or not src or src.startswith(("/", "http://", "https://")) or ".." in src.split("/"):
        diagnostics.append(MotionDiagnostic(f"{path}.src", "invalid-sound-src", "sound src must be a safe workspace-relative path"))
    if not isinstance(media_type, str) or not media_type.startswith("audio/"):
        diagnostics.append(MotionDiagnostic(f"{path}.mediaType", "invalid-sound-media-type", "sound mediaType must be audio/*"))
    if "loop" in value and not isinstance(value["loop"], bool):
        diagnostics.append(MotionDiagnostic(f"{path}.loop", "invalid-sound-loop", "sound loop must be boolean"))
    return diagnostics


def _validate_timing(value: object, path: str) -> list[MotionDiagnostic]:
    if value is None:
        return []
    if not isinstance(value, Mapping):
        return [MotionDiagnostic(path, "invalid-timing", "timing must be an object")]
    diagnostics: list[MotionDiagnostic] = []
    positive = ("durationMs", "repeatDurationMs")
    non_negative = ("repeatCount", "acceleration", "deceleration", "bounceEnd")
    for key in positive:
        item = value.get(key)
        if item is not None and not _number(item, minimum=1):
            diagnostics.append(MotionDiagnostic(f"{path}.{key}", "invalid-timing-number", f"{key} must be a positive number or null"))
    for key in non_negative:
        item = value.get(key)
        if item is not None and not _number(item, minimum=0):
            diagnostics.append(MotionDiagnostic(f"{path}.{key}", "invalid-timing-number", f"{key} must be a non-negative number or null"))
    for key in ("autoReverse", "rewind", "smoothStart", "smoothEnd"):
        if key in value and not isinstance(value[key], bool):
            diagnostics.append(MotionDiagnostic(f"{path}.{key}", "invalid-timing-boolean", f"{key} must be boolean"))
    restart = value.get("restart")
    if restart is not None and restart not in RESTART_VALUES:
        diagnostics.append(MotionDiagnostic(f"{path}.restart", "invalid-restart", f"restart must be one of {sorted(RESTART_VALUES)}"))
    return diagnostics


def _validate_start(value: object, path: str, target_ids: set[str]) -> list[MotionDiagnostic]:
    if not isinstance(value, Mapping):
        return [MotionDiagnostic(path, "invalid-start", "start must be an object")]
    diagnostics: list[MotionDiagnostic] = []
    trigger = value.get("type")
    if trigger not in TRIGGER_TYPES:
        diagnostics.append(MotionDiagnostic(f"{path}.type", "invalid-trigger", f"trigger type must be one of {sorted(TRIGGER_TYPES)}"))
    delay = value.get("delayMs")
    if delay is not None and not _number(delay, minimum=0):
        diagnostics.append(MotionDiagnostic(f"{path}.delayMs", "invalid-delay", "delayMs must be a non-negative number"))
    trigger_target = value.get("target")
    if trigger == "onShapeClick":
        if not isinstance(trigger_target, str) or trigger_target not in target_ids:
            diagnostics.append(MotionDiagnostic(f"{path}.target", "unknown-trigger-target", "onShapeClick requires an existing element target"))
    elif trigger_target is not None:
        diagnostics.append(MotionDiagnostic(f"{path}.target", "unexpected-trigger-target", "only onShapeClick accepts a target"))
    return diagnostics


def _validate_behavior(value: object, path: str) -> list[MotionDiagnostic]:
    if not isinstance(value, Mapping):
        return [MotionDiagnostic(path, "invalid-behavior", "behavior must be an object")]
    kind = value.get("type")
    if kind not in BEHAVIOR_TYPES:
        return [MotionDiagnostic(f"{path}.type", "invalid-behavior-type", f"behavior type must be one of {sorted(BEHAVIOR_TYPES)}")]
    return []


def _validate_effect(value: object, path: str, target_ids: set[str]) -> list[MotionDiagnostic]:
    if not isinstance(value, Mapping):
        return [MotionDiagnostic(path, "invalid-effect", "animation effect must be an object")]
    diagnostics: list[MotionDiagnostic] = []
    effect_id = value.get("id")
    if not _valid_id(effect_id):
        diagnostics.append(MotionDiagnostic(f"{path}.id", "invalid-effect-id", "effect id must match ^[A-Za-z][A-Za-z0-9._-]*$"))
    target = value.get("target")
    if not isinstance(target, Mapping) or not isinstance(target.get("element"), str):
        diagnostics.append(MotionDiagnostic(f"{path}.target", "invalid-animation-target", "target.element is required"))
    elif target["element"] not in target_ids:
        diagnostics.append(MotionDiagnostic(f"{path}.target.element", "unknown-animation-target", f"unknown element target {target['element']!r}"))

    has_preset = "preset" in value
    has_behaviors = "behaviors" in value
    if has_preset == has_behaviors:
        diagnostics.append(MotionDiagnostic(path, "animation-source-count", "effect requires exactly one of preset or behaviors"))
    if has_preset:
        preset = value.get("preset")
        if not isinstance(preset, Mapping):
            diagnostics.append(MotionDiagnostic(f"{path}.preset", "invalid-preset", "preset must be an object"))
        else:
            category = preset.get("category")
            if category not in ANIMATION_CATEGORIES:
                diagnostics.append(MotionDiagnostic(f"{path}.preset.category", "invalid-animation-category", f"category must be one of {sorted(ANIMATION_CATEGORIES)}"))
            if not _valid_id(preset.get("effect")):
                diagnostics.append(MotionDiagnostic(f"{path}.preset.effect", "invalid-animation-effect", "effect must be a catalog identifier"))
    if has_behaviors:
        behaviors = value.get("behaviors")
        if not isinstance(behaviors, list) or not behaviors:
            diagnostics.append(MotionDiagnostic(f"{path}.behaviors", "invalid-behaviors", "behaviors must be a non-empty array"))
        else:
            for index, behavior in enumerate(behaviors):
                diagnostics.extend(_validate_behavior(behavior, f"{path}.behaviors[{index}]"))
    diagnostics.extend(_validate_start(value.get("start"), f"{path}.start", target_ids))
    diagnostics.extend(_validate_timing(value.get("timing"), f"{path}.timing"))
    diagnostics.extend(_validate_sound(value.get("sound"), f"{path}.sound"))
    after = value.get("afterEffect")
    if after is not None:
        if not isinstance(after, Mapping) or after.get("type") not in AFTER_EFFECT_TYPES:
            diagnostics.append(MotionDiagnostic(f"{path}.afterEffect", "invalid-after-effect", f"afterEffect.type must be one of {sorted(AFTER_EFFECT_TYPES)}"))
    return diagnostics


def _element_ids(slide: Mapping[str, Any]) -> tuple[set[str], list[MotionDiagnostic]]:
    ids: set[str] = set()
    morph_ids: set[str] = set()
    diagnostics: list[MotionDiagnostic] = []

    def add_identity(value: Mapping[str, Any], path: str) -> None:
        element_id = value.get("id")
        if element_id is not None:
            if not _valid_id(element_id):
                diagnostics.append(MotionDiagnostic(f"{path}.id", "invalid-element-id", "element id must match ^[A-Za-z][A-Za-z0-9._-]*$"))
            elif element_id in ids:
                diagnostics.append(MotionDiagnostic(f"{path}.id", "duplicate-element-id", f"duplicate element id {element_id!r}"))
            else:
                ids.add(element_id)
        morph_id = value.get("morphId")
        if morph_id is not None:
            if not _valid_id(morph_id):
                diagnostics.append(MotionDiagnostic(f"{path}.morphId", "invalid-morph-id", "morphId must match ^[A-Za-z][A-Za-z0-9._-]*$"))
            elif morph_id in morph_ids:
                diagnostics.append(MotionDiagnostic(f"{path}.morphId", "duplicate-morph-id", f"duplicate morphId {morph_id!r} on one slide"))
            else:
                morph_ids.add(morph_id)

    for index, element in enumerate(slide.get("elements") or []):
        if isinstance(element, Mapping) and element.get("type") != "include":
            add_identity(element, f"elements[{index}]")
    placeholders = slide.get("placeholders")
    if isinstance(placeholders, Mapping):
        for key, placeholder in placeholders.items():
            if isinstance(placeholder, Mapping):
                add_identity(placeholder, f"placeholders[{key!r}]")
    return ids, diagnostics


def validate_slide_motion(slide: Mapping[str, Any]) -> list[MotionDiagnostic]:
    """Validate one slide's transition, identities, and animation timeline."""
    target_ids, diagnostics = _element_ids(slide)
    transition = slide.get("transition")
    raw_transition = slide.get("_rawTransition")
    if transition is not None and raw_transition is not None:
        diagnostics.append(MotionDiagnostic("transition", "transition-source-conflict", "semantic transition and _rawTransition are mutually exclusive"))
    if transition is not None:
        if not isinstance(transition, Mapping):
            diagnostics.append(MotionDiagnostic("transition", "invalid-transition", "transition must be an object"))
        else:
            effect = transition.get("effect")
            if not _valid_id(effect):
                diagnostics.append(MotionDiagnostic("transition.effect", "invalid-transition-effect", "transition effect must be a catalog identifier"))
            duration = transition.get("durationMs")
            if duration is not None and not _number(duration, minimum=1):
                diagnostics.append(MotionDiagnostic("transition.durationMs", "invalid-transition-duration", "durationMs must be a positive number"))
            advance = transition.get("advance")
            if advance is not None:
                if not isinstance(advance, Mapping):
                    diagnostics.append(MotionDiagnostic("transition.advance", "invalid-transition-advance", "advance must be an object"))
                else:
                    if "onClick" in advance and not isinstance(advance["onClick"], bool):
                        diagnostics.append(MotionDiagnostic("transition.advance.onClick", "invalid-transition-on-click", "onClick must be boolean"))
                    after_ms = advance.get("afterMs")
                    if after_ms is not None and not _number(after_ms, minimum=0):
                        diagnostics.append(MotionDiagnostic("transition.advance.afterMs", "invalid-transition-after", "afterMs must be non-negative or null"))
            diagnostics.extend(_validate_sound(transition.get("sound"), "transition.sound"))
            if effect == "morph":
                parameters = transition.get("parameters")
                option = parameters.get("variant") if isinstance(parameters, Mapping) else None
                if option not in MORPH_OPTIONS:
                    diagnostics.append(MotionDiagnostic("transition.parameters.variant", "invalid-morph-variant", f"Morph variant must be one of {sorted(MORPH_OPTIONS)}"))

    animations = slide.get("animations")
    raw_timing = slide.get("_rawTiming")
    if animations is not None and raw_timing is not None:
        diagnostics.append(MotionDiagnostic("animations", "animation-source-conflict", "semantic animations and _rawTiming are mutually exclusive"))
    if animations is None:
        return diagnostics
    if not isinstance(animations, Mapping):
        diagnostics.append(MotionDiagnostic("animations", "invalid-animations", "animations must be an object"))
        return diagnostics

    effect_ids: set[str] = set()
    for sequence_key in ("mainSequence",):
        sequence = animations.get(sequence_key, [])
        if not isinstance(sequence, list):
            diagnostics.append(MotionDiagnostic(f"animations.{sequence_key}", "invalid-animation-sequence", f"{sequence_key} must be an array"))
            continue
        for index, effect in enumerate(sequence):
            path = f"animations.{sequence_key}[{index}]"
            diagnostics.extend(_validate_effect(effect, path, target_ids))
            if isinstance(effect, Mapping) and _valid_id(effect.get("id")):
                if effect["id"] in effect_ids:
                    diagnostics.append(MotionDiagnostic(f"{path}.id", "duplicate-effect-id", f"duplicate effect id {effect['id']!r}"))
                effect_ids.add(effect["id"])

    interactive = animations.get("interactiveSequences", [])
    if not isinstance(interactive, list):
        diagnostics.append(MotionDiagnostic("animations.interactiveSequences", "invalid-interactive-sequences", "interactiveSequences must be an array"))
    else:
        sequence_ids: set[str] = set()
        for sequence_index, sequence in enumerate(interactive):
            path = f"animations.interactiveSequences[{sequence_index}]"
            if not isinstance(sequence, Mapping):
                diagnostics.append(MotionDiagnostic(path, "invalid-interactive-sequence", "interactive sequence must be an object"))
                continue
            sequence_id = sequence.get("id")
            if not _valid_id(sequence_id):
                diagnostics.append(MotionDiagnostic(f"{path}.id", "invalid-sequence-id", "interactive sequence id is required"))
            elif sequence_id in sequence_ids:
                diagnostics.append(MotionDiagnostic(f"{path}.id", "duplicate-sequence-id", f"duplicate sequence id {sequence_id!r}"))
            else:
                sequence_ids.add(sequence_id)
            diagnostics.extend(_validate_start(sequence.get("trigger"), f"{path}.trigger", target_ids))
            effects = sequence.get("effects")
            if not isinstance(effects, list):
                diagnostics.append(MotionDiagnostic(f"{path}.effects", "invalid-animation-sequence", "effects must be an array"))
                continue
            for effect_index, effect in enumerate(effects):
                effect_path = f"{path}.effects[{effect_index}]"
                diagnostics.extend(_validate_effect(effect, effect_path, target_ids))
                if isinstance(effect, Mapping) and _valid_id(effect.get("id")):
                    if effect["id"] in effect_ids:
                        diagnostics.append(MotionDiagnostic(f"{effect_path}.id", "duplicate-effect-id", f"duplicate effect id {effect['id']!r}"))
                    effect_ids.add(effect["id"])
    return diagnostics


class TimingXmlLimitError(ValueError):
    """Raised when timing/transition XML exceeds the bounded parser contract."""


def validate_xml_resource_limits(
    xml_bytes: bytes,
    *,
    max_depth: int = MAX_TIMING_XML_DEPTH,
    max_elements: int = MAX_TIMING_XML_ELEMENTS,
) -> None:
    """Parse non-executing XML and enforce depth and element-count limits."""
    from lxml import etree

    if b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
        raise TimingXmlLimitError("DTD and entity declarations are forbidden")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)
    try:
        root = etree.fromstring(xml_bytes, parser=parser)
    except etree.XMLSyntaxError as error:
        raise TimingXmlLimitError(f"invalid or over-depth timing XML: {error}") from error

    count = 0
    stack = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        count += 1
        if count > max_elements:
            raise TimingXmlLimitError(f"timing XML exceeds {max_elements} elements")
        if depth > max_depth:
            raise TimingXmlLimitError(f"timing XML exceeds depth {max_depth}")
        stack.extend((child, depth + 1) for child in element)
