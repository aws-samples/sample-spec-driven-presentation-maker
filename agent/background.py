# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Background tasks of the orchestrator Agent: compose_slides runs as a Strands background task.

The orchestrator dispatches a compose and its turn goes on (or ends) while the composers
work; Strands delivers the report into the history later, before the next model call
(session_runtime.py starts a turn with no input for it when none runs). Strands' own
delivery is a synthetic ``strands_manage_background_task`` ``get`` call and its result;
``deliver_as_text`` rewrites it, before it reaches the history, into one user text block
``<compose_result task="…" status="…">report</compose_result>``, so neither the model nor
Memory ever sees the management tool.

This module holds the policy and is the only code that knows Strands' background internals:
the agent-state key of the task snapshots, the management tool's name, the continuation
input that carries a delivery and the task manager's cancel. Tests pin each name to
Strands' own (test_agent_background.py).
"""

import dataclasses
import html
import inspect
import logging
import re

from strands.hooks import AfterInvocationEvent, BeforeModelCallEvent, BeforeToolCallEvent, HookOrder
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
    "finishes. Finish any other work and end your turn; you are woken with the result."
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


RESULT_TAG = "compose_result"
_RESULT_RE = re.compile(rf'<{RESULT_TAG} task="([^"]*)" status="([^"]*)">(.*?)</{RESULT_TAG}>', re.DOTALL)


def result_block(task: dict) -> str:
    """The text a delivered task becomes: ``<compose_result task status>report</compose_result>``.
    Escaped like a composer note, so a report cannot close the element."""
    return (f'<{RESULT_TAG} task="{html.escape(str(task.get("task_id", "")))}" '
            f'status="{html.escape(str(task.get("status", "")))}">'
            f'{html.escape(result_text(task), quote=False)}</{RESULT_TAG}>')


def delivered(message: dict) -> list[dict]:
    """The tasks a history message delivers (``<compose_result>`` blocks of a user message),
    as ``{task_id, status, result: {content: [{text: report}]}}``."""
    found = []
    if not isinstance(message, dict) or message.get("role") != "user":
        return found
    for block in message.get("content") or []:
        text = block.get("text") if isinstance(block, dict) else None
        if not isinstance(text, str):
            continue
        for task_id, status, body in _RESULT_RE.findall(text):
            found.append({"task_id": html.unescape(task_id), "status": html.unescape(status),
                          "result": {"content": [{"text": html.unescape(body)}]}})
    return found


def _synthetic_tasks(messages) -> list[dict] | None:
    """The task snapshots in Strands' synthetic delivery (pairs of a management ``get``
    toolUse and its toolResult: the task's metadata, then its result content), or None
    when ``messages`` is anything else."""
    if not isinstance(messages, list) or not messages or len(messages) % 2:
        return None
    found = []
    for use, res in zip(messages[::2], messages[1::2]):
        uses = [b.get("toolUse") for b in use.get("content") or [] if isinstance(b, dict)]
        results = [b.get("toolResult") for b in res.get("content") or [] if isinstance(b, dict)]
        if (use.get("role") != "assistant" or res.get("role") != "user" or len(uses) != 1 or len(results) != 1
                or not isinstance(uses[0], dict) or uses[0].get("name") != MANAGE_TOOL or not isinstance(results[0], dict)):
            return None
        content = results[0].get("content") or []
        meta = content[0].get("json") if content and isinstance(content[0], dict) else None
        if not isinstance(meta, dict) or meta.get("task_id") != results[0].get("toolUseId"):
            return None
        found.append({**meta, "result": {"content": list(content[1:])}})
    return found


def deliver_as_text(agent, on_delivered=None) -> None:
    """Rewrite Strands' delivery of background results into one user text block.

    Strands (1.63, ``_BackgroundTasks._deliver_ready``) queues the synthetic ``get`` pairs
    as a continuation input of the BeforeModelCallEvent / AfterInvocationEvent; the agent
    normalizes and appends it after the event's hooks have run. This hook runs last on both
    events and replaces that input's messages with ``[{"role": "user", "content": [{"text":
    <compose_result>…}]}]``, keeping its ``on_appended`` (which drops the delivered tasks
    from Strands' list once the text is in the history) and calling ``on_delivered(task)``
    for each task after it. A user message right before it (a tool result mid-turn) takes
    the text in; after an assistant message it is a message of its own. The model saw the
    management tool in its history and called it by name (dev, Sonnet 5); now it does not.
    """
    if MANAGE_TOOL not in getattr(agent, "tool_names", ()):
        return
    # Strands' private continuation (strands/agent/_continuation.py): the inputs a hook
    # added to the event, before they are prepared.
    from strands.agent import _continuation

    def rewrite(event) -> None:
        state = _continuation._get_state(event)
        if state is None or state.messages is not None:
            return
        for i, input_ in enumerate(state.inputs):
            snapshots = _synthetic_tasks(input_.args)
            if not snapshots:
                continue
            appended = input_.on_appended

            async def on_appended(appended=appended, snapshots=snapshots) -> None:
                if appended is not None:
                    result = appended()
                    if inspect.isawaitable(result):
                        await result
                if on_delivered is not None:
                    for task in snapshots:
                        on_delivered(task)

            text = "\n\n".join(result_block(task) for task in snapshots)
            state.inputs[i] = dataclasses.replace(
                input_, args=[{"role": "user", "content": [{"text": text}]}], on_appended=on_appended,
            )

    agent.add_hook(rewrite, BeforeModelCallEvent, order=HookOrder.SDK_LAST)
    agent.add_hook(rewrite, AfterInvocationEvent, order=HookOrder.SDK_LAST)


async def cancel_all(agent) -> None:
    """Cancel every pending background task of ``agent`` (errors are logged)."""
    for task in pending(agent):
        try:
            # The single private call: Strands has no public cancel besides the
            # management tool, which the model no longer sees.
            await agent._background_tasks._manager.cancel(task["task_id"])
        except Exception as e:  # noqa: BLE001 - the other tasks still get cancelled
            logger.warning("Cancelling background task %s failed: %s", task.get("task_id"), e)
