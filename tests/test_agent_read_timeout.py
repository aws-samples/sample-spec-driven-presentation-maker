# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Every agent's Bedrock client waits BEDROCK_READ_TIMEOUT_S for the next stream byte.

A model writing one large tool argument sends nothing until the argument is complete. On
dev (2026-11-12) Opus 5.5 writing a style went silent for over 120 s, strands' default, and
the turn ended with "The model took too long to respond".
"""

import pytest


def _factory():
    # Imported lazily, as in test_agent_assembly (agent/ on sys.path shadows other packages).
    from test_mcp_parallel_connect import _factory as load

    return load()


@pytest.mark.parametrize("composer", [False, True])
def test_bedrock_read_timeout_covers_a_long_tool_argument(composer: bool) -> None:
    factory = _factory()
    model = factory.build_model("global.anthropic.claude-opus-5-5", composer=composer)

    assert factory.BEDROCK_READ_TIMEOUT_S == 600
    assert model.client.meta.config.read_timeout == factory.BEDROCK_READ_TIMEOUT_S


def test_composer_keeps_its_adaptive_retries() -> None:
    factory = _factory()
    model = factory.build_model("global.anthropic.claude-opus-5-5", composer=True)

    assert model.client.meta.config.retries["mode"] == "adaptive"
