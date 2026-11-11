# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Session ownership — bind runtime sessions to the user who owns them.

A session id created by the Web UI starts with ``owner_prefix(sub)``, the first 16
hex characters of SHA-256 over the signed-in user's ``sub``. The agent and the
MCP server admit an owner-prefixed id only for that user, and each runtime
process serves a single user (``ProcessOwner``).

The JWT has already been validated by the AgentCore Runtime authorizer before
the request reaches the container, so ``sub_from_jwt`` only decodes the payload.

The Web UI mirror is ``web-ui/src/lib/sessionId.ts``; both test suites pin the
same test vector.
"""

import base64
import hashlib
import hmac
import json
import re
import threading

PREFIX_LEN = 16

# A prefixed id: 16 lowercase hex characters, then "-". No id of the earlier
# formats matches: a UUID has its first "-" at index 8, and a padded deck id
# has no "-" at all.
_PREFIXED = re.compile(r"^[0-9a-f]{16}-")


def owner_prefix(sub: str) -> str:
    """Return the session id prefix of ``sub`` (16 lowercase hex characters)."""
    return hashlib.sha256(sub.encode("utf-8")).hexdigest()[:PREFIX_LEN]


def is_owner_prefixed(session_id: str) -> bool:
    """True when ``session_id`` has the owner-prefixed shape."""
    return bool(_PREFIXED.match(session_id or ""))


def belongs_to(session_id: str, sub: str) -> bool:
    """True when ``session_id`` is owner-prefixed and its prefix is ``sub``'s.

    Suffixes after the prefix (composer groups ``-gN``) do not matter.
    """
    if not sub or not is_owner_prefixed(session_id):
        return False
    return hmac.compare_digest(session_id[:PREFIX_LEN], owner_prefix(sub))


def owned_mcp_session_id(session_id: str, sub: str) -> str:
    """Return the ``Mcp-Session-Id`` the agent sends for ``session_id``.

    An id that already belongs to ``sub`` is sent unchanged; any other id gets
    ``sub``'s prefix in front, so the MCP session always carries its owner.
    Without a ``sub`` the id is returned unchanged.
    """
    if not sub or not session_id or belongs_to(session_id, sub):
        return session_id
    return f"{owner_prefix(sub)}-{session_id}"


_GROUP_SUFFIX = re.compile(r"-g\d+$")


def chat_session_id(mcp_session_id: str, sub: str) -> str | None:
    """Return the chat session id behind an ``Mcp-Session-Id``, or None.

    The agent sends the runtime session id unchanged when it already belongs to
    ``sub`` (``owned_mcp_session_id``); composer groups append ``-g<N>``, which is
    stripped here. Anything that does not belong to ``sub`` maps to None.
    """
    session_id = _GROUP_SUFFIX.sub("", mcp_session_id or "")
    return session_id if belongs_to(session_id, sub) else None


def sub_from_jwt(token: str) -> str:
    """Return the ``sub`` claim of a JWT (payload decode only), or ``""``."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        sub = claims.get("sub", "") if isinstance(claims, dict) else ""
    except (IndexError, ValueError, AttributeError):
        return ""
    return sub if isinstance(sub, str) else ""


class ProcessOwner:
    """The one user a runtime process serves: the first ``sub`` that claims it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sub: str | None = None

    def claim(self, sub: str) -> bool:
        """Bind the process to ``sub`` if unbound; True when ``sub`` is the owner."""
        if not sub:
            return False
        with self._lock:
            if self._sub is None:
                self._sub = sub
                return True
            return hmac.compare_digest(self._sub.encode("utf-8"), sub.encode("utf-8"))
