# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The remote MCP server admits a session only for its owner.

An owner-prefixed session id must carry the prefix of the token's user (also for a
composer group's ``<sid>-gN``), and each server process serves one user. Requests go
through the app as server.py runs it (FastMCP + the header middleware).
"""

import asyncio

import pytest

import test_remote_warmup_preload as harness

server = harness.server  # the fixture: servers/remote/server.py imported fresh per test
_bearer = harness._bearer
_post = harness._post

P1 = "c6c289e49e9c05b2"  # owner_prefix("user-1")
P2 = "d92b69cfb82cecab"  # owner_prefix("user-2")
OWN = f"{P1}-00000000-0000-4000-8000-000000000000"
OTHER = f"{P2}-00000000-0000-4000-8000-000000000000"
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def _headers(session_id: str | None, sub: str | None = "user-1", **extra) -> dict:
    headers = dict(extra)
    if sub is not None:
        headers["authorization"] = _bearer(sub)
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return headers


def _list(module, session_id: str | None, sub: str | None = "user-1", **extra):
    return _post(module, LIST, headers=_headers(session_id, sub, **extra))


def _statuses(module, *requests: tuple[dict, dict]) -> list[int]:
    """POST each (body, headers) in turn through one app run (FastMCP's manager runs once)."""
    import httpx

    app = module.mcp.streamable_http_app()
    app.add_middleware(module._CaptureHeadersMiddleware)

    async def run():
        async with module.mcp.session_manager.run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                out = []
                for body, headers in requests:
                    r = await client.post(
                        "/mcp", json=body,
                        headers={"accept": "application/json, text/event-stream", **headers},
                    )
                    out.append(r.status_code)
                return out

    return asyncio.run(run())


@pytest.mark.parametrize("session_id, status", [
    (OWN, 200),
    (OTHER, 403),
    (f"{OWN}-g3", 200),
    (f"{OTHER}-g3", 403),
])
def test_owner_prefixed_ids(server, session_id, status):
    module, *_ = server

    r = _list(module, session_id)

    assert r.status_code == status
    if status == 403:
        assert r.json() == {"error": "forbidden"}


def test_runtime_session_header_of_another_user_is_refused(server):
    module, *_ = server

    r = _list(module, OWN, **{"x-amzn-bedrock-agentcore-runtime-session-id": OTHER})

    assert r.status_code == 403


def test_legacy_id_binds_the_process_to_its_first_user(server):
    module, *_ = server

    assert _statuses(
        module,
        (LIST, _headers("sess-1")),
        (LIST, _headers("sess-1", sub="user-2")),
        (LIST, _headers("sess-1")),
    ) == [200, 403, 200]


def test_other_users_own_prefixed_id_is_refused_on_a_bound_process(server):
    module, *_ = server

    assert _statuses(module, (LIST, _headers(OWN)), (LIST, _headers(OTHER, sub="user-2"))) == [200, 403]


def test_ping_without_authorization_passes_and_does_not_bind(server):
    module, *_ = server

    assert _statuses(module, (PING, {}), (LIST, _headers(OTHER, sub="user-2"))) == [200, 200]


def test_authorization_without_sub_is_refused(server):
    module, *_ = server

    r = _post(module, LIST, headers={"authorization": "Bearer not-a-jwt", "mcp-session-id": "sess-1"})

    assert r.status_code == 403


def test_refused_request_does_not_start_the_warm_up(server, monkeypatch):
    module, _, _, warm_ups = server
    monkeypatch.setattr(module, "_WARMUP_QUIET_S", 0.05)

    r = _post(module, LIST, headers={"authorization": _bearer(), "mcp-session-id": OTHER}, linger=0.2)

    assert r.status_code == 403
    assert warm_ups == []
    assert module._client_requests_in_flight == 0
    assert module._warmup_timer is None
