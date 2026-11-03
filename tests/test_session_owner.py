# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Session ids carry their owner's prefix, and a runtime process serves one user."""

import base64
import json
import threading

import pytest

from shared import session_owner
from shared.session_owner import (
    ProcessOwner,
    belongs_to,
    is_owner_prefixed,
    owned_mcp_session_id,
    owner_prefix,
    sub_from_jwt,
)

P1 = "c6c289e49e9c05b2"  # owner_prefix("user-1"); web-ui/src/lib/sessionId.test.ts pins the same
P2 = "d92b69cfb82cecab"  # owner_prefix("user-2")
UUID = "0f8c6a4e-2b1d-4c3e-9a7f-5d6e7f8a9b0c"
PADDED_DECK = "a1b2c3d4".ljust(36, "0")


def _jwt(claims) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"h.{body}.s"


def test_owner_prefix_vectors():
    assert owner_prefix("user-1") == P1
    assert owner_prefix("user-2") == P2


@pytest.mark.parametrize("sid, expected", [
    (f"{P1}-{UUID}", True),
    (f"{P1}-{PADDED_DECK}", True),
    (f"{P1}-{UUID}-g12", True),
    (UUID, False),
    (PADDED_DECK, False),
    ("s" * 33, False),
    (f"{UUID}-g12", False),
    (f"{P1.upper()}-{UUID}", False),
    ("", False),
])
def test_is_owner_prefixed(sid, expected):
    assert is_owner_prefixed(sid) is expected


def test_prefixed_ids_fit_the_runtime_session_id_bounds():
    for sid in (f"{P1}-{UUID}", f"{P1}-{PADDED_DECK}"):
        assert len(sid) == 53
        assert 33 <= len(sid) <= 256


def test_belongs_to():
    assert belongs_to(f"{P1}-{UUID}", "user-1")
    assert belongs_to(f"{P1}-{UUID}-g3", "user-1")
    assert not belongs_to(f"{P1}-{UUID}", "user-2")
    assert not belongs_to(f"{P1}-{UUID}", "")
    assert not belongs_to(UUID, "user-1")


def test_same_deck_gets_different_ids_per_user():
    assert f"{owner_prefix('user-1')}-{PADDED_DECK}" != f"{owner_prefix('user-2')}-{PADDED_DECK}"
    assert not belongs_to(f"{P2}-{PADDED_DECK}", "user-1")


def test_belongs_to_compares_in_constant_time(monkeypatch):
    calls: list[tuple] = []
    real = session_owner.hmac.compare_digest

    def recorder(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(session_owner.hmac, "compare_digest", recorder)

    assert belongs_to(f"{P1}-{UUID}", "user-1")
    assert not belongs_to(f"{P2}-{UUID}", "user-1")
    assert calls == [(P1, P1), (P2, P1)]


def test_owned_mcp_session_id():
    assert owned_mcp_session_id("sess-1234567890", "user-1") == f"{P1}-sess-1234567890"
    assert owned_mcp_session_id(f"{P1}-{UUID}", "user-1") == f"{P1}-{UUID}"
    assert owned_mcp_session_id(f"{P1}-{UUID}-g3", "user-1") == f"{P1}-{UUID}-g3"
    assert owned_mcp_session_id(f"{P2}-{UUID}", "user-1") == f"{P1}-{P2}-{UUID}"
    assert owned_mcp_session_id("sess-1", "") == "sess-1"
    assert owned_mcp_session_id("", "user-1") == ""


def test_process_owner_first_claim_wins():
    owner = ProcessOwner()
    assert owner.claim("user-1")
    assert owner.claim("user-1")
    assert not owner.claim("user-2")


def test_process_owner_empty_sub_never_claims():
    owner = ProcessOwner()
    assert not owner.claim("")
    assert owner.claim("user-2")


def test_process_owner_concurrent_claims_bind_one_sub():
    owner = ProcessOwner()
    barrier = threading.Barrier(8)
    results: list[bool] = []
    lock = threading.Lock()

    def claim(i):
        barrier.wait()
        ok = owner.claim(f"user-{i}")
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1


def test_sub_from_jwt():
    assert sub_from_jwt(_jwt({"sub": "user-1"})) == "user-1"
    assert sub_from_jwt(_jwt({"sub": 42})) == ""
    assert sub_from_jwt(_jwt(["sub"])) == ""
    assert sub_from_jwt("garbage") == ""
    assert sub_from_jwt("a.!!!.b") == ""
    assert sub_from_jwt("") == ""
