# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Composers get a Presentation Maker client restricted to the composer's deck tools.

compose_slides replaces the orchestrator's client with a fresh one per group, so the
filter has to be on the client the composer factory builds.
"""

from test_mcp_parallel_connect import _factory


class _Hooks:
    def add_callback(self, *args, **kwargs):
        pass


class _Client:
    """The session handle holds a consumer on its Presentation Maker client."""

    def add_consumer(self, consumer_id, **kwargs):
        pass

    def remove_consumer(self, consumer_id, **kwargs):
        pass


def _jwt_of(sub: str) -> str:
    import base64
    import json

    body = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


class _Agent:
    def __init__(self, **kwargs):
        self.messages = []
        self.hooks = _Hooks()
        self.tool_names = []
        self.system_prompt = ""


def test_composer_mcp_factory_carries_the_composer_allowlist(monkeypatch):
    factory = _factory()
    MODES = factory.MODES

    runtime_calls: list[dict] = []
    captured: dict = {}

    def runtime(**kwargs):
        runtime_calls.append(kwargs)
        return _Client()

    def make_compose_slides(mcp_servers, model, composer_mcp_factory, **kwargs):
        captured["factory"] = composer_mcp_factory
        return object()

    monkeypatch.delenv("MEMORY_ID", raising=False)
    monkeypatch.setattr(factory, "mcp_agentcore_runtime", runtime)
    monkeypatch.setattr(factory, "mcp_aws_knowledge", lambda: object())
    monkeypatch.setattr(factory, "mcp_aws_pricing", lambda: object())
    monkeypatch.setattr(factory, "_prewarm_mcp_clients", lambda clients, names, required, then=None: (clients, []))
    monkeypatch.setattr(factory, "BedrockModel", lambda **kwargs: object())
    monkeypatch.setattr(factory, "make_compose_slides", make_compose_slides)
    monkeypatch.setattr(factory, "Agent", _Agent)
    monkeypatch.setattr(factory, "collect_mcp_instructions", lambda servers: "")
    monkeypatch.setattr(factory, "resolve_parts", lambda *a, **k: ("", []))

    factory.create_agent("orchestrator", user_id="u1", session_id="s1", jwt_token=_jwt_of("u1"))
    runtime_calls.clear()
    captured["factory"]("s1-g1")

    (call,) = runtime_calls
    assert call["session_id"] == "s1-g1"
    assert call["tool_filters"] == {"allowed": MODES["composer"].allowed_tools}
    assert "run_style_python" not in call["tool_filters"]["allowed"]
