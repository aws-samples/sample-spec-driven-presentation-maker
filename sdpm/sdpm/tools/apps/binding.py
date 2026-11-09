# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""FastMCP wiring for sdpm's MCP Apps views (mcp 1.30). The rules come from the package.

What ``register`` installs on a server whose tools are already registered:

- ``_meta.ui.resourceUri`` (and the older flat ``ui/resourceUri``) on ``list_styles``, so a host
  that shows MCP Apps renders its result as the style gallery
- the gallery view as a ``ui://`` resource (``text/html;profile=mcp-app``; no ``csp`` key, so the
  spec's default CSP applies and the view fetches nothing)
- ``app_action``, the one tool the views call (``visibility: ["app"]``)
- a ``tools/list`` that leaves out app-only tools unless the caller declared MCP Apps.
  ``tools/call`` is not gated: a host may call for its view without declaring
- ``extensions["io.modelcontextprotocol/ui"]`` in the initialize capabilities
"""

import asyncio
from typing import Annotated, Any, Literal

from mcp import types
from pydantic import Field

from sdpm.tools import apps
from sdpm.tools.apps import gallery

_ACTIONS = Literal["style_previews"]


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
        if _caller_declared(mcp):
            return listed
        return [t for t in listed if apps.model_listed(t.meta)]

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


def register(mcp: Any, *, read_styles: Any = None, load_icons: Any = None) -> None:
    """Install the MCP Apps wiring. ``read_styles(names) -> {name: html}`` and
    ``load_icons(ids) -> {id: svg bytes}`` default to the local files and catalog."""
    if read_styles is None:
        from sdpm.api import read_style_htmls as read_styles

    listing = mcp._tool_manager.get_tool("list_styles")
    if listing is None:
        raise RuntimeError("register MCP Apps after list_styles")
    uri = apps.view_uri(apps.GALLERY)
    listing.meta = {**(listing.meta or {}), "ui": {"resourceUri": uri}, "ui/resourceUri": uri}

    def style_gallery() -> str:
        """The style gallery view (a template: the styles come from the list_styles result)."""
        return apps.view_html(apps.GALLERY)

    mcp.resource(uri, name=apps.GALLERY, mime_type=apps.APP_MIME, meta={"ui": {"prefersBorder": True}})(style_gallery)

    async def app_action(
        action: Annotated[_ACTIONS, Field(description="Operation: style_previews (display copies of styles).")],
        names: Annotated[
            list[str],
            Field(description=f"Style names for style_previews, 1 to {gallery.MAX_NAMES}.", max_length=gallery.MAX_NAMES),
        ] = [],  # noqa: B006 (FastMCP copies defaults); not Optional: hosts that validate view calls reject anyOf
    ) -> types.CallToolResult:
        """Data for sdpm's MCP Apps views; only the views call it.
        style_previews: the named styles cut into slides, icons drawn in.
        """
        # action is "style_previews" (the Literal refuses anything else)
        payload = await asyncio.to_thread(gallery.style_previews, names, read_styles, load_icons)
        text = f"{len(payload['previews'])} style previews"
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)], structuredContent=payload)

    mcp.tool(name=apps.APP_TOOL, meta={"ui": {"visibility": ["app"]}})(app_action)
    _install_list_filter(mcp)
    _install_capability(mcp)
