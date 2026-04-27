# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Bedrock usage logger: emits per-invocation cache/token metrics for cost analysis."""

import json
import logging

from strands.hooks.events import AfterInvocationEvent

logger = logging.getLogger("sdpm.cost")


def log_usage(event: AfterInvocationEvent) -> None:
    """Log per-invocation token usage (fresh/cache-read/cache-write/output)."""
    try:
        inv = event.agent.event_loop_metrics.latest_agent_invocation
        if inv is None:
            return
        usage = inv.usage
        attrs = event.agent.trace_attributes
    except Exception as e:
        logger.warning("cost_logger failed: %s", e)
        return
    logger.info(json.dumps({
        "kind": "bedrock_usage",
        "agent": event.agent.name,
        "group_index": attrs.get("group.index"),
        "group_slugs": attrs.get("group.slugs"),
        "input": usage.get("inputTokens", 0),
        "output": usage.get("outputTokens", 0),
        "cache_read": usage.get("cacheReadInputTokens", 0),
        "cache_write": usage.get("cacheWriteInputTokens", 0),
    }))
