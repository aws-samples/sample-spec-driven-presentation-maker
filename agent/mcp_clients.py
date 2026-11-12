# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP client factories, process-resident clients and server instruction collection."""

import asyncio
import logging
import os
import threading
import urllib.parse
from concurrent.futures import Future
from typing import Callable

from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp import MCPClient
from strands.types.exceptions import MCPClientInitializationError

from shared.session_owner import owned_mcp_session_id, sub_from_jwt
from token_holder import HolderAuth, TokenHolder

logger = logging.getLogger("sdpm.agent")

# MCP server definitions: (display_name, required)
MCP_DEFS: list[tuple[str, bool]] = [
    ("Presentation Maker", True),
    ("AWS Knowledge", False),
    ("AWS Pricing", False),
]


def mcp_agentcore_runtime(
    jwt_token: str = "",
    session_id: str = "",
    tool_filters: dict | None = None,
    token: TokenHolder | None = None,
) -> MCPClient:
    """Pattern 1: Amazon Bedrock AgentCore Runtime MCP Server with JWT Bearer authentication.

    Args:
        jwt_token: JWT access token from the caller (without "Bearer " prefix).
            Sent as a fixed ``Authorization`` header; unused when ``token`` is given.
        session_id: Caller's session id, sent as ``Mcp-Session-Id``. AgentCore
            routes by that header, so omitting it makes every request land on a
            new microVM — see the note below. Empty string disables the header.
        tool_filters: Optional tool filter dict (e.g. {"allowed": ["tool1", "tool2"]}).
        token: The session's TokenHolder (session_handle.py). Every request then reads
            the latest JWT (HolderAuth) and the client is a ReconnectingMCPClient,
            kept across turns.
    """
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    runtime_arn = os.environ["MCP_RUNTIME_ARN"]
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"

    transport: dict = {"url": url, "timeout": 120, "terminate_on_close": False}
    if token is not None:
        headers: dict = {}
        transport["auth"] = HolderAuth(token)
        sub = token.sub
    else:
        headers = {"Authorization": f"Bearer {jwt_token}"}
        sub = sub_from_jwt(jwt_token)
    transport["headers"] = headers
    if session_id:
        # microVM stickiness: AgentCore routes MCP requests to a microVM by this
        # header. Without it the platform mints a fresh session id per request,
        # so every agent turn pays a new-session start on the MCP runtime. That
        # runtime's image is large (LibreOffice), and its cold start was measured
        # at 17.6-19.7s in ap-northeast-1 when no warm capacity was available,
        # versus 0.18-0.20s once requests carry a consistent id.
        #
        # An expired id is safe to keep sending: measured 2026-09-19, replaying an
        # id after the 900s idle timeout returns HTTP 200 (the platform treats it
        # like any unknown id and starts a session for it) and the call right
        # after is back to 0.18s. No re-initialize fallback is needed. This holds
        # for the stateless server we run (`stateless_http=True` in
        # servers/remote/server.py); stateful MCP is documented to 404 instead.
        #
        # The id always carries the owner prefix of the token's user: an id of an
        # earlier format gets it prepended (shared/session_owner.py).
        headers["Mcp-Session-Id"] = owned_mcp_session_id(session_id, sub)

    kwargs: dict = {}
    if tool_filters:
        kwargs["tool_filters"] = tool_filters

    client_class = ReconnectingMCPClient if token is not None else MCPClient
    return client_class(lambda: streamablehttp_client(**transport), **kwargs)


