# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Admit an invocation only for the owner of its session.

The AgentCore Runtime authorizer has validated the JWT before the request reaches
this container; ``sub`` comes from that token. A session id is admitted when:

- it carries the owner prefix of ``sub`` (``shared.session_owner``), or
- it has an earlier format and AgentCore Memory already holds this user's events
  for it (sessions created before ids carried the prefix);

and this process serves no other user. Refusals carry a code and no details.
"""

import asyncio
import logging
import os

from errors import AUTH, BAD_INPUT, SERVICE_UNAVAILABLE, SESSION_RELOAD_REQUIRED, error_event
from shared.session_owner import ProcessOwner, belongs_to, is_owner_prefixed

logger = logging.getLogger("sdpm.agent")

# The one user this process serves (set by the first admitted invocation).
_process_owner = ProcessOwner()
# (sub, session id) pairs of earlier-format ids confirmed through Memory.
_owned_legacy: set[tuple[str, str]] = set()
_client = None


def _memory_client():
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        _client = boto3.client(
            "bedrock-agentcore",
            region_name=region,
            config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 2}),
        )
    return _client


def _has_own_events(memory_id: str, sub: str, session_id: str) -> bool:
    response = _memory_client().list_events(
        memoryId=memory_id, actorId=sub, sessionId=session_id, maxResults=1, includePayloads=False,
    )
    return bool(response.get("events"))


def _refuse(reason: str, session_id: str, event: dict) -> tuple[None, dict]:
    logger.warning("Session refused (%s) for session %s", reason, (session_id or "")[:12])
    return None, event


async def admit(
    payload_session_id: str, header_session_id: str | None, sub: str,
) -> tuple[str | None, dict | None]:
    """Return ``(session_id, None)`` when admitted, else ``(None, error_event)``.

    The platform routes by the session header, so that id is the one checked;
    without the header (local runs) the payload id is used.
    """
    if header_session_id and header_session_id != payload_session_id:
        return _refuse("id mismatch", header_session_id, error_event("Session id mismatch", code=BAD_INPUT))
    session_id = header_session_id or payload_session_id

    if is_owner_prefixed(session_id):
        if not belongs_to(session_id, sub):
            return _refuse("owner", session_id, error_event("Session not available", code=AUTH))
    elif (sub, session_id) not in _owned_legacy:
        memory_id = os.environ.get("MEMORY_ID", "")
        if not memory_id or memory_id == "PLACEHOLDER":
            return _refuse("legacy", session_id, error_event("Reload the page", code=SESSION_RELOAD_REQUIRED))
        try:
            owned = await asyncio.to_thread(_has_own_events, memory_id, sub, session_id)
        except Exception:
            logger.exception("Session check failed for session %s", session_id[:12])
            return None, error_event("Session check unavailable", code=SERVICE_UNAVAILABLE)
        if not owned:
            return _refuse("legacy", session_id, error_event("Reload the page", code=SESSION_RELOAD_REQUIRED))
        _owned_legacy.add((sub, session_id))

    if not _process_owner.claim(sub):
        return _refuse("process", session_id, error_event("Session not available", code=AUTH))
    return session_id, None
