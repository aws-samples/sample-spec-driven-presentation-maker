# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Fakes at the agent's edges (model, Presentation Maker MCP, Memory backend) for
test_agent_stop_guard. Every call that would reach the outside is recorded with a
timestamp, so a test can tell which ones came after a cancel or a SIGTERM.
"""

import asyncio
import json
import threading
import time
import uuid
from pathlib import Path

from strands import tool
from strands.models import Model
from strands.tools.tool_provider import ToolProvider


class Recorder:
    """Appends one JSON line per outside call; readable from another process."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def log(self, kind: str, name: str, who: str = "", detail: dict | None = None) -> None:
        record = {"t": time.time(), "kind": kind, "name": name, "who": who}
        if detail is not None:
            record["detail"] = detail
        line = json.dumps(record)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # a line still being written by the other process
        return records


GROUPS = [{"slugs": ["a"], "instruction": "Compose."}, {"slugs": ["b"], "instruction": "Compose."}]


class ScriptedModel(Model):
    """The parent (compose_slides among its tools) dispatches one compose with two groups,
    then keeps calling write_slide; a composer keeps calling write_slide."""

    def __init__(self, recorder: Recorder):
        self.recorder = recorder

    def update_config(self, **model_config):
        pass

    def get_config(self):
        return {}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        parent = "compose_slides" in {spec["name"] for spec in tool_specs or []}
        self.recorder.log("model", "stream", "parent" if parent else "composer")
        results = sum(1 for m in messages for block in m["content"] if "toolResult" in block)
        if parent and results == 0:
            name, args = "compose_slides", {"deck_id": "deck1", "slide_groups": GROUPS}
        else:
            name, args = "write_slide", {"slug": f"s{results}"}  # distinct input: no LoopGuard repeat
        await asyncio.sleep(0.05)
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{uuid.uuid4().hex[:8]}", "name": name}}}}
        yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}


# One payload answers every direct call compose_slides and resolve_parts make
# (check_specs, start_presentation / start_composing static parts and deck part, generate_pptx).
_PAYLOAD = {
    "ok": True, "errors": [], "warnings": [], "slugs": ["a", "b"],
    "static": {"workflow": "Compose slides.", "slide_spec": "Slide spec."},
    "styles": [], "templates": [], "deck": {"specs_ok": True}, "specs_ok": True,
}


class FakeMCP(ToolProvider):
    """Stands in for the Presentation Maker MCPClient: one slow write_slide tool, and
    call_tool_sync for compose's direct calls.

    hold_loop: write_slide blocks the calling agent's event loop for its whole duration,
    so nothing else on that loop (Strands' cancel watcher) runs meanwhile.
    meta: the client-level ``_meta`` the factory gave it (the turn's write-fence
    generation); recorded at construction and with every direct call.
    fence_seconds: fence_turn is recorded only after this long, like a request that
    reaches a cold MCP runtime late; a process that exits sooner never records it.
    """

    server_instructions = ""

    def __init__(self, recorder: Recorder, who: str, tool_seconds: float = 0.5, hold_loop: bool = False,
                 meta: dict | None = None, fence_seconds: float = 0.0):
        self.recorder = recorder
        self.who = who
        self.meta = meta
        self.fence_seconds = fence_seconds
        recorder.log("client", "created", who, detail={"meta": meta})

        if hold_loop:
            @tool(name="write_slide")
            async def write_slide(slug: str) -> str:
                """Write one slide."""
                recorder.log("tool", "write_slide", who)
                time.sleep(tool_seconds)
                return f"wrote {slug}"
        else:
            @tool(name="write_slide")
            def write_slide(slug: str) -> str:
                """Write one slide."""
                recorder.log("tool", "write_slide", who)
                time.sleep(tool_seconds)
                return f"wrote {slug}"

        self._tools = [write_slide]

    async def load_tools(self, **kwargs):
        return self._tools

    def add_consumer(self, consumer_id, **kwargs):
        pass

    def remove_consumer(self, consumer_id, **kwargs):
        pass

    def stop(self, *exc_info):
        pass

    def call_tool_sync(self, tool_use_id, name, arguments, **kwargs):
        if name == "fence_turn":
            time.sleep(self.fence_seconds)
        meta = kwargs.get("meta") if kwargs.get("meta") is not None else self.meta
        self.recorder.log("mcp", name, self.who, detail={"arguments": arguments, "meta": meta})
        return {"status": "success", "toolUseId": tool_use_id, "content": [{"text": json.dumps(_PAYLOAD)}]}


def patch_memory_backend(recorder: Recorder) -> None:
    """Replace AgentCore Memory's network calls with recorded no-ops (below the write gate)."""
    from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager as M

    def create_message(self, session_id, agent_id, session_message, **kwargs):
        recorder.log("memory", "create_message")
        return {"eventId": f"e{uuid.uuid4().hex[:8]}"}

    def create_agent(self, session_id, session_agent, **kwargs):
        recorder.log("memory", "create_agent")
        self._agent_created_at_cache[session_agent.agent_id] = session_agent.created_at

    M.create_message = create_message
    M.create_agent = create_agent
    M.create_session = lambda self, session, **kwargs: session
    M.read_session = lambda self, session_id, **kwargs: None
    M.read_agent = lambda self, session_id, agent_id, **kwargs: None
    M.list_messages = lambda self, *args, **kwargs: []
