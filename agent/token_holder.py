# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The caller's JWT for a session's MCP clients, swapped per turn.

A session keeps its Presentation Maker clients across turns (session_handle.py), but
the Cognito access token they send expires after 60 minutes. Each turn (and each steer)
hands the holder the token of the request that carried it; every HTTP request of the
clients reads the latest one through HolderAuth.
"""

import hmac
import logging
import threading
import time

import httpx

from shared.session_owner import sub_from_jwt

logger = logging.getLogger("sdpm.agent")


class TokenHolder:
    """The latest JWT of one user. A token of another user is refused."""

    def __init__(self, sub: str, token: str):
        if not sub:
            raise ValueError("TokenHolder needs the owner's sub")
        self._sub = sub
        self._lock = threading.Lock()
        self._token = ""
        self._version = 0
        # When a request was refused (401) with no newer token to retry with.
        self.unauthorized_at: float | None = None
        self.set(token)

    @property
    def sub(self) -> str:
        return self._sub

    @property
    def token(self) -> str:
        with self._lock:
            return self._token

    @property
    def version(self) -> int:
        """Grows by one each time the token changes."""
        with self._lock:
            return self._version

    def set(self, token: str) -> None:
        """Use ``token`` from now on. Raises PermissionError when it names another user."""
        sub = sub_from_jwt(token)
        if not sub or not hmac.compare_digest(sub.encode("utf-8"), self._sub.encode("utf-8")):
            raise PermissionError("token of another user")
        with self._lock:
            if token != self._token:
                self._token = token
                self._version += 1
                self.unauthorized_at = None


class HolderAuth(httpx.Auth):
    """Sets ``Authorization: Bearer <latest token>`` on every request.

    A 401 is retried once when the holder got a newer token after the request was
    built (a turn swapped it meanwhile); otherwise the response goes back to the MCP
    transport, which ends the session, and the client is restarted at its next use
    (mcp_clients.ReconnectingMCPClient).
    """

    def __init__(self, holder: TokenHolder):
        self.holder = holder

    def auth_flow(self, request: httpx.Request):
        version = self.holder.version
        request.headers["Authorization"] = f"Bearer {self.holder.token}"
        response = yield request
        if response.status_code != 401:
            return
        if self.holder.version != version:
            request.headers["Authorization"] = f"Bearer {self.holder.token}"
            yield request
            return
        self.holder.unauthorized_at = time.time()
        logger.warning("MCP request refused (401) and no newer token to retry with")
