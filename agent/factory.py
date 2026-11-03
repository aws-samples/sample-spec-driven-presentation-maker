# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unified agent factory: assembles MCP clients, model, tools, and prompt into a Strands Agent."""

import asyncio
import contextvars
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable

from botocore.config import Config as BotocoreConfig
from strands import Agent
from strands.hooks.events import AfterInvocationEvent, AfterToolCallEvent, BeforeToolCallEvent
from strands.models import BedrockModel

from cost_logger import log_usage
from mcp_clients import (
    MCP_DEFS,
    ResidentClient,
    collect_mcp_instructions,
    mcp_agentcore_runtime,
    mcp_aws_knowledge,
    mcp_aws_pricing,
    resident_client,
)
from composition import prefetch_sources, resolve_parts
from message_hooks import LiftToolResultImages
from model_profiles import build_model_kwargs, MODEL_PROFILES
from modes import MODES
from modes.composer import make_compose_slides
from resilience import LoopGuard, gate_tool_call
from session import fix_excess_tool_results
from turn_fence import TurnFence
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
    lambda jwt_token, session_id="", tool_filters=None, **kwargs: mcp_agentcore_runtime(jwt_token=jwt_token, session_id=session_id, tool_filters=tool_filters, **kwargs),
    lambda jwt_token, session_id="", tool_filters=None: mcp_aws_knowledge(),
    lambda jwt_token, session_id="", tool_filters=None: mcp_aws_pricing(),
]

# Servers whose client uses nothing from the caller (no JWT, no session id): connected
# once per process and reused across turns (mcp_clients.ResidentClient). On dev a warm
# Presentation Maker reconnect (~1.0s) finished before AWS Pricing's stdio start
# (~1.45s), so a per-turn Pricing client missed the deadline on nearly every warm turn.
_RESIDENT_SERVERS = {"AWS Knowledge", "AWS Pricing"}


# Status error for an optional server that was still connecting at the deadline.
_LATE_ERROR = "Not connected in time; skipped for this turn"

# Test seam: called with each client once its worker has recorded the connection
# result (or closed the client as late). Tests use it to order clients without sleeps.
_on_recorded: Callable[[object], None] | None = None


def _prewarm_mcp_clients(
    clients: list,
    names: list[str],
    required: list[bool],
    then: Callable[[list], None] | None = None,
) -> tuple[list, list[dict]]:
    """Connect the MCP clients concurrently and drop the optional ones that fail or are late.

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

    Optional servers also get a deadline: the moment the required servers are up
    and *then* has returned. *then* runs on the calling thread with the connected
    required clients (in input order) while the optional ones are still connecting,
    so the caller can do its own critical-path work there. An optional server still
    connecting at the deadline is dropped for this turn; on dev the AWS Pricing stdio
    server (about 1.4s) was the slowest part of a warm turn's assembly (2026-11-03).

    An entry may be a ResidentClient. Its connection outlives the turn: one that is
    late keeps connecting and serves the next turn, and one already connected is used
    even if its liveness check is still running at the deadline. Any other late
    client is closed once its connection finishes, since no agent consumes it.

    Returns:
        (clients that are usable, status entries per server)
    """
    results: dict[int, tuple[object, BaseException | None]] = {}
    lock = threading.Lock()
    deadline = threading.Event()

    def connect(index: int) -> None:
        target = clients[index]
        resident = isinstance(target, ResidentClient)
        client, error = None, None
        try:
            if resident:
                client = target.connect()
            else:
                # asyncio.run rather than Strands' run_async: that helper lives in the
                # private strands._async module, and each worker thread here has no
                # running loop of its own. load_tools() does its work synchronously
                # inside (the MCP session itself runs on the client's own background
                # thread), so a throwaway loop per thread is enough.
                asyncio.run(target.load_tools())
                client = target
        except BaseException as e:  # noqa: BLE001 - recorded per client below
            error = e
        with lock:
            on_time = required[index] or not deadline.is_set()
            if on_time:
                results[index] = (client, error)
        # Dropped at the deadline: no agent consumes this client, so close it here.
        if not on_time and not resident and error is None:
            try:
                target.stop(None, None, None)
            except Exception as e:  # noqa: BLE001 - best-effort cleanup off the request path
                logger.warning("MCP server %r: closing the late client failed: %s", names[index], e)
        if _on_recorded is not None:
            _on_recorded(target)

    pool = ThreadPoolExecutor(max_workers=len(clients), thread_name_prefix="sdpm-mcp") if clients else None
    try:
        futures = [pool.submit(connect, i) for i in range(len(clients))] if pool else []
        wait([f for f, req in zip(futures, required) if req])
        for i, req in enumerate(required):
            if req and results[i][1] is not None:
                logger.warning("MCP server %r failed to connect: %s", names[i], results[i][1])
                raise results[i][1]
        if then is not None:
            then([results[i][0] for i, req in enumerate(required) if req])
    finally:
        with lock:
            deadline.set()
            outcome = dict(results)
        if pool is not None:
            pool.shutdown(wait=False)

    usable: list = []
    status: list[dict] = []
    for i, target in enumerate(clients):
        if i not in outcome:
            kept = target.connected if isinstance(target, ResidentClient) else None
            if kept is not None:
                # Connected in an earlier turn; only its liveness check is still running.
                usable.append(kept)
                status.append({"name": names[i], "status": "ok"})
                continue
            logger.warning("MCP server %r dropped for this turn: still connecting at the deadline", names[i])
            status.append({"name": names[i], "status": "error", "error": _LATE_ERROR})
            continue
        client, error = outcome[i]
        if error is None:
            usable.append(client)
            status.append({"name": names[i], "status": "ok"})
            continue
        logger.warning("MCP server %r failed to connect: %s", names[i], error)
        status.append({"name": names[i], "status": "error", "error": str(error)})
    return usable, status


