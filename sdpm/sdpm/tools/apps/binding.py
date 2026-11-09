# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""FastMCP wiring for sdpm's MCP Apps views (mcp 1.30). The rules come from the package.

What ``register`` installs on a server whose tools are already registered:

- ``_meta.ui.resourceUri`` (and the older flat ``ui/resourceUri``) on ``list_styles``, so a host
  that shows MCP Apps renders its result as the style gallery
- with a ``deck`` access (``deck.DeckAccess``): the deck viewer on ``check_specs`` (it opens on
  the Outline tab; the result itself is unchanged) and ``show_deck`` (it opens on Slides)
- the views as ``ui://`` resources (``text/html;profile=mcp-app``; no ``csp`` key, so the spec's
  default CSP applies and the views fetch nothing)
- ``app_action``, the one tool the views call (``visibility: ["app"]``). Its ``open`` action
  (the deck's built file or folder, opened on the user's machine) is in its schema only when
  the deck access opens files (``DeckAccess.opens``, the Local server)
- a ``tools/list`` that leaves out ``app_action`` and ``show_deck`` unless the caller declared
  MCP Apps. ``tools/call`` is not gated: a host may call for its view without declaring
- ``extensions["io.modelcontextprotocol/ui"]`` in the initialize capabilities
"""

import asyncio
from typing import Annotated, Any, Literal

from mcp import types
from pydantic import Field

from sdpm.tools import apps
from sdpm.tools.apps import deck as _deck
from sdpm.tools.apps import gallery

_ACTIONS = ("style_previews", "deck", "slide_preview", "submit_review", "outline_edit")
# Offered only with a deck access that opens files (``DeckAccess.opens``: the Local server).
_OPEN = "open"
_DESCRIPTION = """Data for sdpm's MCP Apps views; only the views call it.
style_previews: the named styles cut into slides, icons drawn in.
deck: the deck's brief, outline, check result and slide list (no images).
slide_preview: one slide's preview: compose SVG parts, or a JPEG when the slide has none.
submit_review: save slide comments as reviews/<id>.json; returns the message for the chat.
outline_edit: an outline edit as a diff message for the chat; writes nothing."""
_OPEN_DESCRIPTION = "\nopen: open the deck's built file or its folder (target) with the OS default app."


def _caller_declared(mcp: Any) -> bool:
    try:
        rc = mcp.get_context().request_context
    except (ValueError, LookupError, AttributeError):  # outside a request
        return False
    return apps.declared(getattr(rc.session, "client_params", None), rc.meta)


def _install_list_filter(mcp: Any) -> None:
    unfiltered = mcp.list_tools

    async def list_tools() -> list[types.Tool]:
        listed = await unfiltered()
        declared = _caller_declared(mcp)
        return [t for t in listed if apps.listed(t.name, t.meta, declared)]

    list_tools.__doc__ = unfiltered.__doc__
    # FastMCP bound its own method as the handler at init; replace both.
    mcp.list_tools = list_tools
    mcp._mcp_server.list_tools()(list_tools)


def _install_capability(mcp: Any) -> None:
    low = mcp._mcp_server
    capabilities = low.get_capabilities

    def get_capabilities(*args: Any, **kwargs: Any) -> types.ServerCapabilities:
        caps = capabilities(*args, **kwargs)
        extensions = dict(getattr(caps, "extensions", None) or {})
        extensions[apps.UI_EXTENSION] = {"mimeTypes": [apps.APP_MIME]}
        caps.extensions = extensions  # ServerCapabilities allows extra fields
        return caps

    low.get_capabilities = get_capabilities


def _text(text: str, payload: dict) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], structuredContent=payload)


def _view(mcp: Any, name: str, doc: str) -> str:
    """Register ``views/<name>.html`` as its ``ui://`` resource; return the URI."""
    uri = apps.view_uri(name)

    def view() -> str:
        return apps.view_html(name)

    view.__doc__ = doc
    mcp.resource(uri, name=name, mime_type=apps.APP_MIME, meta={"ui": {"prefersBorder": True}})(view)
    return uri


def _ui_meta(uri: str) -> dict[str, Any]:
    return {"ui": {"resourceUri": uri}, "ui/resourceUri": uri}


