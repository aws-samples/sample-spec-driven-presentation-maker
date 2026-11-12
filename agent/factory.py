# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unified agent factory: assembles MCP clients, model, tools, and prompt into a Strands Agent."""

import asyncio
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

import background
from compose_messaging import make_message_composer
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
from resilience import gate_tool_call
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
    so the session handle builds it next to the MCP connections, at the first prompt.
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
# Building blocks of a session (session_handle.SessionHandle calls them through
# this module, so tests can patch them here)
# ---------------------------------------------------------------------------

def resolve_models(cfg, chat_model_id: str | None, create_model_id: str | None) -> tuple[str, str | None]:
    """(the agent's model id, the composers' model id or None) for a mode."""
    if cfg.agent_model == "create":
        resolved_agent = _resolve_model_id(create_model_id, _DEFAULT_CREATE_MODEL_ID)
    else:
        resolved_agent = _resolve_model_id(chat_model_id, _DEFAULT_CHAT_MODEL_ID)
    resolved_create = None
    if cfg.use_composer:
        resolved_create = _resolve_model_id(create_model_id, _DEFAULT_CREATE_MODEL_ID)
        profile = MODEL_PROFILES.get(resolved_create)
        if profile and not profile.compose_capable:
            logger.warning("Model %r is not compose_capable; falling back to %r for create", resolved_create, _DEFAULT_CREATE_MODEL_ID)
            resolved_create = _DEFAULT_CREATE_MODEL_ID
    return resolved_agent, resolved_create


def connect_clients(handle, cfg, then: Callable[[], None] | None = None) -> tuple[list, list[dict]]:
    """Connect the session's MCP clients for ``cfg`` and prefetch its system-prompt sources.

    The Presentation Maker client is the handle's (kept across turns, carrying the
    session's TokenHolder); AWS Knowledge / AWS Pricing are the
    process's resident clients. A connected client costs nothing here: load_tools is a
    cache hit and a resident only runs its liveness check. ``then`` runs on the
    critical path after the prefetch (the first prompt waits there for Memory).
    """
    built, names, required_flags = [], [], []
    for i, ((name, required), factory_fn) in enumerate(zip(MCP_DEFS, _MCP_FACTORIES)):
        if name in _RESIDENT_SERVERS:
            built.append(resident_client(name, lambda make=factory_fn: make("")))
        elif i == 0:
            built.append(handle.pm_client(cfg))
        else:
            continue
        names.append(name)
        required_flags.append(required)

    def critical_path(required_clients: list) -> None:
        # Runs as soon as the Presentation Maker client is up, while the optional
        # servers are still connecting: start_presentation (the system-prompt
        # sources) goes first, then *then*. The optional servers' deadline is the
        # end of this function.
        try:
            prefetch_sources(cfg.parts, required_clients[0] if required_clients else None, user_id=handle.sub)
        except Exception as e:
            logger.warning("Prompt prefetch failed: %s", e)
        if then is not None:
            then()

    return _prewarm_mcp_clients(built, names, required_flags, then=critical_path)


# Longest silence allowed on a Bedrock stream. A model writing one large tool argument
# (a style, a slide's code) sends nothing until the argument is complete; strands'
# default of 120 s cut such turns off (2026-11-12, Opus 5.5 writing a style).
BEDROCK_READ_TIMEOUT_S = 600


def build_model(model_id: str, composer: bool = False):
    if not composer:
        return BedrockModel(
            **build_model_kwargs(model_id),
            boto_client_config=BotocoreConfig(read_timeout=BEDROCK_READ_TIMEOUT_S),
        )
    return BedrockModel(
        **build_model_kwargs(model_id),
        boto_client_config=BotocoreConfig(
            user_agent_extra="strands-agents",
            read_timeout=BEDROCK_READ_TIMEOUT_S,
            retries={"max_attempts": 5, "mode": "adaptive"},
        ),
    )


