# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unified agent factory: assembles MCP clients, model, tools, and prompt into a Strands Agent."""

import logging
import os
import uuid

from botocore.config import Config as BotocoreConfig
from strands import Agent
from strands.hooks.events import AfterToolCallEvent
from strands.models import BedrockModel
from strands.models.bedrock import CacheConfig

from mcp_clients import (
    MCP_DEFS,
    collect_mcp_instructions,
    mcp_agentcore_runtime,
    mcp_aws_knowledge,
    mcp_aws_pricing,
)
from modes import MODES
from modes.separated.composer import make_compose_slides
from prompts import build_system_prompt, load_prompt
from resilience import LoopGuard
from session import fix_excess_tool_results
from tools.upload_tools import list_uploads
from tools.web_tools import web_fetch

logger = logging.getLogger("sdpm.agent")

_MCP_FACTORIES = [
    lambda jwt_token: mcp_agentcore_runtime(jwt_token=jwt_token),
    lambda jwt_token: mcp_aws_knowledge(),
    lambda jwt_token: mcp_aws_pricing(),
]


# ---------------------------------------------------------------------------
# Prefetch helpers (canonical location — composer.py imports from here)
# ---------------------------------------------------------------------------

def prefetch_sections(mcp_client, prefetch_list: list) -> list[str]:
    """Prefetch references from MCP server via synchronous tool calls."""
    sections = []
    for tool_name, args, label in prefetch_list:
        result = mcp_client.call_tool_sync(
            tool_use_id=f"prefetch-{uuid.uuid4().hex[:8]}",
            name=tool_name,
            arguments=args,
        )
        if result.get("status") == "error":
            raise RuntimeError(f"Failed to prefetch {label}: {result.get('content')}")
        text = ""
        for item in result.get("content", []):
            if isinstance(item, dict) and "text" in item:
                text += item["text"]
        if text:
            sections.append(f"## {label}\n\n{text}")
    return sections


def build_common_context(sections: list[str]) -> str:
    """Build common reference context string from prefetched sections."""
    if not sections:
        return ""
    return "# Pre-loaded References (already executed — do NOT re-fetch)\n\n" + "\n\n---\n\n".join(sections)


# ---------------------------------------------------------------------------
# Prefill injection
# ---------------------------------------------------------------------------

def _inject_prefill(messages: list, sections: list[str], prefetch_list: list) -> None:
    """Inject prefetched content as fake tool call history.

    Only called when len(agent.messages) == 0 (new session).
    Restored sessions already contain the prefill from the first run.
    """
    for (tool_name, args, label), section in zip(prefetch_list, sections):
        tool_use_id = f"prefill-{uuid.uuid4().hex[:8]}"
        messages.extend([
            {
                "role": "assistant",
                "content": [
                    {"text": f"I'll read the {label} workflow."},
                    {"toolUse": {"toolUseId": tool_use_id, "name": tool_name, "input": args}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"toolResult": {"toolUseId": tool_use_id, "content": [{"text": section}], "status": "success"}},
                ],
            },
        ])


# ---------------------------------------------------------------------------
# Unified factory
# ---------------------------------------------------------------------------

