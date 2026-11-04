# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A session's MCP clients, Agent and Memory session manager, kept across its turns.

Building them per turn cost a warm second message about 2.5 s on dev (2026-11-03):
three MCP connections, the Memory session manager and one start_presentation call.
A SessionHandle builds them once per session and reuses them:

- The Presentation Maker client(s), one per tool allowlist, carry the session's
  TokenHolder (the JWT is swapped per turn, token_holder.py) and one shared ``_meta``
  dict that holds the current turn's write-fence generation (turn_fence.py). A client
  whose MCP session ended is restarted in place (mcp_clients.ReconnectingMCPClient).
- One Agent for the current (mode, chat model, create model). A change rebuilds the
  Agent with a new Memory session manager (Strands binds a session manager to one
  Agent); spec and vibe share the Presentation Maker client (same allowlist).
- The Memory session manager is created at the first prompt, never by prepare, so a
  session that is only prepared writes nothing to Memory.
- The handle is bound to its owner's ``sub``: a turn with another user's token is
  refused (TokenHolder).

Per turn, the Agent's hooks act on the turn's own objects (write fence, LoopGuard,
stop event), and the system prompt is refreshed (``{now}``). A cancelled turn leaves
the handle as it is; close() (idle sweep, SIGTERM) releases the clients.

