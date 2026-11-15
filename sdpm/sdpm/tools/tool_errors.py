# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""A failing tool's message reaches the agent, on every server.

The contract tools report a refusal by raising (``ValueError("Invalid style name: ...")``,
``PermissionError``, ``FileNotFoundError("run init_deck_workspace first")``) and the agent
acts on that text. mcp 2.x passes the text on only for ``ToolError``; any other exception
becomes ``Error executing tool <name>`` with the reason kept on the server. ``install``
restores mcp 1.x's result for those: ``Error executing tool <name>: <exception text>``,
still an ``is_error`` result, never a JSON-RPC error. Messages that may carry a user's
identity are scrubbed where they are raised (``servers/remote``), as before. This also
passes on the text of a crash (a botocore error, say), as mcp 1.x did.

A refusal is logged by the SDK as one INFO line. Any other exception is a crash and is
logged here at ERROR with its traceback, so a search for ERROR finds crashes only.
"""

import logging
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from sdpm.tools.attachment.errors import AttachmentError
from sdpm.tools.attachment.paging import PagingError

logger = logging.getLogger(__name__)

# What the tools raise on purpose to refuse a call; the agent reads the text and corrects.
REFUSALS: tuple[type[BaseException], ...] = (
    ValueError, PermissionError, FileNotFoundError, AttachmentError, PagingError,
)


def install(mcp: Any) -> None:
    """Make ``mcp`` (an ``MCPServer``) return a crashed tool's exception text as its result."""
    call_tool = mcp.call_tool

    async def surfaced(name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        try:
            return await call_tool(name, arguments, context)
        except UnexpectedToolError as exc:
            cause = exc.__cause__
            if cause is None or isinstance(cause, UnexpectedToolError):
                raise
            if not isinstance(cause, REFUSALS):
                logger.error("Tool %r raised an unexpected exception", name, exc_info=cause)
            raise ToolError(f"{exc}: {cause}") from cause

    # MCPServer's tools/call handler calls self.call_tool, so the instance attribute wins.
    mcp.call_tool = surfaced