def _register_deck_viewer(mcp: Any, access: _deck.DeckAccess) -> None:
    checking = mcp._tool_manager.get_tool("check_specs")
    if checking is None:
        raise RuntimeError("register MCP Apps after check_specs")
    uri = _view(mcp, apps.DECK_VIEWER, "The deck viewer (a template: the deck comes from app_action).")
    checking.meta = {**(checking.meta or {}), **_ui_meta(uri)}

    async def show_deck(
        deck_id: Annotated[str, Field(description="Deck ID (the deck_id init_deck_workspace returned).")],
    ) -> types.CallToolResult:
        """Show the deck to the user in the chat: Brief, Outline and Slides tabs, with each slide's
        preview. The user's slide comments (saved to reviews/<id>.json), outline edits (a diff for
        you to apply) and confirmations arrive as their next message.
        """
        deck_id = _deck._deck_id(deck_id)
        await asyncio.to_thread(access.open, deck_id, False)
        return _text(
            f"The deck viewer shows {deck_id} to the user; their comments and edits arrive as their next message.",
            {"deck_id": deck_id, "tab": "slides"},
        )

    mcp.tool(name=apps.DECK_TOOL, meta=_ui_meta(uri))(show_deck)


def register(mcp: Any, *, read_styles: Any = None, load_icons: Any = None, deck: Any = None) -> None:
    """Install the MCP Apps wiring. ``read_styles(names) -> {name: html}`` and
    ``load_icons(ids) -> {id: svg bytes}`` default to the local files and catalog; ``deck``
    (a ``DeckAccess``) adds the deck viewer, which a server without it does not offer."""
    if read_styles is None:
        from sdpm.api import read_style_htmls as read_styles

    listing = mcp._tool_manager.get_tool("list_styles")
    if listing is None:
        raise RuntimeError("register MCP Apps after list_styles")
    uri = _view(mcp, apps.GALLERY, "The style gallery view (a template: the styles come from the list_styles result).")
    listing.meta = {**(listing.meta or {}), **_ui_meta(uri)}
    access = deck
    if access is not None:
        _register_deck_viewer(mcp, access)
    opens = access is not None and access.opens
    actions = Literal[(*_ACTIONS, _OPEN) if opens else _ACTIONS]  # type: ignore[valid-type]

    async def app_action(
        action: Annotated[actions, Field(description="Operation; see the tool description.")],
        names: Annotated[
            list[str],
            Field(description=f"Style names for style_previews, 1 to {gallery.MAX_NAMES}.", max_length=gallery.MAX_NAMES),
        ] = [],  # noqa: B006 (FastMCP copies defaults); not Optional: hosts that validate view calls reject anyOf
        deck_id: Annotated[str, Field(description="Deck for the deck actions: the deck_id the deck tools take.")] = "",
        slug: Annotated[str, Field(description="Slide for slide_preview.")] = "",
        review: Annotated[
            dict[str, Any], Field(description="Change request for submit_review: {note, comments}."),
        ] = {},  # noqa: B006 (FastMCP copies defaults)
        base: Annotated[
            str, Field(description="Outline as loaded, for outline_edit.", max_length=_deck.MAX_TEXT),
        ] = "",
        text: Annotated[
            str, Field(description="Outline as edited, for outline_edit.", max_length=_deck.MAX_TEXT),
        ] = "",
        target: Annotated[
            Literal[_deck.OPEN_TARGETS], Field(description="For open: the deck's built file, or its folder."),  # type: ignore[valid-type]
        ] = "file",
    ) -> types.CallToolResult:
        if action == "style_previews":
            payload = await asyncio.to_thread(gallery.style_previews, names, read_styles, load_icons)
            return _text(f"{len(payload['previews'])} style previews", payload)
        if access is None:
            raise ValueError("the deck viewer is not available here")
        if action == "deck":
            payload = await asyncio.to_thread(_deck.deck_view, deck_id, access)
            return _text(f"deck {payload['deck_id']}: {len(payload['slides'])} slides", payload)
        if action == "slide_preview":
            payload = await asyncio.to_thread(_deck.slide_preview, deck_id, slug, access)
            return _text(f"preview of {payload['slug']}", payload)
        if action == "submit_review":
            payload = await asyncio.to_thread(_deck.submit_review, deck_id, review, access)
            return _text(f"review {payload['id']} saved", payload)
        if action == _OPEN:
            payload = await asyncio.to_thread(_deck.open_target, deck_id, target, access)
            return _text(f"opened {payload['name']}", payload)
        # outline_edit (the Literal refuses anything else)
        payload = await asyncio.to_thread(_deck.outline_edit, deck_id, base, text, access)
        return _text("outline edit", payload)

    description = _DESCRIPTION + (_OPEN_DESCRIPTION if opens else "")
    mcp.tool(name=apps.APP_TOOL, description=description, meta={"ui": {"visibility": ["app"]}})(app_action)
    _install_list_filter(mcp)
    _install_capability(mcp)
