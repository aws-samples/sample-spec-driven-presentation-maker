# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""sdpm.tools.apps.ui_capable — the one check for "the client declared MCP Apps"."""

from types import SimpleNamespace

import pytest
from mcp.types import ClientCapabilities, Implementation, InitializeRequestParams

from sdpm.tools.apps import UI_EXTENSION, ui_capable


def _params(**capabilities) -> InitializeRequestParams:
    return InitializeRequestParams(
        protocolVersion="2025-06-18",
        capabilities=ClientCapabilities(**capabilities),
        clientInfo=Implementation(name="test", version="1"),
    )


@pytest.mark.parametrize(("capabilities", "expected"), [
    ({"extensions": {UI_EXTENSION: {"mimeTypes": ["text/html;profile=mcp-app"]}}}, True),
    ({"extensions": {UI_EXTENSION: {}}}, True),
    ({}, False),
    ({"extensions": {"io.example/other": {}}}, False),
    ({"extensions": {UI_EXTENSION: True}}, False),
    ({"extensions": {UI_EXTENSION: None}}, False),
    ({"extensions": [UI_EXTENSION]}, False),
])
def test_ui_capable_reads_the_initialize_extensions(capabilities, expected):
    assert ui_capable(_params(**capabilities)) is expected


def test_ui_capable_without_params_or_with_a_native_field():
    assert ui_capable(None) is False
    assert ui_capable(SimpleNamespace(capabilities=None)) is False
    native = SimpleNamespace(capabilities=SimpleNamespace(extensions={UI_EXTENSION: {}}))
    assert ui_capable(native) is True
    assert ui_capable(object()) is False