def _run_blocking(make_coro: Callable[[], object]) -> object:
    """Run a coroutine to completion from sync code, also on a thread with a running loop.

    compose_slides calls MCP synchronously from inside the agent's event loop, where
    asyncio.run is not allowed; the coroutine then runs on a short-lived thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coro())
    result: list = []

    def run() -> None:
        try:
            result.append((True, asyncio.run(make_coro())))
        except BaseException as e:  # noqa: BLE001 - re-raised on the caller's thread
            result.append((False, e))

    thread = threading.Thread(target=run, daemon=True, name="sdpm-mcp-restart")
    thread.start()
    thread.join()
    ok, value = result[0]
    if not ok:
        raise value
    return value


class ReconnectingMCPClient(MCPClient):
    """A Presentation Maker client kept across a session's turns, restarted when its
    MCP session has ended (a 401 with no newer token, a dropped connection).

    The restart keeps the object, so the Agent's MCP tools (which hold it) keep working,
    and keeps its consumers. A call made on an ended session is sent after the restart
    (nothing reached the server); a call that fails in flight returns its error result
    as before, so a write is never sent twice.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._restart_lock = threading.Lock()

    def alive(self) -> bool:
        """True while the MCP session runs.

        The one private probe of this module: MCPClient has no public liveness check,
        and its own calls test this same state before they send anything.
        """
        return self._is_session_active()

    def restart(self) -> None:
        """Start a new MCP session in place if the current one has ended."""
        with self._restart_lock:
            if self.alive():
                return
            consumers = set(self._consumers)
            logger.warning("Presentation Maker MCP session ended; reconnecting")
            try:
                self.stop(None, None, None)
            except Exception as e:  # noqa: BLE001 - the old session is gone either way
                logger.warning("Closing the ended MCP session failed: %s", e)
            # load_tools starts the session and lists the tools again (Strands' own
            # bookkeeping); stop() reset both.
            _run_blocking(self.load_tools)
            self._consumers.update(consumers)

    def call_tool_sync(self, *args, **kwargs):
        if not self.alive():
            self.restart()
        try:
            return super().call_tool_sync(*args, **kwargs)
        except MCPClientInitializationError:  # ended between the check and the call; nothing sent
            self.restart()
            return super().call_tool_sync(*args, **kwargs)

    async def call_tool_async(self, *args, **kwargs):
        if not self.alive():
            await asyncio.to_thread(self.restart)
        try:
            return await super().call_tool_async(*args, **kwargs)
        except MCPClientInitializationError:
            await asyncio.to_thread(self.restart)
            return await super().call_tool_async(*args, **kwargs)


AWS_KNOWLEDGE_URL = "https://knowledge-mcp.global.api.aws"

# The AWS documentation tools the agent offers its model. The allowlist pins the
# set even if the endpoint adds tools later.
AWS_KNOWLEDGE_TOOLS: list[str] = [
    "aws___search_documentation",
    "aws___read_documentation",
    "aws___retrieve_skill",
    "aws___list_regions",
    "aws___get_regional_availability",
]


def mcp_aws_knowledge() -> MCPClient:
    """Pattern 2: AWS Knowledge MCP Server (public endpoint, no authentication).

    The agent uses the AWS documentation tools only. The public endpoint serves
    exactly those and is called without the execution role's credentials.
    """
    return MCPClient(
        lambda: streamablehttp_client(url=AWS_KNOWLEDGE_URL),
        tool_filters={"allowed": list(AWS_KNOWLEDGE_TOOLS)},
    )


def mcp_aws_pricing() -> MCPClient:
    """Pattern 3: Local stdio MCP Server for AWS Pricing."""
    from mcp.client.stdio import StdioServerParameters, stdio_client

    return MCPClient(
        lambda: stdio_client(StdioServerParameters(
            command="awslabs.aws-pricing-mcp-server",
            env={**os.environ, "AWS_REGION": "us-east-1", "FASTMCP_LOG_LEVEL": "ERROR"},
        )),
    )


# Consumer id the process holds on every resident client. Strands stops an MCPClient
# when its last consumer (an Agent's tool registry) goes away; this one never does.
_PROCESS_CONSUMER = "sdpm-process"


