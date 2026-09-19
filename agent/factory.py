# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unified agent factory: assembles MCP clients, model, tools, and prompt into a Strands Agent."""

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

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
from message_hooks import LiftToolResultImages
from model_profiles import build_model_kwargs, MODEL_PROFILES
from modes import MODES
from modes.composer import make_compose_slides
from resilience import LoopGuard
from session import fix_excess_tool_results
from tools.hearing_tool import hearing
from tools.web_tools import web_fetch

logger = logging.getLogger("sdpm.agent")

_ALLOWED_MODEL_IDS: set[str] = set(json.loads(os.environ.get("ALLOWED_MODEL_IDS", "[]")))
_DEFAULT_CHAT_MODEL_ID: str = os.environ.get("CHAT_MODEL_ID", "global.anthropic.claude-sonnet-5")
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
    lambda jwt_token, session_id="", tool_filters=None: mcp_agentcore_runtime(jwt_token=jwt_token, session_id=session_id, tool_filters=tool_filters),
    lambda jwt_token, session_id="", tool_filters=None: mcp_aws_knowledge(),
    lambda jwt_token, session_id="", tool_filters=None: mcp_aws_pricing(),
]


def _prewarm_mcp_clients(clients: list, names: list[str], required: list[bool]) -> tuple[list, list[dict]]:
    """Connect the MCP clients concurrently and drop the optional ones that fail.

    Strands connects MCP servers serially: `ToolRegistry.process_tools()` iterates
    the tools list and blocks on `await provider.load_tools()` for each
    ToolProvider in turn. With three servers — one on AgentCore and two AWS ones
    pinned to us-east-1 — that put roughly 2.6s of cross-region handshakes on the
    critical path of every request, in series behind each other.

    `load_tools()` is the public ToolProvider entry point and caches its result in
    the client, so calling it here first means Strands' own call is a cache hit.
    Running those calls in a thread pool collapses the handshakes into the slowest
    one instead of their sum.

    It also makes the `required` flag in MCP_DEFS mean something. The flag was only
    ever guarding client *construction*, which is lazy and cannot fail, so a
    failure to reach an optional server surfaced later inside Strands as a hard
    `ValueError` from process_tools (MCPClient defaults to
    `continue_on_error=False`). Connecting here lets an optional server be dropped
    with a status entry, which is what the flag always claimed to do.

    Returns:
        (clients that are usable, status entries per server)
    """
    results: dict[int, BaseException | None] = {}

    def connect(index: int) -> None:
        try:
            # asyncio.run rather than Strands' run_async: that helper lives in the
            # private strands._async module, and each worker thread here has no
            # running loop of its own. load_tools() does its work synchronously
            # inside (the MCP session itself runs on the client's own background
            # thread), so a throwaway loop per thread is enough.
            asyncio.run(clients[index].load_tools())
            results[index] = None
        except BaseException as e:  # noqa: BLE001 - recorded per client below
            results[index] = e

    if clients:
        with ThreadPoolExecutor(max_workers=len(clients)) as pool:
            list(pool.map(connect, range(len(clients))))

    usable: list = []
    status: list[dict] = []
    for i, client in enumerate(clients):
        error = results.get(i)
        if error is None:
            usable.append(client)
            status.append({"name": names[i], "status": "ok"})
            continue
        logger.warning("MCP server %r failed to connect: %s", names[i], error)
        status.append({"name": names[i], "status": "error", "error": str(error)})
        if required[i]:
            raise error
    return usable, status


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
    # MCP servers — built lazily here, then connected concurrently below.
    built = []
    names = []
    required_flags = []
    for i, ((name, required), factory_fn) in enumerate(zip(MCP_DEFS, _MCP_FACTORIES)):
        # Apply tool_filters only to the Presentation Maker server (index 0)
        filters = {"allowed": cfg.allowed_tools} if (i == 0 and cfg.allowed_tools) else None
        built.append(factory_fn(jwt_token, session_id=session_id, tool_filters=filters))
        names.append(name)
        required_flags.append(required)
    mcp_servers, mcp_status = _prewarm_mcp_clients(built, names, required_flags)

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
        composer_mcp_factory = lambda mcp_session_id="": mcp_agentcore_runtime(jwt_token=jwt_token, session_id=mcp_session_id)  # noqa: E731
        compose_slides = make_compose_slides(mcp_servers, composer_model, composer_mcp_factory, extra_tools=[web_fetch], model_id=resolved_create, user_id=user_id, session_id=session_id)
        tools.append(compose_slides)

    # Agent
    agent_name = f"Sdpm{mode.capitalize()}Agent"
    agent_trace_attributes = {
        "user.id": user_id, "session.id": session_id,
        "model.id": resolved_agent, "purpose": cfg.agent_model,
    }
    try:
        agent = Agent(
            name=agent_name, system_prompt="", tools=tools, model=model,
            session_manager=session_manager,
            trace_attributes=agent_trace_attributes,
            hooks=[LiftToolResultImages()],
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
            compose_slides = make_compose_slides(mcp_servers, composer_model, composer_mcp_factory, extra_tools=[web_fetch], model_id=resolved_create, user_id=user_id, session_id=session_id)
            tools.append(compose_slides)
        agent = Agent(
            name=agent_name, system_prompt="", tools=tools, model=model,
            session_manager=session_manager,
            trace_attributes=agent_trace_attributes,
            hooks=[LiftToolResultImages()],
        )

    # Prompts + history (parts-based)
    context = {"mcp_instructions": collect_mcp_instructions(mcp_servers)}

    try:
        profile = MODEL_PROFILES.get(resolved_agent)
        enable_cache = (profile.cache_strategy == "auto") if profile else True
        system_prompt, initial_messages = resolve_parts(
            cfg.parts,
            mcp_client=mcp_servers[0] if mcp_servers else None,
            context=context,
            enable_cache=enable_cache,
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

    # Tool filter validation: an allowlist entry that matches no loaded tool
    # silently disappears (e.g. after a server-side rename). Surface it.
    if cfg.allowed_tools:
        try:
            loaded = set(agent.tool_names)
            stale = [t for t in cfg.allowed_tools if t not in loaded]
            if stale:
                logger.warning("allowed_tools entries not found on MCP server (renamed or removed?): %s", stale)
        except Exception as e:
            logger.warning("tool filter validation skipped: %s", e)

    fix_excess_tool_results(agent.messages)

    return agent, mcp_status
