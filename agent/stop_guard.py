# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""SIGTERM guard: a stopped microVM ends its running turns and writes nothing more.

AgentCore sends SIGTERM to the process right after StopRuntimeSession (and when it
reclaims an idle microVM). uvicorn then waits for the running /invocations to finish,
with no time limit by default, and the platform kills the process only after a grace
period (about 10 s on V2, 28-60 s or more on V1). The turn and its composers keep
running and writing to S3, MCP and Memory meanwhile.

The guard, installed through the app's lifespan so it runs before uvicorn's own handler:
  1. closes the write gate (resilience.close_writes): tool calls, compose's direct MCP
     calls and Memory events (GatedMemorySessionManager) are dropped from then on;
  2. sets every running turn's stop event, which Strands and the composers observe;
  3. starts a watchdog that flushes OpenTelemetry and exits the process after
     EXIT_AFTER_S, whatever is still running (a composer thread blocked in a read);
  4. closes the process's resident MCP clients (AWS Knowledge, and AWS Pricing's stdio
     subprocess) on a side thread, best effort: the watchdog's exit bounds it.
basic_agent passes GRACEFUL_SHUTDOWN_S to uvicorn so it stops waiting before that.
"""

import contextlib
import logging
import os
import signal
import sys
import threading
import time
from typing import Callable

from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

import mcp_clients
from resilience import close_writes, writes_closed

logger = logging.getLogger("sdpm.agent")

GRACEFUL_SHUTDOWN_S = 2
EXIT_AFTER_S = 3.0

# Re-entrant: the SIGTERM handler takes it on the main thread, which may hold it already.
_lock = threading.RLock()
# Running turns: stop event -> what to call when the turn is stopped (or None).
_running: dict[threading.Event, Callable[[], object] | None] = {}
_exiting = threading.Event()


def begin_turn(on_stop: Callable[[], object] | None = None) -> threading.Event:
    """Register a running turn and return its stop event (set on SIGTERM).

    ``on_stop`` runs when SIGTERM stops the turn (on the signal handler's thread, so it
    must not block: turn_fence.TurnFence.advance hands its call to a thread).
    Pair with end_turn() in a finally block.
    """
    stop = threading.Event()
    with _lock:
        _running[stop] = on_stop
    if writes_closed():
        stop.set()  # the process is already stopping
    return stop


def end_turn(stop: threading.Event) -> None:
    with _lock:
        _running.pop(stop, None)


def stop_all() -> int:
    """Close the write gate and set the stop event of every running turn."""
    close_writes()
    with _lock:
        running = list(_running.items())
    for stop, on_stop in running:
        stop.set()
        if on_stop is not None:
            try:
                on_stop()
            except Exception as e:  # noqa: BLE001 - the other turns still stop
                logger.warning("SIGTERM guard: a turn's stop callback failed: %s", e)
    return len(running)


class GatedMemorySessionManager(AgentCoreMemorySessionManager):
    """AgentCore Memory session manager that drops new events once the write gate is closed."""

    def create_message(self, session_id, agent_id, session_message, **kwargs):
        if writes_closed():
            return None
        return super().create_message(session_id, agent_id, session_message, **kwargs)

    def create_agent(self, session_id, session_agent, **kwargs):
        if writes_closed():
            return None
        return super().create_agent(session_id, session_agent, **kwargs)


def _flush_telemetry() -> None:
    from opentelemetry import trace
    from opentelemetry._logs import get_logger_provider

    for provider in (trace.get_tracer_provider(), get_logger_provider()):
        flush = getattr(provider, "force_flush", None)
        if flush is not None:
            with contextlib.suppress(Exception):
                flush(1000)


def _exit_after(delay: float) -> None:
    time.sleep(delay)
    with _lock:
        running = len(_running)
    logger.warning("SIGTERM guard: exiting after %.1fs (%d turn(s) still registered)", delay, running)
    with contextlib.suppress(Exception):
        _flush_telemetry()
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    os._exit(0)


def _close_resident_clients() -> None:
    try:
        mcp_clients.close_resident_clients()
    except Exception as e:  # noqa: BLE001 - best effort, the process is exiting anyway
        logger.warning("SIGTERM guard: closing the resident MCP clients failed: %s", e)


def _on_sigterm(previous):
    def handler(signum, frame):
        stopped = stop_all()
        if not _exiting.is_set():  # signal handlers run on the main thread only: no race here
            _exiting.set()
            logger.warning("SIGTERM: stopping %d running turn(s); writes are closed", stopped)
            threading.Thread(target=_exit_after, args=(EXIT_AFTER_S,), daemon=True, name="stop-guard-exit").start()
            # After the watchdog: closing can block (a stdio subprocess that does not exit).
            threading.Thread(target=_close_resident_clients, daemon=True, name="stop-guard-close").start()
        if callable(previous):
            previous(signum, frame)  # uvicorn's handle_exit: begin the graceful shutdown
    return handler


def install() -> None:
    """Install the SIGTERM handler in front of the current one (uvicorn's)."""
    if threading.current_thread() is not threading.main_thread():
        return  # signal handlers can only be set from the main thread (as in uvicorn)
    signal.signal(signal.SIGTERM, _on_sigterm(signal.getsignal(signal.SIGTERM)))


@contextlib.asynccontextmanager
async def lifespan(app):
    """App lifespan: uvicorn has installed its signal handlers by the time this starts."""
    install()
    yield
