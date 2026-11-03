# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""When the remote MCP server warms LibreOffice, and what it preloads at startup.

On AgentCore Runtime platform V2 every microVM is restored from a snapshot taken
after startup. The LibreOffice warm-up must run after the restore but must not
compete with the agent's first requests, so it starts once per process, after
the first entry tool (start_presentation / start_composing) has sent its result,
and never from the platform's health check (a PingRequest POST without an
Mcp-Session-Id). The startup preload puts static files into the snapshot and
must not build clients or resolve credentials, which the snapshot would freeze.
"""

import asyncio
import base64
import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def server(monkeypatch):
    """servers/remote/server.py imported fresh, with a fresh default boto3 session.

    Returns (module, built, credentials, warm_ups): every boto3 client/resource the
    module built, every credential resolution, and the name of every background
    warm-up start (the warm-up itself does not run).
    """
    for var, val in {
        "DECKS_TABLE": "decks-test",
        "PPTX_BUCKET": "pptx-test",
        "RESOURCE_BUCKET": "resource-test",
        "AWS_DEFAULT_REGION": "ap-northeast-1",
    }.items():
        monkeypatch.setenv(var, val)
    for var in ("KB_ID", "KB_SSM_PARAM", "SDPM_SKIP_SOFFICE_WARMUP"):
        monkeypatch.delenv(var, raising=False)

    boto3 = pytest.importorskip("boto3")
    pytest.importorskip("mcp.server.fastmcp")
    import boto3.session
    import botocore.session

    monkeypatch.setattr(boto3, "DEFAULT_SESSION", None)
    built: list[tuple[str, str]] = []
    credentials: list[object] = []
    monkeypatch.setattr(boto3.session.Session, "client", lambda self, name, *a, **k: built.append(("client", name)) or MagicMock())
    monkeypatch.setattr(boto3.session.Session, "resource", lambda self, name, *a, **k: built.append(("resource", name)) or MagicMock())
    real_get_credentials = botocore.session.Session.get_credentials
    monkeypatch.setattr(
        botocore.session.Session, "get_credentials",
        lambda self, *a, **k: credentials.append(self) or real_get_credentials(self, *a, **k),
    )

    remote = _ROOT / "servers" / "remote"
    for p in (str(_ROOT), str(remote), str(_ROOT / "sdpm")):
        if p not in sys.path:
            sys.path.insert(0, p)
    name = "sdpm_remote_server_warmup_under_test"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, remote / "server.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:  # pragma: no cover - environment-dependent
        sys.modules.pop(name, None)
        pytest.skip(f"servers/remote/server.py not importable here: {e}")

    warm_ups: list[str] = []
    monkeypatch.setattr(module, "_run_in_background", lambda target, *, name: warm_ups.append(name))
    monkeypatch.setattr(module.reference, "list_styles", lambda **kw: {"styles": []})
    monkeypatch.setattr(module.template_mod, "list_templates", lambda **kw: {"templates": []})
    yield module, built, credentials, warm_ups
    sys.modules.pop(name, None)


def _bearer(sub: str = "user-1") -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"Bearer x.{payload}.y"


def _post(module, body: dict, *, headers: dict | None = None, events: list | None = None):
    """POST /mcp through the app as server.py runs it (FastMCP + the header middleware).

    ``events`` gets "response sent" once the last body chunk has gone out.
    """
    import httpx

    app = module.mcp.streamable_http_app()
    app.add_middleware(module._CaptureHeadersMiddleware)

    async def recording(scope, receive, send):
        async def _send(message):
            await send(message)
            if events is not None and message["type"] == "http.response.body" and not message.get("more_body"):
                events.append("response sent")

        await app(scope, receive, _send)

    async def run():
        async with module.mcp.session_manager.run():
            transport = httpx.ASGITransport(app=recording)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.post(
                    "/mcp", json=body,
                    headers={"accept": "application/json, text/event-stream", **(headers or {})},
                )

    return asyncio.run(run())


class TestWarmUpTrigger:
    def test_health_check_ping_does_not_start_it(self, server):
        module, _, _, warm_ups = server
        # The platform's health check: a PingRequest without an Mcp-Session-Id.
        r = _post(module, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 200
        assert warm_ups == []
        assert module._warmup_state == "pending"

    def test_first_start_presentation_starts_it_after_the_response(self, server):
        module, _, _, warm_ups = server
        events: list[str] = []
        module._run_in_background = lambda target, *, name: events.append(f"started {name}")
        r = _post(
            module,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "start_presentation", "arguments": {}}},
            headers={"authorization": _bearer(), "mcp-session-id": "sess-1"},
            events=events,
        )
        assert r.status_code == 200
        assert "workflow" in r.text
        assert events == ["response sent", "started soffice-warmup"]

    def test_start_composing_starts_it(self, server):
        # A composer group's MCP session (<sid>-gN) is its own microVM.
        module, _, _, warm_ups = server
        module.start_composing()
        assert warm_ups == ["soffice-warmup"]

    def test_never_twice_in_one_process(self, server):
        module, _, _, warm_ups = server
        token = module._current_request_headers.set({"authorization": _bearer()})
        try:
            module.start_presentation()
            module.start_presentation()  # still running
            module._warmup_state = "done"
            module.start_presentation()
            module.start_composing()
        finally:
            module._current_request_headers.reset(token)
        assert warm_ups == ["soffice-warmup"]

    def test_skip_switch(self, server, monkeypatch):
        module, _, _, warm_ups = server
        monkeypatch.setenv("SDPM_SKIP_SOFFICE_WARMUP", "1")
        module.start_composing()
        assert warm_ups == []


class TestWarmUpRun:
    def _fake_soffice(self, monkeypatch, returncode: int, gate: threading.Event | None = None) -> list:
        import shutil
        import subprocess

        runs: list = []

        def fake_run(cmd, **kw):
            runs.append(cmd)
            if gate is not None:
                gate.wait(5)
            return SimpleNamespace(returncode=returncode)

        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/soffice")
        monkeypatch.setattr(subprocess, "run", fake_run)
        return runs

    def test_success_is_final(self, server, monkeypatch):
        module, *_ = server
        runs = self._fake_soffice(monkeypatch, 0)
        module._run_in_background = lambda target, *, name: target()
        for _ in range(3):
            module._start_soffice_warm_up_once()
        assert len(runs) == 1
        assert module._warmup_state == "done"

    def test_failure_is_retried_on_the_next_entry_call(self, server, monkeypatch):
        module, *_ = server
        runs = self._fake_soffice(monkeypatch, 1)
        module._run_in_background = lambda target, *, name: target()
        module._start_soffice_warm_up_once()
        assert module._warmup_state == "pending"
        module._start_soffice_warm_up_once()
        assert len(runs) == 2

    def test_a_running_warm_up_holds_no_lock(self, server, monkeypatch):
        # A conversion arriving meanwhile never waits on the warm-up.
        module, *_ = server
        gate = threading.Event()
        runs = self._fake_soffice(monkeypatch, 0, gate)
        module._run_in_background = lambda target, *, name: threading.Thread(target=target, daemon=True).start()
        module._start_soffice_warm_up_once()
        try:
            for _ in range(100):
                if runs:
                    break
                threading.Event().wait(0.01)
            assert module._warmup_state == "running"
            module._start_soffice_warm_up_once()  # returns at once, starts nothing
            assert module._warmup_lock.acquire(blocking=False)
            module._warmup_lock.release()
        finally:
            gate.set()
        assert len(runs) == 1


class TestStartupPreload:
    def test_builds_no_client_and_resolves_no_credentials(self, server):
        _, built, credentials, _ = server
        assert built == []
        assert credentials == []

    def test_service_definitions_are_served_from_memory(self, server, monkeypatch):
        import os

        import boto3
        from botocore import loaders

        real_load = loaders.JSONFileLoader._load_file

        def no_read(self, full_path, open_method):
            # Probing for optional files (sdk-extras) is fine; reading a definition again is not.
            if os.path.isfile(full_path):
                raise AssertionError(f"read from disk after the preload: {full_path}")
            return real_load(self, full_path, open_method)

        monkeypatch.setattr(loaders.JSONFileLoader, "_load_file", no_read)
        loader = boto3.DEFAULT_SESSION._session.get_component("data_loader")
        # The way a client asks for them (api_version passed), not the way the preload does.
        for service in ("s3", "dynamodb", "ssm", "bedrock-agentcore", "bedrock-runtime", "s3vectors"):
            assert loader.load_service_model(service, "service-2", api_version=None)["metadata"]
            assert loader.load_service_model(service, "endpoint-rule-set-1", api_version=None)
        assert loader.load_service_model("dynamodb", "resources-1", api_version=None)
        assert loader.load_data("partitions")

    def test_styles_and_role_documents_are_served_from_memory(self, server, monkeypatch):
        module, *_ = server
        import sdpm.knowledge.reference as kr
        from sdpm import entry

        def no_disk(*a, **k):
            raise AssertionError("read from disk after the preload")

        monkeypatch.setattr(kr, "list_styles", no_disk)
        monkeypatch.setattr(kr, "read_docs", no_disk)
        assert module.reference.bundled_styles()
        for role in ("orchestrator", "composer", "composer-html", "style"):
            assert entry._workflow(role)
        assert entry._slide_spec()
