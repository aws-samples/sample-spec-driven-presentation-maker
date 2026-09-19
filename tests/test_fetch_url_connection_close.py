# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""fetch_url must survive `Connection: close` and keep its idle read timeout.

Background: fetch_url sends `Connection: close`, so http.client sets
`response.will_close` and `getresponse()` hands the connection to the response by
calling `HTTPConnection.close()`, which sets `conn.sock = None` — before the body
is read at all. The body loop then called `conn.sock.settimeout(...)` on every
iteration, so **every** URL fetch died with
`AttributeError: 'NoneType' object has no attribute 'settimeout'`. The line
carried a `# type: ignore[union-attr]`, so the type checker had been silenced
rather than the case handled.

Two things had to hold in the fix, and both are pinned here:

1. The fetch succeeds even though `conn.sock` is gone.
2. The idle read timeout is still re-armed during the body read. A bare
   `if conn.sock is not None:` guard would satisfy (1) while silently removing
   the only reason that line exists.

There is also a second shape to avoid: once http.client finishes the body it
closes the response's file object, which drops the last socket reference and
really closes the fd, so re-arming after that raises EBADF.
"""

import socket
import ssl
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "sdpm") not in sys.path:
    sys.path.insert(0, str(_ROOT / "sdpm"))

fetcher = pytest.importorskip("sdpm.tools.attachment.fetcher")

_PAYLOAD = b"P" * 200_000
_PUBLIC_IP = "93.184.216.34"


class _FakeSocket:
    """Records settimeout calls; refuses them once the fd is gone."""

    def __init__(self):
        self.timeouts: list[float] = []
        self.dead = False

    def settimeout(self, value):
        if self.dead:
            raise OSError(9, "Bad file descriptor")
        self.timeouts.append(value)

    def close(self):
        pass


class _FakeResponse:
    def __init__(self, sock: _FakeSocket):
        self.status = 200
        self.reason = "OK"
        self._pos = 0
        self._sock = sock
        self.fp = object()
        self.will_close = True

    def getheaders(self):
        return [("Content-Length", str(len(_PAYLOAD))), ("Content-Type", "image/png")]

    def getheader(self, name, default=None):
        for k, v in self.getheaders():
            if k.lower() == name.lower():
                return v
        return default

    def isclosed(self):
        return self.fp is None

    def read(self, n=-1):
        if self.fp is None:
            return b""
        chunk = _PAYLOAD[self._pos:self._pos + (n if n and n > 0 else len(_PAYLOAD))]
        self._pos += len(chunk)
        if not chunk:
            # http.client closes the body here; that drops the last socket
            # reference and really closes the fd.
            self.fp = None
            self._sock.dead = True
        return chunk

    def close(self):
        self.fp = None


class _FakeConnection:
    def __init__(self, *args, **kwargs):
        self.sock = None
        self.response: _FakeResponse | None = None

    def connect(self):
        self.sock = _FakeSocket()

    def request(self, method, path, headers=None, body=None):
        pass

    def getresponse(self):
        self.response = _FakeResponse(self.sock)
        # The behaviour under test: a will_close response makes http.client drop
        # the connection's own socket reference.
        self.sock = None
        return self.response

    def close(self):
        pass


@pytest.fixture()
def driven_fetch(monkeypatch):
    """Drive fetch_url against a fake connection and return (result, socket).

    fetch_url resolves DNS itself and pins the IP (so DNS cannot be resolved a
    second time), builds a plain HTTPConnection against that IP, and assigns a
    TLS-wrapped socket to conn.sock by hand. The fakes therefore replace
    `fetcher.HTTPConnection`, the resolver, and the TLS wrap.
    """
    conns: list[_FakeConnection] = []

    def make_conn(*args, **kwargs):
        conn = _FakeConnection()
        conns.append(conn)
        return conn

    monkeypatch.setattr(fetcher, "HTTPConnection", make_conn)
    monkeypatch.setattr(fetcher, "_resolve_and_validate", lambda hostname: [_PUBLIC_IP])
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: _FakeSocket())

    class _Ctx:
        minimum_version = None

        def wrap_socket(self, sock, server_hostname=None):
            return _FakeSocket()

    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **kw: _Ctx())

    result = fetcher.fetch_url("https://example.com/a.png")
    assert conns, "fetch_url never built a connection — the fake is not wired in"
    return result, conns[0].response._sock


def test_fetch_succeeds_when_the_connection_socket_is_dropped(driven_fetch):
    """The regression: conn.sock is None before the body is read."""
    result, _sock = driven_fetch
    data = result.data if hasattr(result, "data") else result[0]
    assert data == _PAYLOAD


def test_idle_timeout_is_re_armed_during_the_body_read(driven_fetch):
    """A guard that merely skips settimeout would leave this at one.

    One call always happens before `getresponse()`, so the assertion has to be
    strictly greater than that — otherwise `if conn.sock is not None:` (which can
    never be true here) would satisfy it while the body reads run unbounded. With
    a 200 KB payload read 64 KB at a time the loop re-arms 5 times.
    """
    _result, sock = driven_fetch
    assert len(sock.timeouts) > 1, (
        f"settimeout was called {len(sock.timeouts)} time(s): only the one before "
        "getresponse(). The body reads are no longer bounded by the idle timeout."
    )
    assert all(t <= fetcher.IDLE_READ_TIMEOUT_S for t in sock.timeouts)


def test_timeouts_shrink_with_the_remaining_budget(driven_fetch):
    """Each re-arm is bounded by both the idle timeout and the total budget."""
    _result, sock = driven_fetch
    assert sock.timeouts, "no timeout was ever armed"
    assert all(0 < t <= fetcher.IDLE_READ_TIMEOUT_S for t in sock.timeouts)
    assert all(t <= fetcher.TOTAL_TIMEOUT_S for t in sock.timeouts)


def test_socket_is_not_touched_after_the_body_closes(driven_fetch):
    """Re-arming after the body finished would raise EBADF.

    Reaching this assertion at all means no OSError escaped fetch_url; the fake
    socket raises EBADF once the body is done, exactly as the real fd does.
    """
    result, sock = driven_fetch
    assert sock.dead is True, "the fake never reached the end-of-body state"
    data = result.data if hasattr(result, "data") else result[0]
    assert len(data) == len(_PAYLOAD)
