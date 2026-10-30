# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Remote MCP server: AgentCore Browser as the browser of the HTML browser check."""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.credentials import Credentials

from sdpm.engine.html import browser as browser_mod
from sdpm.engine.html.browser_check import check_deck
from tools import agentcore_browser

_ROOT = Path(__file__).resolve().parents[1]
_STREAM = "wss://bedrock-agentcore.ap-northeast-1.amazonaws.com/browser-streams/aws.browser.v1/sessions/s1/automation"

os.environ.setdefault("DECKS_TABLE", "test-table")
os.environ.setdefault("PPTX_BUCKET", "test-pptx")
os.environ.setdefault("RESOURCE_BUCKET", "test-resource")


class StubClient:
    def __init__(self, start_error: Exception | None = None, stop_error: Exception | None = None):
        self.started: list[dict] = []
        self.stopped: list[dict] = []
        self.start_error = start_error
        self.stop_error = stop_error

    def start_browser_session(self, **kwargs):
        self.started.append(kwargs)
        if self.start_error:
            raise self.start_error
        return {"sessionId": "s1", "streams": {"automationStream": {"streamEndpoint": _STREAM}}}

    def stop_browser_session(self, **kwargs):
        self.stopped.append(kwargs)
        if self.stop_error:
            raise self.stop_error


def _source(client: StubClient, calls: list | None = None):
    def factory():
        if calls is not None:
            calls.append(1)
        return client

    return agentcore_browser.make_source(
        "ap-northeast-1", client_factory=factory,
        credentials_factory=lambda: Credentials("AKIDEXAMPLE", "secret", "session-token"),
    )


def test_session_starts_with_the_deck_viewport_and_signs_the_stream():
    client = StubClient()
    with _source(client)(1920, 1080) as endpoint:
        assert client.stopped == []
        assert endpoint.url == _STREAM and endpoint.name == "AgentCore Browser"
        assert set(endpoint.headers) == {"Authorization", "X-Amz-Date", "X-Amz-Security-Token"}
        assert endpoint.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
        assert "/ap-northeast-1/bedrock-agentcore/aws4_request" in endpoint.headers["Authorization"]
        assert endpoint.headers["X-Amz-Security-Token"] == "session-token"
    assert client.started == [{
        "browserIdentifier": "aws.browser.v1", "name": "sdpm-check", "sessionTimeoutSeconds": 120,
        "viewPort": {"width": 1920, "height": 1080},
    }]
    assert client.stopped == [{"browserIdentifier": "aws.browser.v1", "sessionId": "s1"}]


def test_session_is_stopped_when_the_check_raises():
    client = StubClient()
    with pytest.raises(RuntimeError, match="boom"):
        with _source(client)(1280, 720):
            raise RuntimeError("boom")
    assert client.stopped == [{"browserIdentifier": "aws.browser.v1", "sessionId": "s1"}]


def test_failing_stop_is_logged_not_raised(caplog):
    client = StubClient(stop_error=RuntimeError("throttled"))
    with caplog.at_level(logging.WARNING, logger="sdpm.agentcore_browser"):
        with _source(client)(1920, 1080):
            pass
    assert "stop_browser_session failed for s1" in caplog.text


def test_client_is_created_on_first_use_only():
    calls: list = []
    source = _source(StubClient(), calls)
    assert calls == [] and source.browser_name == "AgentCore Browser"
    for _ in range(2):
        with source(1920, 1080):
            pass
    assert calls == [1]


def test_failing_start_is_a_failed_check(tmp_path, monkeypatch):
    monkeypatch.delenv("SDPM_BROWSER")
    client = StubClient(start_error=RuntimeError("AccessDeniedException"))
    browser_mod.register_browser_source(_source(client))
    html = tmp_path / "output.html"
    html.write_text("<!doctype html><html></html>", encoding="utf-8")

    result = check_deck(html, ["cover"], slide_size=(1920, 1080), line_map=[], layouts={}, decorations={})

    assert result["status"] == "failed" and result["browser"] == "AgentCore Browser"
    assert result["note"].startswith(
        "Browser check could not run (AgentCore Browser): RuntimeError: AccessDeniedException"
    )
    assert client.stopped == []  # nothing was started


def _import_server(name: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "servers" / "remote" / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_importing_the_server_creates_no_boto3_client_and_registers_agentcore():
    boom = MagicMock(side_effect=AssertionError("boto3 used at import"))
    with patch("boto3.client", boom), patch("boto3.resource", boom), patch("boto3.Session", boom):
        server = _import_server("remote_server_browser_under_test")
    boom.assert_not_called()
    source = browser_mod.registered_browser_source()
    assert source is not None and source.browser_name == "AgentCore Browser"

    browser_mod.register_browser_source(None)
    server._register_browser_source()
    assert browser_mod.registered_browser_source().browser_name == "AgentCore Browser"