def assemble_agent(handle, cfg, mode: str, model_ids: tuple[str, str | None], mcp_servers: list, mcp_status: list[dict], session_manager) -> tuple[Agent, list, list[dict]]:
    """Build the session's Agent for one (mode, models) from connected clients.

    Its hooks act on the handle's current turn (LoopGuard), so the Agent
    serves every turn of the session until the mode or a model changes.

    With composers, compose_slides runs as a background task (background.py): the
    Agent's callback handler forwards the task's progress to the handle, and the handle
    records the results Strands delivers. The orchestrator
    also gets message_composer, and each composer report_to_orchestrator, both through the
    handle's ComposeMessaging.

    Returns:
        (Agent, the MCP clients it uses, MCP status list)
    """
    resolved_agent, resolved_create = model_ids
    user_id, session_id = handle.sub, handle.session_id
    model = handle.model(resolved_agent)

    composer_model = None
    composer_mcp_factory = None
    if cfg.use_composer:
        composer_model = handle.model(resolved_create, composer=True)
        # Composers get their own Presentation Maker client per group; it carries the
        # composer allowlist so a composer sees only the deck tools, and the session's
        # latest JWT.
        composer_filters = {"allowed": MODES["composer"].allowed_tools}

        def composer_mcp_factory(mcp_session_id: str = ""):
            return mcp_agentcore_runtime(
                session_id=mcp_session_id, tool_filters=composer_filters, token=handle.holder,
            )

    def tools_for(servers: list) -> list:
        tools = [*servers, web_fetch, hearing]
        if cfg.use_composer:
            # The list itself goes to compose_slides, so a resident client that connects
            # later in the session (add_clients) reaches the composers too.
            tools.append(make_compose_slides(servers, composer_model, composer_mcp_factory, extra_tools=[web_fetch], model_id=resolved_create, user_id=user_id, session_id=session_id, messaging=handle.compose_messaging))
            tools.append(make_message_composer(handle.compose_messaging))
        return tools

    agent_name = f"Sdpm{mode.capitalize()}Agent"
    agent_trace_attributes = {
        "user.id": user_id, "session.id": session_id,
        "model.id": resolved_agent, "purpose": cfg.agent_model,
    }

    # Only with composers: other modes keep Strands' default callback handler.
    background_kwargs = (
        {"background_tasks": background.CONFIG, "callback_handler": handle.on_agent_callback}
        if cfg.use_composer else {}
    )

    def build(servers: list) -> Agent:
        return Agent(
            name=agent_name, system_prompt="", tools=tools_for(servers), model=model,
            session_manager=session_manager,
            trace_attributes=agent_trace_attributes,
            hooks=[LiftToolResultImages()],
            plugins=[handle.steer_plugin()],
            **background_kwargs,
        )

    mcp_servers = list(mcp_servers)
    try:
        agent = build(mcp_servers)
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
        agent = build(mcp_servers)

    # LoopGuard (a new one per turn, held by the handle)
    agent.hooks.add_callback(AfterToolCallEvent, handle.after_tool)

    # Write gate: no tool runs once the process is stopping (SIGTERM, stop_guard.py)
    agent.hooks.add_callback(BeforeToolCallEvent, gate_tool_call)

    if cfg.use_composer:
        # Background compose: the model neither sees nor calls the management tool, the
        # results reach the history as <compose_result> text, and the handle learns each
        # delivered result.
        background.hide_manage_tool(agent)
        background.deliver_as_text(agent, handle.note_delivered)

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

    return agent, mcp_servers, mcp_status


def refresh_prompt(handle, cfg, agent: Agent, model_id: str, mcp_servers: list) -> None:
    """Set the turn's system prompt (``{now}``); on a new Agent also its opening history.

    The Source.mcp parts come from the process cache after the first turn, so this
    makes no MCP call then.
    """
    context = {"mcp_instructions": collect_mcp_instructions(mcp_servers)}
    try:
        profile = MODEL_PROFILES.get(model_id)
        enable_cache = (profile.cache_strategy == "auto") if profile else True
        system_prompt, initial_messages = resolve_parts(
            cfg.parts,
            mcp_client=mcp_servers[0] if mcp_servers else None,
            context=context,
            enable_cache=enable_cache,
            user_id=handle.sub,
        )
    except Exception as e:
        logger.warning("Prompt resolve failed: %s", e)
        system_prompt, initial_messages = "", []

    if initial_messages and len(agent.messages) == 0:
        agent.messages.extend(initial_messages)
    agent.system_prompt = system_prompt
    fix_excess_tool_results(agent.messages)


# ---------------------------------------------------------------------------
# Unified factory
# ---------------------------------------------------------------------------

def create_agent(mode: str, user_id: str, session_id: str, jwt_token: str, chat_model_id: str | None = None, create_model_id: str | None = None) -> tuple[Agent, list[dict]]:
    """Create a Strands Agent for one turn of the given mode (a one-shot session handle).

    The agent entry keeps a SessionHandle per session instead (session_runtime.py);
    this builds one, takes its first turn's Agent and leaves the clients to that Agent.

    Returns:
        Tuple of (Configured Strands Agent, MCP status list).
    """
    from session_handle import SessionHandle

    handle = SessionHandle(session_id, user_id)
    try:
        agent, mcp_status = handle.begin_turn(jwt_token, mode, chat_model_id, create_model_id)
    except BaseException:
        handle.close()
        raise
    handle.release_clients()
    return agent, mcp_status
