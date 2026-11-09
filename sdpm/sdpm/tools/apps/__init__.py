# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP Apps (``io.modelcontextprotocol/ui``): sdpm's views, defined once for both servers.

The pure rules live here: what a client declared (``ui_capable``, ``declared``), which tools
a client sees (``model_listed``, ``listed``), and the view documents and their ``ui://``
URIs. No ``mcp`` import, no I/O beyond reading the bundled view files, and the rules never
raise. The views' operations are pure modules next to this one: ``gallery`` (style previews)
and ``deck`` (the deck viewer, with storage passed in as a ``DeckAccess``).

``register(mcp, ...)`` installs the wiring on a FastMCP server (``binding.py``): the style
gallery on ``list_styles``; with a ``deck`` access, the deck viewer on ``check_specs`` (Outline
tab) and on ``show_deck`` (Slides tab, listed only to MCP Apps clients); the views as
resources, the app-only ``app_action`` tool, the ``tools/list`` filter and the extension in the
initialize capabilities. Both servers call it once, after their tools are registered. The
Local server also uses ``ui_capable`` to leave out the ``sdpm open`` hint (such a client shows
decks itself).
"""

import functools
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

UI_EXTENSION = "io.modelcontextprotocol/ui"
APP_MIME = "text/html;profile=mcp-app"
# The per-request form of a client's declaration (MCP 2026-07-28 extensions).
CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"
# The one tool only sdpm's views call (visibility ["app"]); its ``action`` selects the operation.
APP_TOOL = "app_action"
GALLERY = "style-gallery"
DECK_VIEWER = "deck-viewer"
# The model tool that only opens the deck viewer: a client that cannot show it is not offered it.
DECK_TOOL = "show_deck"
UI_ONLY_TOOLS = frozenset({APP_TOOL, DECK_TOOL})

_VIEWS = Path(__file__).resolve().parent / "views"
_BRIDGE_PLACEHOLDER = "/*__SDPM_BRIDGE__*/"


def _declares_ui(extensions: Any) -> bool:
    return isinstance(extensions, Mapping) and isinstance(extensions.get(UI_EXTENSION), Mapping)


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
        return _declares_ui(extensions)
    except Exception:  # an unexpected object shape means "not declared"
        return False


def declared(client_params: Any, request_meta: Any = None) -> bool:
    """Whether the caller declared MCP Apps, in initialize or in this request's ``_meta``.

    ``request_meta`` is the request's ``_meta`` (a pydantic ``RequestParams.Meta`` or a
    mapping); the declaration sits at ``_meta["io.modelcontextprotocol/clientCapabilities"]
    ["extensions"]["io.modelcontextprotocol/ui"]``. A stateless server (the remote one) keeps
    no initialize params, so the per-request form is the only one it can see.
    """
    if ui_capable(client_params):
        return True
    try:
        if isinstance(request_meta, Mapping):
            capabilities = request_meta.get(CLIENT_CAPABILITIES_META)
        else:
            extra = getattr(request_meta, "model_extra", None)
            capabilities = extra.get(CLIENT_CAPABILITIES_META) if isinstance(extra, Mapping) else None
        return isinstance(capabilities, Mapping) and _declares_ui(capabilities.get("extensions"))
    except Exception:  # an unexpected object shape means "not declared"
        return False


def model_listed(tool_meta: Any) -> bool:
    """Whether a tool is for the model: True unless ``_meta.ui.visibility`` leaves out ``"model"``."""
    ui = tool_meta.get("ui") if isinstance(tool_meta, Mapping) else None
    visibility = ui.get("visibility") if isinstance(ui, Mapping) else None
    return not isinstance(visibility, list) or "model" in visibility


def listed(name: Any, tool_meta: Any, declared: bool) -> bool:
    """Whether ``tools/list`` shows a tool: every tool to a client that declared MCP Apps,
    otherwise the model's tools except the ones that only serve a view (``UI_ONLY_TOOLS``)."""
    if declared:
        return True
    return model_listed(tool_meta) and not (isinstance(name, str) and name in UI_ONLY_TOOLS)


@functools.lru_cache(maxsize=None)
def view_html(name: str) -> str:
    """The view document ``views/<name>.html`` with the shared bridge script inlined.

    A view is one document (it cannot load files), so ``views/bridge.js`` goes in at the
    bridge placeholder comment.
    """
    html = (_VIEWS / f"{name}.html").read_text(encoding="utf-8")
    bridge = (_VIEWS / "bridge.js").read_text(encoding="utf-8")
    return html.replace(_BRIDGE_PLACEHOLDER, bridge)


def view_uri(name: str) -> str:
    """``ui://sdpm/<name>-<hash>.html``: hosts cache a view by URI, so every change is a new one."""
    digest = hashlib.sha256(view_html(name).encode("utf-8")).hexdigest()[:12]
    return f"ui://sdpm/{name}-{digest}.html"


def register(mcp: Any, *, read_styles: Any = None, load_icons: Any = None, deck: Any = None) -> None:
    """Install sdpm's MCP Apps wiring on a FastMCP server (see ``binding.register``)."""
    from .binding import register as _register

    _register(mcp, read_styles=read_styles, load_icons=load_icons, deck=deck)
