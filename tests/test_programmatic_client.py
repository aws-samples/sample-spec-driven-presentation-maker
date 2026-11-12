# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The reference programmatic client (examples/programmatic-client/sdpm_client.py).

Pins what it shares with the server side: the session id rule the agent admits
(shared/session_owner.py), the loopback-only sign-in listener, the 0600 token file,
and the exit code for a refused refresh token. Network calls are faked.
"""

from __future__ import annotations

import asyncio
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


# -- the job's state from its work period (R7) ------------------------------------------


def _period(working=False, how=None, reclaimed=False):
    return {"working": working, "how": how, "reclaimed": reclaimed}


@pytest.mark.parametrize("has_pptx", [False, True])
def test_a_working_session_is_running_with_or_without_a_pptx(has_pptx):
    # The agent may rebuild the PPTX under a new name while it works: a PPTX is not done.
    assert client.job_state(_period(working=True), has_pptx) == "running"


@pytest.mark.parametrize(("how", "has_pptx", "state"), [
    ("finished", True, "done"),
    ("finished", False, "needs_input"),
    ("cancelled", True, "cancelled"),
    ("error", True, "failed"),
    ("watchdog", False, "failed"),
    ("sigterm", True, "failed"),
])
def test_an_ended_period_maps_its_how(how, has_pptx, state):
    assert client.job_state(_period(how=how), has_pptx) == state
    assert state in client.FINAL_STATES


@pytest.mark.parametrize(("has_pptx", "state"), [(True, "done"), (False, "needs_input")])
def test_a_reclaimed_session_falls_back_to_the_pptx(has_pptx, state):
    assert client.job_state(_period(reclaimed=True), has_pptx) == state


@pytest.mark.parametrize("has_pptx", [False, True])
def test_an_ended_period_without_its_how_is_never_done(has_pptx):
    state = client.job_state(_period(), has_pptx)
    assert state == "running"
    assert state not in client.FINAL_STATES


class _FakeSocket:
    """The agent's side of /ws for ``_work_period``: answers each ``resume`` from a session."""

    def __init__(self, working, events):
        self.working = working
        self.events = events  # the ended period's events, seq 1..n
        self.sent: list[dict] = []
        self.out: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, text):
        message = json.loads(text)
        self.sent.append(message)
        head = len(self.events)
        if self.working is None:  # not in the process
            self.out.append(json.dumps({"ctl": "resumeAck", "working": False, "head": 0, "period_start": 1,
                                        "replay_from": 1, "complete": True}))
            return
        first = message["from_seq"] + 1
        items = [{"seq": i + 1, "ev": ev} for i, ev in enumerate(self.events) if i + 1 >= first]
        self.out.append(json.dumps({"ctl": "resumeAck", "working": self.working, "head": head, "period_start": 1,
                                    "replay_from": items[0]["seq"] if items else head + 1, "complete": True}))
        if items:
            # The last item split across chunk frames, the others batched.
            *rest, last = items
            if rest:
                self.out.append(json.dumps({"batch": rest}))
            text = json.dumps(last)
            self.out += [json.dumps({"chunk": "c1", "i": i, "n": 2, "data": part})
                         for i, part in enumerate((text[:10], text[10:]))]

    async def recv(self):
        return self.out.pop(0)


def _work_period(monkeypatch, socket):
    monkeypatch.setattr(client, "_connect", lambda deployment, token, session_id: socket)
    return asyncio.run(client._work_period(DEPLOYMENT, "access", "s-1"))


def test_work_period_reads_the_how_of_the_ended_period(monkeypatch):
    events = [{"work": {"state": "busy"}}] + [{"turnEnd": {"how": "finished"}}] * 20 + [
        {"work": {"state": "idle", "how": "finished"}}]
    socket = _FakeSocket(working=False, events=events)
    assert _work_period(monkeypatch, socket) == {"working": False, "how": "finished", "reclaimed": False}
    # The first resume replays nothing; the second only the period's last events.
    assert socket.sent == [{"type": "resume", "from_seq": client.LATEST_SEQ},
                           {"type": "resume", "from_seq": len(events) - client.LOOKBACK}]


def test_work_period_of_a_working_session_needs_one_resume(monkeypatch):
    socket = _FakeSocket(working=True, events=[{"work": {"state": "busy"}}])
    assert _work_period(monkeypatch, socket) == {"working": True, "how": None, "reclaimed": False}
    assert len(socket.sent) == 1


def test_work_period_of_a_session_the_agent_does_not_hold_is_reclaimed(monkeypatch):
    socket = _FakeSocket(working=None, events=[])
    assert _work_period(monkeypatch, socket) == {"working": False, "how": None, "reclaimed": True}
    assert len(socket.sent) == 1


def test_work_period_without_a_work_idle_reports_no_how(monkeypatch):
    socket = _FakeSocket(working=False, events=[{"work": {"state": "busy"}}, {"turnEnd": {"how": "finished"}}])
    period = _work_period(monkeypatch, socket)
    assert period == {"working": False, "how": None, "reclaimed": False}
    assert client.job_state(period, has_pptx=True) == "running"
