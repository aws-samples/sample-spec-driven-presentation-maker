# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP Apps (``io.modelcontextprotocol/ui``): what a client declared, decided in one place.

``ui_capable`` is the single rule for "this client shows MCP Apps". The Local server uses it to
leave out the ``sdpm open`` hint (such a client shows decks itself); the MCP Apps work uses it
to decide which app-only tools the model sees. Pure: no ``mcp`` import, no I/O, never raises.
"""

from collections.abc import Mapping
from typing import Any

UI_EXTENSION = "io.modelcontextprotocol/ui"


def ui_capable(client_params: Any) -> bool:
    """Whether the client declared MCP Apps in initialize (``capabilities.extensions``).

    ``client_params`` is the session's InitializeRequestParams (or None before initialize).
    The declaration is an object under ``extensions["io.modelcontextprotocol/ui"]``; an empty
    object counts. mcp 1.30 keeps ``extensions`` as an extra field of ClientCapabilities, a
    later SDK as a field of its own; both are read here.
    """
    try:
        capabilities = getattr(client_params, "capabilities", None)
        if capabilities is None:
            return False
        extensions = getattr(capabilities, "extensions", None)
        if extensions is None:
            extra = getattr(capabilities, "model_extra", None)
            extensions = extra.get("extensions") if isinstance(extra, Mapping) else None
        return isinstance(extensions, Mapping) and isinstance(extensions.get(UI_EXTENSION), Mapping)
    except Exception:  # an unexpected object shape means "not declared"
        return False
