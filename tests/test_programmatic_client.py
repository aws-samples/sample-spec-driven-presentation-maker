# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The reference programmatic client (examples/programmatic-client/sdpm_client.py).

Pins what it shares with the server side: the session id rule the agent admits
(shared/session_owner.py), the loopback-only sign-in listener, the 0600 token file,
and the exit code for a refused refresh token. Network calls are faked.
"""

from __future__ import annotations

import importlib.util
import io
import json
import stat
import sys
import urllib.error
from pathlib import Path

import pytest

from shared.session_owner import belongs_to, owner_prefix

_PATH = Path(__file__).resolve().parents[1] / "examples" / "programmatic-client" / "sdpm_client.py"
_spec = importlib.util.spec_from_file_location("sdpm_client_under_test", _PATH)
client = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = client  # dataclasses look the module up while the file runs
_spec.loader.exec_module(client)

DEPLOYMENT = client.Deployment(
    client_id="programmatic-client-id", region="ap-northeast-1",
    agent_runtime_arn="arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:runtime/sdpm_agent-x",
    api_base_url="https://api.example.com", authorization_endpoint="https://auth.example.com/oauth2/authorize",
    token_endpoint="https://auth.example.com/oauth2/token",
)


def test_session_ids_are_the_ones_the_agent_admits_for_the_user():
    assert client.owner_prefix("user-1") == owner_prefix("user-1") == "c6c289e49e9c05b2"  # pragma: allowlist secret
    session_id = client.new_session_id("user-1")
    assert belongs_to(session_id, "user-1")
    assert not belongs_to(session_id, "user-2")
    assert len(session_id) >= 33  # AgentCore's minimum session id length


def test_the_sign_in_listener_binds_loopback_only(monkeypatch):
    bound = []

    class _Server:
        def __init__(self, address, handler):
            bound.append(address)
            raise OSError(48, "Address already in use")

    monkeypatch.setattr(client, "HTTPServer", _Server)
    with pytest.raises(client.ClientError, match="cannot listen on http://127.0.0.1:8765"):
        client._wait_for_redirect("https://auth.example.com", open_browser=False, timeout_s=1)
    assert bound == [("127.0.0.1", 8765)]


def test_the_token_file_is_private_and_round_trips(tmp_path):
    store = f"file:{tmp_path / 'sub' / 'token.json'}"
    client.save_refresh_token(store, "rt-value", DEPLOYMENT)
    path = tmp_path / "sub" / "token.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["client_id"] == "programmatic-client-id"
    assert client.load_refresh_token(store) == "rt-value"


def _refused(error: str):
    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(json.dumps({"error": error}).encode()))
    return urlopen


def test_a_refused_refresh_token_is_its_own_error(monkeypatch):
    monkeypatch.setattr(client.urllib.request, "urlopen", _refused("invalid_grant"))
    with pytest.raises(client.RefreshTokenExpired):
        client.token_request(DEPLOYMENT, {"grant_type": "refresh_token", "refresh_token": "x"})
    # A refused authorization code is a sign-in failure, not an expired token.
    with pytest.raises(client.ClientError) as e:
        client.token_request(DEPLOYMENT, {"grant_type": "authorization_code", "code": "x"})
    assert not isinstance(e.value, client.RefreshTokenExpired)


def test_status_exits_3_when_the_refresh_token_is_refused(monkeypatch, capsys):
    def expired(settings, session_id):
        raise client.RefreshTokenExpired("the refresh token is expired, revoked or invalid: run login again")

    monkeypatch.setattr(client, "job_status", expired)
    code = client.main(["status", "s-1", "--site", "https://site.example.com", "--client-id", "c", "--store", "file:/nonexistent"])
    assert code == client.EXIT_TOKEN == 3
    assert "login again" in capsys.readouterr().err
