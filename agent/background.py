# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Background tasks of the orchestrator Agent: compose_slides runs as a Strands background task.

The orchestrator dispatches a compose and its turn goes on (or ends) while the composers
work; Strands delivers the report into the history later, as a synthetic
``strands_manage_background_task`` ``get`` call and its result, before the next model call
(session_runtime.py starts a turn with no input for it when none runs).

This module holds the policy and is the only code that knows Strands' background internals:
the agent-state key of the task snapshots, the management tool's name and the task
manager's cancel. Tests pin each name to Strands' own (test_agent_background.py).
"""

import dataclasses
import logging

from strands.hooks import BeforeToolCallEvent
from strands.middleware.stages import InvokeModelStage

logger = logging.getLogger("sdpm.agent")

BACKGROUND_TOOLS = ("compose_slides",)
TASK_TIMEOUT_S = 3600.0  # the session runtime's watchdog (WORK_LIMIT_S)

# The Agent's ``background_tasks``. "never: *" is required: without an explicit wildcard
# Strands lets the model choose for every other tool (it adds a ``_background_execution``
# flag to their schemas). One task at a time per session: two composes of one deck would
# write the same files; a second call waits for the first, as calls did when compose was
# synchronous.
CONFIG = {
    "always": list(BACKGROUND_TOOLS),
    "never": ["*"],
    "wait_for_completion": False,
    "max_concurrency": 1,
    "timeout": TASK_TIMEOUT_S,
}

# strands.background_tasks._background_tasks._MANAGE_TOOL_NAME / _BACKGROUND_TASKS_STATE_KEY
MANAGE_TOOL = "strands_manage_background_task"
STATE_KEY = "strands.background_tasks"

TERMINAL = ("completed", "failed", "cancelled")

_DELIVERED_AUTOMATICALLY = (
    "Not available here: background results are delivered automatically when the task "
    "finishes. Continue without checking on them."
)


def hide_manage_tool(agent) -> None:
    """Keep the management tool from the model, and refuse a call to it by name.

    The model polled with it and cancelled running composes to redo them; a cancel would
    stop the session's work. The synthetic deliveries are history messages, not calls,
    so they are unaffected.
    """
    if MANAGE_TOOL not in getattr(agent, "tool_names", ()):
        return  # no background plugin on this Agent

    async def drop_spec(context):
        return dataclasses.replace(
            context, tool_specs=[spec for spec in context.tool_specs if spec.get("name") != MANAGE_TOOL],
        )

    def refuse(event: BeforeToolCallEvent) -> None:
        if event.tool_use.get("name") == MANAGE_TOOL:
            event.cancel_tool = _DELIVERED_AUTOMATICALLY

    agent.add_middleware(InvokeModelStage.Input, drop_spec)
    agent.add_hook(refuse, BeforeToolCallEvent)


def tasks(agent) -> list[dict]:
    """The Agent's background task snapshots (a task leaves once its result is delivered)."""
    state = getattr(agent, "state", None)
    if state is None:
        return []
    return list(state.get(STATE_KEY) or [])


def pending(agent) -> list[dict]:
    """Tasks that have not settled (queued or working)."""
    return [task for task in tasks(agent) if task.get("status") not in TERMINAL]


def undelivered(agent) -> list[dict]:
    """Settled tasks whose result is not in the history yet."""
    return [task for task in tasks(agent) if task.get("status") in TERMINAL]


def result_text(task: dict) -> str:
    """The text of a task's result (compose_slides' report JSON); the error message when it has none."""
    content = (task.get("result") or {}).get("content") or []
    text = "".join(item["text"] for item in content if isinstance(item, dict) and isinstance(item.get("text"), str))
    if not text and isinstance(task.get("error"), dict):
        text = str(task["error"].get("message", ""))
    return text


def delivered(message: dict) -> list[dict]:
    """The tasks a history message delivers (the results of synthetic ``get`` calls), as
    snapshots: the metadata Strands puts first, plus the result content after it."""
    found = []
    if not isinstance(message, dict) or message.get("role") != "user":
        return found
    for block in message.get("content") or []:
        result = block.get("toolResult") if isinstance(block, dict) else None
        if not isinstance(result, dict):
            continue
        content = result.get("content") or []
        meta = content[0].get("json") if content and isinstance(content[0], dict) else None
        if (isinstance(meta, dict) and meta.get("task_id") == result.get("toolUseId")
                and meta.get("status") in TERMINAL):
            found.append({**meta, "result": {"content": list(content[1:])}})
    return found


async def cancel_all(agent) -> None:
    """Cancel every pending background task of ``agent`` (errors are logged)."""
    for task in pending(agent):
        try:
            # The single private call: Strands has no public cancel besides the
            # management tool, which the model no longer sees.
            await agent._background_tasks._manager.cancel(task["task_id"])
        except Exception as e:  # noqa: BLE001 - the other tasks still get cancelled
            logger.warning("Cancelling background task %s failed: %s", task.get("task_id"), e)
