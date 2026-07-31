# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Per-model Bedrock invocation profiles.

Centralises the differences in how each Bedrock model must be called
(e.g. Opus 4.7 rejects `temperature` because of extended thinking,
while Sonnet accepts `temperature=0.1`).

Structure inspired by aws-samples/generative-ai-use-cases's
`packages/cdk/lambda/utils/models.ts` (family-default constants + model-id map).

Usage:
    from model_profiles import build_model_kwargs
    model = BedrockModel(**build_model_kwargs("global.anthropic.claude-opus-4-7"))
"""

from dataclasses import dataclass, replace
from typing import Literal

from strands.models.bedrock import CacheConfig


@dataclass(frozen=True)
class ModelProfile:
    """Bedrock invocation parameters for one model family.

    Attributes:
        temperature: Sampling temperature. ``None`` means "do not pass
            ``temperature`` to BedrockModel at all" — required for models
            that reject the parameter (e.g. Claude Opus 4.7 extended thinking).
        cache_strategy: Prompt-caching strategy. ``"auto"`` enables
            Strands' automatic prompt cache. ``"none"`` disables it for
            models that do not support prompt caching on Bedrock.
        compose_capable: Whether the model has sufficient capability for
            slide generation (compose). Models below Sonnet-class should
            set this to ``False``.
        max_tokens: Maximum output tokens per response. Without an explicit
            value Bedrock applies a small model default, which truncates
            long single-call outputs (e.g. writing specs/brief.md in one
            run_python call) and surfaces as MaxTokensReachedException.
    """

    temperature: float | None = 0.1
    cache_strategy: Literal["auto", "none"] = "auto"
    compose_capable: bool = True
    max_tokens: int | None = 32768

    def with_overrides(self, **kwargs) -> "ModelProfile":
        """Return a new profile with the given fields overridden.

        Reserved for future per-usecase tuning (e.g. main vs sub
        agent wanting different temperature on the same model).
        """
        return replace(self, **kwargs)

    def to_bedrock_kwargs(self) -> dict:
        """Convert the profile to kwargs for ``BedrockModel(**kwargs)``."""
        kwargs: dict = {}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.cache_strategy == "auto":
            kwargs["cache_config"] = CacheConfig(strategy="auto")
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        return kwargs


# ---------------------------------------------------------------------------
# Family defaults
# ---------------------------------------------------------------------------

# Claude (Anthropic) — standard models accept temperature and support prompt caching.
CLAUDE_STANDARD = ModelProfile(temperature=0.1, cache_strategy="auto")

# Claude Haiku — same invocation params as standard, but not capable enough for compose.
CLAUDE_HAIKU = ModelProfile(temperature=0.1, cache_strategy="auto", compose_capable=False)

# Claude with extended thinking (e.g. Opus 4.7). Bedrock rejects
# ``temperature`` because extended thinking forces temperature=1 internally;
# passing it triggers ``ValidationException: temperature is deprecated``.
CLAUDE_EXTENDED_THINKING = ModelProfile(temperature=None, cache_strategy="auto")

# Claude with adaptive thinking (e.g. Opus 4.6). Temperature=1 is required
# when reasoning is enabled; Strands handles this internally.
CLAUDE_ADAPTIVE_THINKING = ModelProfile(temperature=1.0, cache_strategy="auto")

# Amazon Nova 2 — supports prompt caching.
NOVA_2_DEFAULT = ModelProfile(temperature=0.7, cache_strategy="auto", compose_capable=False,
                              max_tokens=8192)

# DeepSeek — prompt caching not supported on Bedrock at time of writing.
DEEPSEEK_DEFAULT = ModelProfile(temperature=0.6, cache_strategy="none", compose_capable=False,
                                max_tokens=8192)

# Qwen — prompt caching not supported on Bedrock at time of writing.
QWEN_DEFAULT = ModelProfile(temperature=0.7, cache_strategy="none", compose_capable=False,
                            max_tokens=8192)

# Moonshot Kimi — prompt caching not supported on Bedrock at time of writing.
KIMI_DEFAULT = ModelProfile(temperature=0.6, cache_strategy="none", compose_capable=False,
                            max_tokens=8192)

# OpenAI GPT — bedrock-mantle only (Responses API endpoint).
GPT_DEFAULT = ModelProfile(temperature=0.7, cache_strategy="none")


# Fallback profile when a model id is not explicitly registered.
_DEFAULT = CLAUDE_STANDARD

# Models served via bedrock-mantle (OpenAI-compatible endpoint, not Converse API).
# model_id → list of supported regions (first entry is the fallback).
MANTLE_MODELS: dict[str, list[str]] = {
    "openai.gpt-5.6-terra": ["us-east-1", "us-east-2", "us-west-2"],
    "openai.gpt-5.5": ["us-east-1", "us-east-2"],
    "openai.gpt-5.4": ["us-east-1", "us-east-2", "us-west-2"],
}

# Mantle models that only support the Responses API (no Chat Completions).
# GPT-5.6 model cards: Responses ✅ / Chat Completions ❌ — calling
# /chat/completions returns 400 Bad Request.
MANTLE_RESPONSES_MODELS: set[str] = {
    "openai.gpt-5.6-terra",
}


def resolve_mantle_region(model_id: str, deploy_region: str | None = None) -> str:
    """Resolve the best mantle region for a model.

    If the deploy region is in the model's supported list, use it (lowest latency).
    Otherwise fall back to the first region in the list.
    """
    regions = MANTLE_MODELS.get(model_id, [])
    if not regions:
        return deploy_region or "us-east-1"
    if deploy_region and deploy_region in regions:
        return deploy_region
    return regions[0]


# ---------------------------------------------------------------------------
# Model id → profile map
# ---------------------------------------------------------------------------
# Keep in sync with:
#   - infra/lib/model-metadata.ts (UI display)
#   - infra/config.yaml#model.allowedModelIds (runtime selection)

MODEL_PROFILES: dict[str, ModelProfile] = {
    # Anthropic Claude
    "global.anthropic.claude-sonnet-5": CLAUDE_ADAPTIVE_THINKING,
    "global.anthropic.claude-opus-4-8": CLAUDE_EXTENDED_THINKING,
    "global.anthropic.claude-opus-4-7": CLAUDE_EXTENDED_THINKING,
    "global.anthropic.claude-opus-4-6-v1": CLAUDE_ADAPTIVE_THINKING,
    "global.anthropic.claude-sonnet-4-6": CLAUDE_STANDARD,
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": CLAUDE_HAIKU,
    # Amazon Nova
    "us.amazon.nova-2-lite-v1:0": NOVA_2_DEFAULT,
    # OpenAI GPT (bedrock-mantle)
    "openai.gpt-5.6-terra": GPT_DEFAULT,
    "openai.gpt-5.5": GPT_DEFAULT,
    "openai.gpt-5.4": GPT_DEFAULT,
}


def build_model_kwargs(model_id: str, **overrides) -> dict:
    """Build BedrockModel kwargs for ``model_id``.

    Args:
        model_id: Bedrock inference profile id.
        **overrides: Optional per-call overrides applied on top of the
            family profile (e.g. ``temperature=0.0`` for a specific
            deterministic usecase).

    Returns:
        A dict suitable for ``BedrockModel(**kwargs)``. Always contains
        ``model_id``; may omit ``temperature`` for models whose profile
        has ``temperature=None``.
    """
    profile = MODEL_PROFILES.get(model_id, _DEFAULT)
    if overrides:
        profile = profile.with_overrides(**overrides)
    return {"model_id": model_id, **profile.to_bedrock_kwargs()}
