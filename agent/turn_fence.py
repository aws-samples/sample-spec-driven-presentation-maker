# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The agent's half of the MCP write fence (servers/remote/storage/write_fence.py).

Stopping a turn does not stop the Presentation Maker calls it has already sent: they
keep running on the MCP runtime and write to S3 afterwards. So each turn:
  - mints a generation (wall-clock nanoseconds at the start of the turn: a later turn,
    in this process or in a new microVM, always gets a larger one) and sends it in the
    ``_meta`` of every Presentation Maker call, the orchestrator's, the composers' and
    compose_slides' direct ones (``meta``, set on each MCP client);
  - records the decks its tool calls name (``note_tool_call``, a BeforeToolCallEvent hook);
  - when it is stopped (``advance``: cancel, a newer request, the client going away,
    SIGTERM), calls ``fence_turn`` with those decks. The server then skips every write
    the stopped turn's calls still make to them.

A turn that ends normally fences nothing, so the background work of its last calls
(previews after generate_pptx) still lands.
"""

import logging
import threading
import time
import uuid

logger = logging.getLogger("sdpm.agent")

GENERATION_META_KEY = "sdpm/generation"  # same key as the server's write_fence
FENCE_TOOL = "fence_turn"

# Consumer id held on the turn's Presentation Maker client until the fence call is done,
# so the Agent's cleanup does not stop the client under it.
_CONSUMER = "sdpm-turn-fence"


class TurnFence:
    """One turn's generation, the decks it touched, and the call that fences them."""

    def __init__(self, generation: int | None = None):
        self.generation = generation if generation is not None else time.time_ns()
        # Re-entrant: advance() also runs from the SIGTERM handler on the main thread,
        # which may be inside note_tool_call (hooks run on the event loop's thread).
        self._lock = threading.RLock()
        self._decks: set[str] = set()
        self._client = None
        self._done = False

    @property
    def meta(self) -> dict:
        """The ``_meta`` entry for this turn's MCP calls."""
        return {GENERATION_META_KEY: self.generation}

    @property
    def decks(self) -> list[str]:
        with self._lock:
            return sorted(self._decks)

    def bind(self, client) -> None:
        """Use ``client`` (the turn's Presentation Maker MCPClient) for the fence call."""
        with self._lock:
            if self._done or client is None:
                return
            client.add_consumer(_CONSUMER)
            self._client = client

    def note_tool_call(self, event) -> None:
        """BeforeToolCallEvent hook: remember the deck a tool call names."""
        tool_input = event.tool_use.get("input")
        deck_id = tool_input.get("deck_id") if isinstance(tool_input, dict) else None
        if isinstance(deck_id, str) and deck_id.strip():
            with self._lock:
                self._decks.add(deck_id.strip())

    def note_decks(self, decks) -> None:
        """Remember decks the turn did not name itself (those of the session's running
        background tasks), so a stop fences them too."""
        with self._lock:
            self._decks.update(d.strip() for d in decks if isinstance(d, str) and d.strip())

    def advance(self) -> threading.Thread | None:
        """The turn was stopped: fence its decks (once). The call runs on a daemon thread,
        so this is safe from a signal handler and from the event loop; returns it (for
        stop_guard.hold, so a shutting-down process waits for it)."""
        return self._finish(fence=True)

    def release(self) -> None:
        """The turn ended without a stop: nothing to fence, let the client go."""
        self._finish(fence=False)

    def _finish(self, fence: bool) -> threading.Thread | None:
        with self._lock:
            if self._done:
                return None
            self._done = True
            client, decks = self._client, sorted(self._decks)
            self._client = None
        if client is None:
            return None
        thread = threading.Thread(
            target=self._send, args=(client, decks if fence else []), daemon=True, name="sdpm-turn-fence",
        )
        thread.start()
        return thread

    def _send(self, client, decks: list[str]) -> None:
        try:
            if decks:
                # Not through call_tool_with_retry: this is the one call made after the
                # write gate closed. The generation goes with the call itself: the
                # client's meta is the session's (session_handle.py) and holds the next
                # turn's generation once that turn has started.
                result = client.call_tool_sync(
                    tool_use_id=f"fence-{uuid.uuid4().hex[:8]}", name=FENCE_TOOL, arguments={"deck_ids": decks},
                    meta=self.meta,
                )
                if result.get("status") == "error":
                    logger.warning("write fence: fence_turn failed for %s: %s", decks, result.get("content"))
                else:
                    logger.info("write fence: fenced generation %s for %s", self.generation, decks)
        except Exception as e:  # noqa: BLE001 - best effort; the turn is over either way
            logger.warning("write fence: fence_turn for %s failed: %s", decks, e)
        finally:
            try:
                client.remove_consumer(_CONSUMER)
            except Exception as e:  # noqa: BLE001 - best-effort cleanup
                logger.warning("write fence: releasing the MCP client failed: %s", e)