def _session_manager(memory_id: str, session_id: str, user_id: str, region: str):
    """AgentCore Memory session manager, or None when Memory is not configured.

    Its constructor reads (and for a new session writes) Memory, about 0.4s on dev,
    so create_agent builds it next to the MCP connections.
    """
    if not memory_id or memory_id == "PLACEHOLDER":
        return None
    from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
    from stop_guard import GatedMemorySessionManager  # drops events once SIGTERM closed the gate
    return GatedMemorySessionManager(
        agentcore_memory_config=AgentCoreMemoryConfig(
            memory_id=memory_id, session_id=session_id, actor_id=user_id,
        ),
        region_name=region,
    )


# ---------------------------------------------------------------------------
# Unified factory
# ---------------------------------------------------------------------------

def create_agent(mode: str, user_id: str, session_id: str, jwt_token: str, chat_model_id: str | None = None, create_model_id: str | None = None, fence: TurnFence | None = None) -> tuple[Agent, list[dict]]:
    """Create a Strands Agent for the given mode.

    ``fence`` (turn_fence.py): its generation goes into the ``_meta`` of every
    Presentation Maker call (orchestrator and composers), and it learns the decks the
    turn's tool calls name.

    Returns:
        Tuple of (Configured Strands Agent, MCP status list).
    """
    cfg = MODES[mode]
    memory_id = os.environ.get("MEMORY_ID", "")
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

    # Session manager — built on a side thread while the MCP servers connect. The
    # context copy keeps its Memory calls under this request's trace.
    side = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sdpm-memory")
    session_manager_future = side.submit(
        contextvars.copy_context().run, _session_manager, memory_id, session_id, user_id, region,
    )
    side.shutdown(wait=False)

    # Models — agent uses chat or create model depending on mode
    if cfg.agent_model == "create":
        requested_agent = create_model_id
        default_agent = _DEFAULT_CREATE_MODEL_ID
    else:
        requested_agent = chat_model_id
        default_agent = _DEFAULT_CHAT_MODEL_ID
    resolved_agent = _resolve_model_id(requested_agent, default_agent)
    model = BedrockModel(**build_model_kwargs(resolved_agent))

    # MCP servers — Presentation Maker built per turn (it carries the JWT), AWS
    # Knowledge / AWS Pricing reused from the process; all connected concurrently below.
    fence_kwargs = {"meta": fence.meta} if fence is not None else {}
    built = []
    names = []
    required_flags = []
    for i, ((name, required), factory_fn) in enumerate(zip(MCP_DEFS, _MCP_FACTORIES)):
        if name in _RESIDENT_SERVERS:
            built.append(resident_client(name, lambda make=factory_fn: make("")))
        else:
            # Apply tool_filters only to the Presentation Maker server (index 0)
            filters = {"allowed": cfg.allowed_tools} if (i == 0 and cfg.allowed_tools) else None
            built.append(factory_fn(jwt_token, session_id=session_id, tool_filters=filters, **fence_kwargs))
        names.append(name)
        required_flags.append(required)

    def critical_path(required_clients: list) -> None:
        # Runs as soon as the Presentation Maker client is up, while the optional
        # servers are still connecting: start_presentation (the system-prompt
        # sources) goes first, then the Memory session manager is awaited. The
        # optional servers' deadline is the end of this function.
        try:
            prefetch_sources(cfg.parts, required_clients[0] if required_clients else None, user_id=user_id)
        except Exception as e:
            logger.warning("Prompt prefetch failed: %s", e)
        wait([session_manager_future])

    mcp_servers, mcp_status = _prewarm_mcp_clients(built, names, required_flags, then=critical_path)
    try:
        session_manager = session_manager_future.result()
    except Exception:
        # Memory failed after the servers connected: no agent will own this turn's
        # clients. Resident ones stay for the next turn.
        per_turn = [c for c in built if not isinstance(c, ResidentClient)]
        for client in mcp_servers:
            if not any(client is c for c in per_turn):
                continue
            try:
                client.stop(None, None, None)
            except Exception as e:  # noqa: BLE001 - best-effort cleanup before re-raising
                logger.warning("Closing an MCP client after the Memory failure failed: %s", e)
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
        # Composers get their own Presentation Maker client per group; it carries the
        # composer allowlist so a composer sees only the deck tools.
        composer_filters = {"allowed": MODES["composer"].allowed_tools}
        composer_mcp_factory = lambda mcp_session_id="": mcp_agentcore_runtime(jwt_token=jwt_token, session_id=mcp_session_id, tool_filters=composer_filters, **fence_kwargs)  # noqa: E731
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
            user_id=user_id,
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

    # Write gate: no tool runs once the process is stopping (SIGTERM, stop_guard.py)
    agent.hooks.add_callback(BeforeToolCallEvent, gate_tool_call)

    # Write fence: the decks this turn touches, and the client that fences them on a stop
    if fence is not None:
        agent.hooks.add_callback(BeforeToolCallEvent, fence.note_tool_call)
        fence.bind(mcp_servers[0] if mcp_servers else None)

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
