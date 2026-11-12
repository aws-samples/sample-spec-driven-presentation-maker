# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""An in-memory AgentCore Memory for the Strands session manager.

``patch_memory(monkeypatch)`` replaces the MemoryClient that
bedrock_agentcore's AgentCoreMemorySessionManager builds with one whose events live in
a list. The events have the shapes ``bedrock_agentcore.memory.client.MemoryClient
.create_event`` builds and ListEvents returns (newest first), so the real converter
reads them back. The boto3 clients the session manager assigns are ignored.
"""

import itertools
import threading
from datetime import datetime, timezone


class FakeMemoryStore:
    """Every event of every session, in creation order, and the calls that changed them."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.ops: list[tuple[str, str]] = []  # ("create" | "delete", eventId)
        self._ids = itertools.count(1)

    def create(self, params: dict) -> dict:
        with self.lock:
            n = next(self._ids)
            event = {
                "memoryId": params["memoryId"],
                "actorId": params["actorId"],
                "sessionId": params["sessionId"],
                "eventId": f"{n:016d}#fake",
                "eventTimestamp": params.get("eventTimestamp") or datetime.now(timezone.utc),
                "payload": params["payload"],
                "branch": params.get("branch") or {"name": "main"},
            }
            if params.get("metadata"):
                event["metadata"] = params["metadata"]
            self.events.append(event)
            self.ops.append(("create", event["eventId"]))
            return dict(event)

    def delete(self, session_id: str, event_id: str) -> None:
        with self.lock:
            before = len(self.events)
            self.events = [e for e in self.events if not (e["sessionId"] == session_id and e["eventId"] == event_id)]
            if len(self.events) == before:
                raise KeyError(event_id)
            self.ops.append(("delete", event_id))

    def find(self, session_id: str, actor_id: str, filters=None) -> list[dict]:
        """Matching events, newest first (as ListEvents returns them)."""
        with self.lock:
            events = [e for e in self.events if e["sessionId"] == session_id and e["actorId"] == actor_id]
        for expression in filters or []:
            key = expression["left"]["metadataKey"]
            operator = getattr(expression["operator"], "value", expression["operator"])
            value = (expression.get("right") or {}).get("metadataValue", {}).get("stringValue")
            if operator == "EQUALS_TO":
                events = [e for e in events if e.get("metadata", {}).get(key, {}).get("stringValue") == value]
            elif operator == "EXISTS":
                events = [e for e in events if key in e.get("metadata", {})]
            elif operator == "NOT_EXISTS":
                events = [e for e in events if key not in e.get("metadata", {})]
        return [dict(e) for e in reversed(events)]

    def messages(self, session_id: str) -> list[dict]:
        """The conversational events of a session, oldest first."""
        with self.lock:
            return [e for e in self.events
                    if e["sessionId"] == session_id and any("conversational" in p for p in e["payload"])]


class _DataPlane:
    """The ``bedrock-agentcore`` boto3 client's calls the session manager makes."""

    def __init__(self, store: FakeMemoryStore):
        self.store = store

    def create_event(self, **params):
        return {"event": self.store.create(params)}

    def delete_event(self, memoryId, actorId, sessionId, eventId, **kwargs):
        self.store.delete(sessionId, eventId)
        return {}

    def get_event(self, memoryId, actorId, sessionId, eventId, **kwargs):
        for event in self.store.find(sessionId, actorId):
            if event["eventId"] == eventId:
                return {"event": event}
        raise KeyError(eventId)

    def list_events(self, memoryId, actorId, sessionId, maxResults=100, filter=None, **kwargs):
        events = self.store.find(sessionId, actorId, (filter or {}).get("eventMetadata"))
        return {"events": events[:maxResults]}


class _MemoryClient:
    """MemoryClient's create_event / list_events over the store; boto clients ignored."""

    store: FakeMemoryStore

    def __init__(self, region_name=None, boto3_session=None, **kwargs):
        self._data_plane = _DataPlane(self.store)

    @property
    def gmdp_client(self):
        return self._data_plane

    @gmdp_client.setter
    def gmdp_client(self, client):
        pass  # the session manager's boto3 client

    @property
    def gmcp_client(self):
        return None

    @gmcp_client.setter
    def gmcp_client(self, client):
        pass

    def create_event(self, memory_id, actor_id, session_id, messages, event_timestamp=None, branch=None,
                     metadata=None, extraction_mode=None):
        # As MemoryClient.create_event builds it.
        payload = [{"conversational": {"content": {"text": text}, "role": role.upper()}} for text, role in messages]
        params = {"memoryId": memory_id, "actorId": actor_id, "sessionId": session_id,
                  "eventTimestamp": event_timestamp, "payload": payload}
        if branch:
            params["branch"] = branch
        if metadata:
            params["metadata"] = metadata
        return self._data_plane.create_event(**params)["event"]

    def list_events(self, memory_id, actor_id, session_id, branch_name=None, include_parent_branches=False,
                    event_metadata=None, max_results=100, include_payload=True):
        return self.store.find(session_id, actor_id, event_metadata)[:max_results]


def patch_memory(monkeypatch) -> FakeMemoryStore:
    """Back every AgentCoreMemorySessionManager built from now on with a new in-memory store."""
    from bedrock_agentcore.memory.integrations.strands import session_manager

    store = FakeMemoryStore()
    client = type("FakeMemoryClient", (_MemoryClient,), {"store": store})
    monkeypatch.setattr(session_manager, "MemoryClient", client)
    return store