Background compose (background.py): the Agent owns its tasks, so while it has any (running,
or settled and not delivered yet) a turn keeps it even if it asks for another mode or model.
The handle records the decks the tasks work on (``task_decks``, fenced when the work is
stopped) and passes the tasks' progress (``on_background_event``) and delivered results
(``on_task_end``) to the session.
"""

import contextvars
import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait

import background
import factory
from modes import MODES
from resilience import LoopGuard
from steer_inbox import Inbox, SteerInbox
from token_holder import TokenHolder
from turn_fence import GENERATION_META_KEY, TurnFence

logger = logging.getLogger("sdpm.agent")

# Consumer id the handle holds on its Presentation Maker clients, so rebuilding the
# Agent (whose cleanup removes its own consumer) never stops them.
_HANDLE_CONSUMER = "sdpm-session"


def _alive(client) -> bool:
    alive = getattr(client, "alive", None)
    return alive() if callable(alive) else True


class SessionHandle:
    """What one session keeps between its turns (see the module docstring)."""

    def __init__(self, session_id: str, sub: str):
        self.session_id = session_id
        self.sub = sub
        self.holder: TokenHolder | None = None
        # _meta of every Presentation Maker client of the session; the turn's
        # generation is written here at its start.
        self.meta: dict = {}
        self.inbox = Inbox()
        # Called with (items, how) when SteerInbox delivers steers (session_runtime).
        self.on_steer_delivered = None
        self.turn_fence: TurnFence | None = None
        self.loop_guard: LoopGuard | None = None
        self.stop: threading.Event | None = None
        # Decks of the background tasks dispatched since the tasks last settled.
        self.task_decks: set[str] = set()
        # Called with each background toolStream event, and with each task snapshot
        # Strands delivers into the history (session_runtime).
        self.on_background_event = None
        self.on_task_end = None
        self.last_used = time.monotonic()
        self.closed = False
        self._lock = threading.RLock()
        # Held while clients connect or an Agent is built: prepare and a turn's start
        # never connect the same client twice at once.
        self._build_lock = threading.Lock()
        self._pm: dict[tuple, object] = {}
        self._models: dict[tuple, object] = {}
        self._agent = None
        self._agent_key: tuple | None = None
        self._agent_clients: list = []
        self._prepared: Future | None = None

    # -- identity ---------------------------------------------------------------

    def update_token(self, token: str) -> None:
        """Use ``token`` for the session's MCP requests from now on (PermissionError for
        another user's token)."""
        with self._lock:
            if self.holder is None:
                self.holder = TokenHolder(self.sub, token)
            else:
                self.holder.set(token)

    # -- parts the factory asks for ---------------------------------------------

    def pm_client(self, cfg):
        """The session's Presentation Maker client for ``cfg``'s allowlist (restarted if
        its MCP session ended)."""
        key = tuple(cfg.allowed_tools or ())
        with self._lock:
            client = self._pm.get(key)
            if client is None:
                filters = {"allowed": cfg.allowed_tools} if cfg.allowed_tools else None
                client = factory._MCP_FACTORIES[0](
                    "", session_id=self.session_id, tool_filters=filters, meta=self.meta, token=self.holder,
                )
                client.add_consumer(_HANDLE_CONSUMER)
                self._pm[key] = client
                return client
        if not _alive(client):
            client.restart()
        return client

    def model(self, model_id: str, composer: bool = False):
        key = (model_id, composer)
        with self._lock:
            model = self._models.get(key)
            if model is None:
                model = self._models[key] = factory.build_model(model_id, composer=composer)
            return model

    def steer_plugin(self) -> SteerInbox:
        return SteerInbox(self.inbox, self.stopped, self._steer_delivered)

    def stopped(self) -> bool:
        stop = self.stop
        return stop is not None and stop.is_set()

    def _steer_delivered(self, items, how: str) -> None:
        callback = self.on_steer_delivered
        if callback is not None:
            callback(items, how)

    # Hooks of the Agent: they act on the current turn's objects.

    def note_tool_call(self, event) -> None:
        fence = self.turn_fence
        if fence is not None:
            fence.note_tool_call(event)

    def after_tool(self, event) -> None:
        guard = self.loop_guard
        if guard is not None:
            guard.after_tool(event)

    def note_task_dispatch(self, event) -> None:
        """BeforeToolCallEvent hook: remember the deck a background tool call works on."""
        if event.tool_use.get("name") not in background.BACKGROUND_TOOLS:
            return
        tool_input = event.tool_use.get("input")
        deck_id = tool_input.get("deck_id") if isinstance(tool_input, dict) else None
        if isinstance(deck_id, str) and deck_id.strip():
            with self._lock:
                self.task_decks.add(deck_id.strip())

    def note_delivery(self, event) -> None:
        """MessageAddedEvent hook: a message that delivers background results."""
        callback = self.on_task_end
        if callback is None:
            return
        for task in background.delivered(event.message):
            callback(task)

    def on_agent_callback(self, **kwargs) -> None:
        """The Agent's callback handler: a background task's progress goes to the session
        (a foreground tool's reaches it through stream_agent)."""
        stream_event = kwargs.get("tool_stream_event")
        callback = self.on_background_event
        if not isinstance(stream_event, dict) or callback is None:
            return
        tool_use = stream_event.get("tool_use") or {}
        data = stream_event.get("data")
        if tool_use.get("name") in background.BACKGROUND_TOOLS and isinstance(data, dict):
            callback({"toolStream": {"toolUseId": tool_use.get("toolUseId", ""), "name": tool_use["name"], "data": data}})

    @property
    def agent(self):
        """The session's current Agent (None before its first turn)."""
        return self._agent

    def fence_client(self):
        """The orchestrator's Presentation Maker client (for a fence call), or None."""
        with self._lock:
            return self._agent_clients[0] if self._agent_clients else None

    # -- prepare ----------------------------------------------------------------

    def prepare(self, token: str, mode: str = "spec", chat_model_id: str | None = None,
                create_model_id: str | None = None) -> Future:
        """Connect the clients, fetch the system-prompt sources and build the models,
        on a thread. No Memory session manager, no Agent (nothing is written).

        Idempotent; the Future resolves to the MCP status list.
        """
        self.update_token(token)
        with self._lock:
            if self._prepared is not None and not (self._prepared.done() and self._prepared.exception()):
                return self._prepared
            future: Future = Future()
            self._prepared = future
        cfg = MODES[mode]

        def run() -> None:
            try:
                with self._build_lock:
                    model_ids = factory.resolve_models(cfg, chat_model_id, create_model_id)
                    self.model(model_ids[0])
                    if model_ids[1] is not None:
                        self.model(model_ids[1], composer=True)
                    _, status = factory.connect_clients(self, cfg)
                future.set_result(status)
            except BaseException as e:  # noqa: BLE001 - delivered through the future
                logger.warning("Prepare failed for session %s: %s", self.session_id[:12], e)
                future.set_exception(e)

        threading.Thread(target=contextvars.copy_context().run, args=(run,), daemon=True, name="sdpm-prepare").start()
        return future

    # -- turns ------------------------------------------------------------------

    def begin_turn(self, token: str, fence: TurnFence | None, mode: str = "spec",
                   chat_model_id: str | None = None, create_model_id: str | None = None,
                   stop: threading.Event | None = None) -> tuple:
        """Make the session ready for a turn and return (Agent, MCP status). Blocking.

        Raises PermissionError when ``token`` belongs to another user.
        """
        if self.closed:
            raise RuntimeError("session handle is closed")
        self.update_token(token)
        cfg = MODES[mode]
        with self._lock:
            self.meta.pop(GENERATION_META_KEY, None)
            if fence is not None:
                self.meta.update(fence.meta)
            self.turn_fence = fence
            self.stop = stop
            self.loop_guard = LoopGuard(max_tool_calls=int(os.environ.get("SPEC_MAX_TOOL_CALLS", "300")))
            self.last_used = time.monotonic()

        with self._build_lock:
            model_ids = factory.resolve_models(cfg, chat_model_id, create_model_id)
            key = (mode, *model_ids)
            # The Agent owns its background tasks: a rebuilt one would restore them as failed.
            keep = self._agent is not None and bool(background.tasks(self._agent))
            if keep and self._agent_key != key:
                logger.info("Session %s: keeping %s while its background tasks are open (asked for %s)",
                            self.session_id[:12], self._agent_key, key)
                key = self._agent_key
                mode, model_ids = key[0], tuple(key[1:])
                cfg = MODES[mode]
            new_agent = self._agent is None or self._agent_key != key
            memory = self._start_session_manager() if new_agent else None
            try:
                mcp_servers, mcp_status = factory.connect_clients(
                    self, cfg, then=(lambda: wait([memory])) if memory is not None else None,
                )
            except BaseException:
                if memory is not None:
                    memory.cancel()
                raise
            if not new_agent and not keep and self._stale(mcp_servers):
                # A resident client was replaced (its server died): the Agent's tools
                # point at the old one.
                new_agent, memory = True, self._start_session_manager()
            if new_agent:
                session_manager = memory.result()
                self._retire_agent()
                agent, clients, mcp_status = factory.assemble_agent(
                    self, cfg, mode, model_ids, mcp_servers, mcp_status, session_manager,
                )
                with self._lock:
                    self._agent, self._agent_key, self._agent_clients = agent, key, clients
            else:
                agent = self._agent
                self._add_clients(agent, mcp_servers)
            factory.refresh_prompt(self, cfg, agent, model_ids[0], self._agent_clients)

        if fence is not None:
            fence.bind(self._agent_clients[0] if self._agent_clients else None)
            if background.pending(agent):
                # A stop during this turn fences the decks the running tasks write too.
                with self._lock:
                    fence.note_decks(list(self.task_decks))
        return agent, mcp_status

    def end_turn(self) -> None:
        with self._lock:
            self.turn_fence = None
            self.loop_guard = None
            self.stop = None
            self.last_used = time.monotonic()

    def _start_session_manager(self) -> Future:
        # Built next to the MCP connections (its constructor reads Memory, ~0.4 s on dev).
        # The context copy keeps its Memory calls under this request's trace.
        side = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sdpm-memory")
        memory_id = os.environ.get("MEMORY_ID", "")
        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        future = side.submit(
            contextvars.copy_context().run, factory._session_manager, memory_id, self.session_id, self.sub, region,
        )
        side.shutdown(wait=False)
        return future

    def _stale(self, mcp_servers: list) -> bool:
        """True when a client the Agent uses is no longer among the usable ones."""
        return any(not any(c is s for s in mcp_servers) for c in self._agent_clients)

    def _add_clients(self, agent, mcp_servers: list) -> None:
        """Give the Agent a resident client that connected after it was built."""
        for client in mcp_servers:
            if any(client is c for c in self._agent_clients):
                continue
            try:
                agent.tool_registry.process_tools([client])
            except Exception as e:  # noqa: BLE001 - the turn runs without that server
                logger.warning("Adding a late MCP client to the session's agent failed: %s", e)
                continue
            self._agent_clients.append(client)

    def _retire_agent(self) -> None:
        with self._lock:
            agent, self._agent, self._agent_key, self._agent_clients = self._agent, None, None, []
        if agent is not None:
            try:
                agent.cleanup()  # removes the Agent's consumer only; the handle's stays
            except Exception as e:  # noqa: BLE001 - best effort
                logger.warning("Cleaning up the session's previous agent failed: %s", e)

    # -- lifetime ---------------------------------------------------------------

    def release_clients(self) -> None:
        """Drop the handle's hold on its Presentation Maker clients (they stop once no
        Agent or fence call uses them)."""
        with self._lock:
            clients = list(self._pm.values())
            self._pm.clear()
        for client in clients:
            try:
                client.remove_consumer(_HANDLE_CONSUMER)
            except Exception as e:  # noqa: BLE001 - best effort
                logger.warning("Releasing a Presentation Maker client failed: %s", e)

    def close(self) -> None:
        """Release the Agent and the Presentation Maker clients (resident clients are the
        process's). A fence call still running keeps its client until it is sent."""
        with self._lock:
            if self.closed:
                return
            self.closed = True
        self._retire_agent()
        self.release_clients()