def create_agent(mode: str, user_id: str, session_id: str, jwt_token: str) -> tuple[Agent, list[dict]]:
    """Create a Strands Agent for the given mode.

    Returns:
        Tuple of (Configured Strands Agent, MCP status list).
    """
    cfg = MODES[mode]
    memory_id = os.environ.get("MEMORY_ID", "")
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

    import tools.upload_tools as _ut
    _ut._current_user_id = user_id

    # Session manager
    session_manager = None
    if memory_id and memory_id != "PLACEHOLDER":
        from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
        from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
        session_manager = AgentCoreMemorySessionManager(
            agentcore_memory_config=AgentCoreMemoryConfig(
                memory_id=memory_id, session_id=session_id, actor_id=user_id,
            ),
            region_name=region,
        )

    # Models
    model = BedrockModel(
        model_id=os.environ.get("MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        temperature=0.1,
        cache_config=CacheConfig(strategy="auto"),
    )

    # MCP servers
    mcp_servers = []
    mcp_status = []
    for (name, required), factory_fn in zip(MCP_DEFS, _MCP_FACTORIES):
        try:
            mcp_servers.append(factory_fn(jwt_token))
            mcp_status.append({"name": name, "status": "ok"})
        except Exception as e:
            mcp_status.append({"name": name, "status": "error", "error": str(e)})
            if required:
                raise

    # Tools
    tools = [*mcp_servers, list_uploads, web_fetch]
    composer_mcp_factory = None
    if cfg.use_composer:
        composer_model = BedrockModel(
            model_id=os.environ.get("COMPOSER_MODEL_ID", os.environ.get("MODEL_ID", "global.anthropic.claude-sonnet-4-6")),
            temperature=0.1,
            cache_config=CacheConfig(strategy="auto"),
            boto_client_config=BotocoreConfig(
                user_agent_extra="strands-agents",
                read_timeout=120,
                retries={"max_attempts": 5, "mode": "adaptive"},
            ),
        )
        composer_mcp_factory = lambda: mcp_agentcore_runtime(jwt_token=jwt_token)  # noqa: E731
        compose_slides = make_compose_slides(mcp_servers, composer_model, composer_mcp_factory)
        tools.append(compose_slides)

    # Agent
    agent_name = f"Sdpm{mode.capitalize()}Agent"
    try:
        agent = Agent(
            name=agent_name, system_prompt="", tools=tools, model=model,
            session_manager=session_manager,
            trace_attributes={"user.id": user_id, "session.id": session_id},
        )
    except Exception:
        logger.warning("Agent init failed with all MCP servers, retrying with required-only")
        required_servers = []
        new_status = []
        for (name, required), st in zip(MCP_DEFS, mcp_status):
            if required and st["status"] == "ok":
                required_servers.append(mcp_servers[len(new_status)])
                new_status.append(st)
            else:
                new_status.append({"name": name, "status": "error", "error": st.get("error", "Service unavailable")})
        mcp_servers = required_servers
        mcp_status = new_status
        tools = [*mcp_servers, list_uploads, web_fetch]
        if cfg.use_composer:
            compose_slides = make_compose_slides(mcp_servers, composer_model, composer_mcp_factory)
            tools.append(compose_slides)
        agent = Agent(
            name=agent_name, system_prompt="", tools=tools, model=model,
            session_manager=session_manager,
            trace_attributes={"user.id": user_id, "session.id": session_id},
        )

    # Prefetch + prefill (new sessions only)
    if cfg.prefetch:
        try:
            sections = prefetch_sections(mcp_servers[0], cfg.prefetch) if mcp_servers else []
            if sections and len(agent.messages) == 0:
                _inject_prefill(agent.messages, sections, cfg.prefetch)
        except Exception as e:
            logger.warning("Workflow prefetch failed: %s", e)

    # System prompt
    prompt_kwargs = {}
    if cfg.inject_mcp_instructions:
        prompt_kwargs["mcp_instructions"] = collect_mcp_instructions(mcp_servers)
    template = load_prompt(cfg.prompt_key)
    prompt = build_system_prompt(template, **prompt_kwargs)

    if cfg.prefetch:
        # No common_context in prompt — it's in message history now
        agent.system_prompt = [
            {"text": prompt},
            {"cachePoint": {"type": "default"}},
        ]
    else:
        agent.system_prompt = prompt

    # LoopGuard
    guard = LoopGuard(max_tool_calls=int(os.environ.get("SPEC_MAX_TOOL_CALLS", "300")))
    agent.hooks.add_callback(AfterToolCallEvent, guard.after_tool)

    fix_excess_tool_results(agent.messages)

    return agent, mcp_status
