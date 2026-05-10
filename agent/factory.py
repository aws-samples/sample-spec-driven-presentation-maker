# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unified agent factory: assembles MCP clients, model, tools, and prompt into a Strands Agent."""

import json
import logging
import os

from botocore.config import Config as BotocoreConfig
from strands import Agent
from strands.hooks.events import AfterInvocationEvent, AfterToolCallEvent
from strands.models import BedrockModel

from cost_logger import log_usage
from mcp_clients import (
    MCP_DEFS,
    collect_mcp_instructions,
    mcp_agentcore_runtime,
    mcp_aws_knowledge,
    mcp_aws_pricing,
)
from composition import resolve_parts
from model_profiles import build_model_kwargs, MODEL_PROFILES
from modes import MODES
from modes.separated.composer import make_compose_slides
from resilience import LoopGuard
from session import fix_excess_tool_results
from tools.hearing_tool import hearing
from tools.web_tools import web_fetch

logger = logging.getLogger("sdpm.agent")

_ALLOWED_MODEL_IDS: set[str] = set(json.loads(os.environ.get("ALLOWED_MODEL_IDS", "[]")))
_DEFAULT_CHAT_MODEL_ID: str = os.environ.get("CHAT_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
_DEFAULT_CREATE_MODEL_ID: str = os.environ.get("CREATE_MODEL_ID", _DEFAULT_CHAT_MODEL_ID)


def _resolve_model_id(requested: str | None, default: str) -> str:
    """Resolve the effective Bedrock model ID for this invocation.

    Resolution order:
        1. If the allowed list is empty (feature not enabled),
           ignore requested and return *default*.
        2. If requested is in the allowed list, use it.
        3. Otherwise, use *default* (log warning if requested was present but stale).
    """
    if not _ALLOWED_MODEL_IDS:
        if requested:
            logger.warning("modelId %r received but allowed list is empty; feature not enabled", requested)
        return default
    if requested and requested in _ALLOWED_MODEL_IDS:
        return requested
    if requested:
        logger.warning("Requested modelId %r not in allowed list; falling back to %r", requested, default)
    return default


_MCP_FACTORIES = [
    lambda jwt_token: mcp_agentcore_runtime(jwt_token=jwt_token),
    lambda jwt_token: mcp_aws_knowledge(),
    lambda jwt_token: mcp_aws_pricing(),
]


# ---------------------------------------------------------------------------
# Unified factory
# ---------------------------------------------------------------------------

def create_agent(mode: str, user_id: str, session_id: str, jwt_token: str, chat_model_id: str | None = None, create_model_id: str | None = None) -> tuple[Agent, list[dict]]:
    """Create a Strands Agent for the given mode.

    Returns:
        Tuple of (Configured Strands Agent, MCP status list).
    """
    cfg = MODES[mode]
    memory_id = os.environ.get("MEMORY_ID", "")
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

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

    # Models — agent uses chat or create model depending on mode
    if cfg.agent_model == "create":
        requested_agent = create_model_id
        default_agent = _DEFAULT_CREATE_MODEL_ID
    else:
        requested_agent = chat_model_id
        default_agent = _DEFAULT_CHAT_MODEL_ID
    resolved_agent = _resolve_model_id(requested_agent, default_agent)
    model = BedrockModel(**build_model_kwargs(resolved_agent))

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
    tools = [*mcp_servers, web_fetch, hearing]
    composer_mcp_factory = None
    if cfg.use_composer:
        resolved_create = _resolve_model_id(create_model_id, _DEFAULT_CREATE_MODEL_ID)
        profile = MODEL_PROFILES.get(resolved_create)
        if profile and not profile.compose_capable:
            logger.warning("Model %r is not compose_capable; falling back to %r for create", resolved_create, _DEFAULT_CREATE_MODEL_ID)
            resolved_create = _DEFAULT_CREATE_MODEL_ID
        composer_model = BedrockModel(
            **build_model_kwargs(resolved_create),
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
        tools = [*mcp_servers, web_fetch, hearing]
        if cfg.use_composer:
            compose_slides = make_compose_slides(mcp_servers, composer_model, composer_mcp_factory)
            tools.append(compose_slides)
        agent = Agent(
            name=agent_name, system_prompt="", tools=tools, model=model,
            session_manager=session_manager,
            trace_attributes={"user.id": user_id, "session.id": session_id},
        )

    # Prompts + history (parts-based)
    context = {"mcp_instructions": collect_mcp_instructions(mcp_servers)}

    try:
        system_prompt, initial_messages = resolve_parts(
            cfg.parts,
            mcp_client=mcp_servers[0] if mcp_servers else None,
            context=context,
        )
    except Exception as e:
        logger.warning("Prompt resolve failed: %s", e)
        system_prompt, initial_messages = "", []

    # Apply to agent
    has_history = bool(initial_messages)
    if has_history and len(agent.messages) == 0:
        agent.messages.extend(initial_messages)
    agent.system_prompt = system_prompt

    # LoopGuard
    guard = LoopGuard(max_tool_calls=int(os.environ.get("SPEC_MAX_TOOL_CALLS", "300")))
    agent.hooks.add_callback(AfterToolCallEvent, guard.after_tool)

    # Cost logger
    agent.hooks.add_callback(AfterInvocationEvent, log_usage)

    fix_excess_tool_results(agent.messages)

    return agent, mcp_status