class ResidentClient:
    """An MCP client connected once and reused across turns for the life of the process.

    Only for servers that use nothing from the caller: AWS Knowledge (public endpoint)
    and AWS Pricing (stdio subprocess under the execution role). Neither carries the
    user's JWT, and an agent microVM serves one runtime session, so a resident client
    is never shared across users. Presentation Maker carries the JWT and stays per session
    (session_handle.py).
    """

    def __init__(self, name: str, make: Callable[[], MCPClient]):
        self.name = name
        self._make = make
        self._lock = threading.Lock()
        self._client: MCPClient | None = None
        self._pending: Future | None = None

    @property
    def connected(self) -> MCPClient | None:
        """The connected client, or None while it has not connected (or was dropped)."""
        return self._client

    def connect(self) -> MCPClient:
        """Return a connected client, connecting (or joining a connection in progress) if needed.

        A connected client is checked with one tools/list call first. When the stdio
        server has died the call fails at once with ClosedResourceError (measured
        2026-11-03), while MCPClient still reports its session as active; the client is
        then closed and a new one connects.
        """
        client = self._client
        if client is not None:
            try:
                client.list_tools_sync()
                return client
            except Exception as e:  # noqa: BLE001 - any failure means the session is gone
                logger.warning("MCP server %r: resident client is gone (%r); reconnecting", self.name, e)
                self._drop(client)
        return self._join_or_start()

    def close(self) -> None:
        """Close the connected client (best effort)."""
        client = self._client
        if client is not None:
            self._drop(client)

    def _drop(self, client: MCPClient) -> None:
        with self._lock:
            if self._client is client:
                self._client = None
        try:
            client.stop(None, None, None)
        except Exception as e:  # noqa: BLE001 - best-effort cleanup
            logger.warning("MCP server %r: closing the client failed: %s", self.name, e)

    def _join_or_start(self) -> MCPClient:
        with self._lock:
            if self._client is not None:  # another turn reconnected meanwhile
                return self._client
            pending = self._pending
            owner = pending is None
            if owner:
                pending = self._pending = Future()
        if not owner:
            return pending.result()
        client = None
        try:
            client = self._make()
            client.add_consumer(_PROCESS_CONSUMER)
            # load_tools() caches the tool list in the client, so Strands' own call
            # in each turn's Agent is a cache hit.
            asyncio.run(client.load_tools())
        except BaseException as e:
            with self._lock:
                self._pending = None
            if client is not None:
                try:
                    client.stop(None, None, None)
                except Exception:  # noqa: BLE001 - best-effort cleanup after a failed connect
                    pass
            pending.set_exception(e)
            raise
        with self._lock:
            self._client, self._pending = client, None
        pending.set_result(client)
        return client


_RESIDENT_CLIENTS: dict[str, ResidentClient] = {}
_RESIDENT_LOCK = threading.Lock()


def resident_client(name: str, make: Callable[[], MCPClient]) -> ResidentClient:
    """The process's resident client for *name*, created on first use with *make*."""
    with _RESIDENT_LOCK:
        resident = _RESIDENT_CLIENTS.get(name)
        if resident is None:
            resident = _RESIDENT_CLIENTS[name] = ResidentClient(name, make)
        return resident


def close_resident_clients() -> None:
    """Close every resident MCP client and forget them; the one shutdown hook for them.

    stop_guard calls it on SIGTERM. The next create_agent connects new ones.
    """
    with _RESIDENT_LOCK:
        residents = list(_RESIDENT_CLIENTS.values())
        _RESIDENT_CLIENTS.clear()
    for resident in residents:
        resident.close()


def collect_mcp_instructions(mcp_servers: list[MCPClient]) -> str:
    """Concatenate server_instructions from all MCP servers.

    Args:
        mcp_servers: List of initialized MCPClient instances.

    Returns:
        Concatenated instructions string (may be empty).
    """
    sections = [client.server_instructions for client in mcp_servers if client.server_instructions]
    return "\n\n".join(sections)
