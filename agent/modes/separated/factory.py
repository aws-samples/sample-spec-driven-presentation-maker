# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Agent factory: assembles MCP clients, model, tools, and prompt into a Strands Agent."""

import logging
import os

from botocore.config import Config as BotocoreConfig
from strands import Agent
from strands.models import BedrockModel
from strands.models.bedrock import CacheConfig

from mcp_clients import (
    MCP_DEFS,
    mcp_agentcore_runtime,
    mcp_aws_knowledge,
    mcp_aws_pricing,
)
from modes.separated.composer import make_compose_slides
from modes.separated.composer import _prefetch_sections, _build_common_context
from prompts import build_system_prompt, load_prompt
from session import fix_excess_tool_results
from tools.upload_tools import list_uploads
from tools.web_tools import web_fetch

logger = logging.getLogger("sdpm.agent")

# Factory functions matching MCP_DEFS order
_MCP_FACTORIES = [
    lambda jwt_token: mcp_agentcore_runtime(jwt_token=jwt_token),
    lambda jwt_token: mcp_aws_knowledge(),
    lambda jwt_token: mcp_aws_pricing(),
]

# Workflow to prefetch for SPEC agent (Phase 1 entry point)
_SPEC_PREFETCH = [
    ("read_workflows", {"names": ["create-new-1-briefing"]}, "create-new-1-briefing"),
]


def create_separated_agent(user_id: str, session_id: str, jwt_token: str) -> tuple[Agent, list[dict]]:
    """Create a Strands Agent with MCP tools and memory (separated mode: SPEC + Composer).

    Args:
        user_id: User identifier (JWT sub claim).
        session_id: Conversation session ID.
        jwt_token: JWT access token for MCP Server authentication.

    Returns:
        Tuple of (Configured Strands Agent instance, MCP status list).
    """
    memory_id = os.environ.get("MEMORY_ID", "")
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

    # Set user_id for upload tools
    import tools.upload_tools as _ut
    _ut._current_user_id = user_id

    session_manager = None
    if memory_id and memory_id != "PLACEHOLDER":
        from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
        from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

        memory_config = AgentCoreMemoryConfig(
            memory_id=memory_id, session_id=session_id, actor_id=user_id,
        )
        session_manager = AgentCoreMemorySessionManager(
            agentcore_memory_config=memory_config, region_name=region,
        )

    model = BedrockModel(
        model_id=os.environ.get("MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        temperature=0.1,
        cache_config=CacheConfig(strategy="auto"),
    )

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

    # --- Build MCP server list with resilience ---
    mcp_servers = []
    mcp_status = []

    for (name, required), factory in zip(MCP_DEFS, _MCP_FACTORIES):
        try:
            mcp_servers.append(factory(jwt_token))
            mcp_status.append({"name": name, "status": "ok"})
        except Exception as e:
            mcp_status.append({"name": name, "status": "error", "error": str(e)})
            if required:
                raise

    # Composer MCP factory: each group gets a fresh MCPClient to isolate
    # connection failures. If one group's MCP session dies, others are unaffected.
    composer_mcp_factory = lambda: mcp_agentcore_runtime(jwt_token=jwt_token)  # noqa: E731

    compose_slides = make_compose_slides(mcp_servers, composer_model, composer_mcp_factory)
    tools = [*mcp_servers, compose_slides, list_uploads, web_fetch]

    try:
        agent = Agent(
            name="SdpmSpecAgent",
            system_prompt="",
            tools=tools,
            model=model,
            session_manager=session_manager,
            trace_attributes={"user.id": user_id, "session.id": session_id},
        )
    except Exception:
        logger.warning("Agent init failed with all MCP servers, retrying with required-only")
        # Keep only required MCP servers
        required_servers = []
        new_status = []
        for (name, required), st in zip(MCP_DEFS, mcp_status):
            if required and st["status"] == "ok":
                required_servers.append(mcp_servers[len(new_status)])
                new_status.append(st)
            else:
                if st["status"] == "ok":
                    new_status.append({"name": name, "status": "error", "error": "Service unavailable"})
                else:
                    new_status.append(st)

        mcp_servers = required_servers
        mcp_status = new_status
        compose_slides = make_compose_slides(mcp_servers, composer_model, composer_mcp_factory)
        agent = Agent(
            name="SdpmSpecAgent",
            system_prompt="",
            tools=[*mcp_servers, compose_slides, list_uploads, web_fetch],
            model=model,
            session_manager=session_manager,
            trace_attributes={"user.id": user_id, "session.id": session_id},
        )

    # Prefetch Phase 1 entry workflow so the SPEC agent starts with it pre-loaded.
    # Falls back to empty context on failure — agent startup must not break here
    # because SPEC agent is the user-facing entry point.
    try:
        prefetch_sections = _prefetch_sections(mcp_servers[0], _SPEC_PREFETCH) if mcp_servers else []
        common_context = _build_common_context(prefetch_sections)
    except Exception as e:
        logger.warning("SPEC agent workflow prefetch failed: %s", e)
        common_context = ""

    spec_agent_template = load_prompt("spec_agent")
    agent.system_prompt = build_system_prompt(
        spec_agent_template,
        common_context=common_context,
    )

    # Attach LoopGuard as hard-stop fallback when soft prompts fail
    from strands.hooks.events import AfterToolCallEvent
    from resilience import LoopGuard
    guard = LoopGuard(max_tool_calls=int(os.environ.get("SPEC_MAX_TOOL_CALLS", "300")))
    agent.hooks.add_callback(AfterToolCallEvent, guard.after_tool)

    fix_excess_tool_results(agent.messages)

    return agent, mcp_status
