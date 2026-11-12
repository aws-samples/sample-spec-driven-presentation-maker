# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""AgentCore Browser as the browser of the HTML browser check (design §9).

The runtime image has no Chrome, so the remote server registers this source with
``sdpm.engine.html.browser.register_browser_source``: each check starts one
``aws.browser.v1`` session with the deck's size as viewport, connects to its
automation stream over CDP with SigV4-signed headers, and stops the session when
the check is done, whatever happened. The core never imports this module.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.
# The runtime role may call only the three browser actions on aws.browser.v1
# (infra/lib/runtime-stack.ts).
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Any, Callable, ContextManager, Iterator

from sdpm.engine.html.browser import BrowserEndpoint, BrowserSource

logger = logging.getLogger("sdpm.agentcore_browser")

BROWSER_ID = "aws.browser.v1"
SESSION_TIMEOUT_S = 120
SESSION_NAME = "sdpm-check"
DISPLAY_NAME = "AgentCore Browser"
_SIGNED_HEADERS = ("authorization", "x-amz-date", "x-amz-security-token")


def _sign(url: str, credentials: Any, region: str) -> dict[str, str]:
    """SigV4 headers for the WebSocket upgrade (a GET on the https form of ``url``)."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    request = AWSRequest(method="GET", url="https://" + url.split("://", 1)[-1])
    SigV4Auth(credentials.get_frozen_credentials(), "bedrock-agentcore", region).add_auth(request)
    return {k: v for k, v in request.headers.items() if k.lower() in _SIGNED_HEADERS}


def make_source(
    region: str,
    *,
    client_factory: Callable[[], Any] | None = None,
    credentials_factory: Callable[[], Any] | None = None,
) -> BrowserSource:
    """A ``BrowserSource`` backed by AgentCore Browser in ``region``.

    The ``bedrock-agentcore`` client (``boto_config.SHORT_API``) and the credentials
    are created on the first check, never here: the platform V2 snapshot taken after
    startup must hold no boto3 connection state. The factories replace them in tests.
    """
    lock = threading.Lock()
    state: dict[str, Any] = {}

    def _clients() -> tuple[Any, Any]:
        with lock:
            if "client" not in state:
                session = None
                if client_factory is None or credentials_factory is None:
                    import boto3

                    session = boto3.Session(region_name=region)
                if client_factory is not None:
                    state["client"] = client_factory()
                else:
                    from boto_config import SHORT_API

                    state["client"] = session.client("bedrock-agentcore", config=SHORT_API)
                state["credentials"] = (credentials_factory() if credentials_factory is not None
                                        else session.get_credentials())
            return state["client"], state["credentials"]

    @contextlib.contextmanager
    def session(width: int, height: int) -> Iterator[BrowserEndpoint]:
        client, credentials = _clients()
        started = client.start_browser_session(
            browserIdentifier=BROWSER_ID,
            name=SESSION_NAME,
            sessionTimeoutSeconds=SESSION_TIMEOUT_S,
            viewPort={"width": int(width), "height": int(height)},
        )
        session_id = started["sessionId"]
        try:
            url = started["streams"]["automationStream"]["streamEndpoint"]
            yield BrowserEndpoint(url, _sign(url, credentials, region), DISPLAY_NAME)
        finally:
            try:
                client.stop_browser_session(browserIdentifier=BROWSER_ID, sessionId=session_id)
            except Exception:  # the session times out on its own (SESSION_TIMEOUT_S)
                logger.warning("stop_browser_session failed for %s", session_id, exc_info=True)

    def source(width: int, height: int) -> ContextManager[BrowserEndpoint]:
        return session(width, height)

    source.browser_name = DISPLAY_NAME  # type: ignore[attr-defined]  # named before it starts
    return source


__all__ = ["BROWSER_ID", "DISPLAY_NAME", "SESSION_TIMEOUT_S", "make_source"]
