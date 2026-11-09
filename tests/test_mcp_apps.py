# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""MCP Apps rules in ``sdpm.tools.apps`` (no server): declarations, visibility, views, previews.

``ui_capable`` is the one check for "the client declared MCP Apps" in initialize; ``declared``
adds the per-request form.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from mcp import types

from sdpm.tools import apps
from sdpm.tools.apps import gallery

_UI = {apps.UI_EXTENSION: {"mimeTypes": [apps.APP_MIME]}}
ICON = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24"/></svg>'


def _params(extensions=None) -> types.InitializeRequestParams:
    extra = {"extensions": extensions} if extensions is not None else {}
    return types.InitializeRequestParams(
        protocolVersion=types.LATEST_PROTOCOL_VERSION,
        capabilities=types.ClientCapabilities(**extra),
        clientInfo=types.Implementation(name="t", version="1"),
    )


def _meta(extensions) -> types.RequestParams.Meta:
    return types.RequestParams.Meta(**{apps.CLIENT_CAPABILITIES_META: {"extensions": extensions}})


@pytest.mark.parametrize(("extensions", "expected"), [
    ({apps.UI_EXTENSION: {"mimeTypes": [apps.APP_MIME]}}, True),
    ({apps.UI_EXTENSION: {}}, True),
    (None, False),
    ({"io.example/other": {}}, False),
    ({apps.UI_EXTENSION: True}, False),
    ({apps.UI_EXTENSION: None}, False),
    ([apps.UI_EXTENSION], False),
])
def test_ui_capable_reads_the_initialize_extensions(extensions, expected) -> None:
    assert apps.ui_capable(_params(extensions)) is expected


def test_ui_capable_without_params_or_with_a_native_field() -> None:
    assert apps.ui_capable(None) is False
    assert apps.ui_capable(SimpleNamespace(capabilities=None)) is False
    native = SimpleNamespace(capabilities=SimpleNamespace(extensions={apps.UI_EXTENSION: {}}))
    assert apps.ui_capable(native) is True
    assert apps.ui_capable(object()) is False


def test_declared_in_initialize_or_per_request() -> None:
    assert apps.declared(_params(_UI), None)
    assert apps.declared(_params({apps.UI_EXTENSION: {}}), None)
    assert apps.declared(None, _meta(_UI))
    assert apps.declared(_params(), {apps.CLIENT_CAPABILITIES_META: {"extensions": _UI}})
    assert not apps.declared(None, None)
    assert not apps.declared(_params(), None)
    assert not apps.declared(_params({"io.example/other": {}}), _meta({"io.example/other": {}}))
    assert not apps.declared(_params(), types.RequestParams.Meta())
    for odd in (object(), "x", 3, SimpleNamespace(model_extra="x"), {apps.CLIENT_CAPABILITIES_META: "x"},
                {apps.CLIENT_CAPABILITIES_META: {"extensions": {apps.UI_EXTENSION: True}}}):
        assert not apps.declared(odd, odd)


def test_model_listed() -> None:
    assert apps.model_listed(None)
    assert apps.model_listed({})
    assert apps.model_listed({"ui": {"resourceUri": "ui://x"}})
    assert apps.model_listed({"ui": {"visibility": ["model", "app"]}})
    assert not apps.model_listed({"ui": {"visibility": ["app"]}})
    assert not apps.model_listed({"ui": {"visibility": []}})
    assert apps.model_listed({"ui": "x"})


def test_view_uri_follows_the_document(monkeypatch: pytest.MonkeyPatch) -> None:
    uri = apps.view_uri(apps.GALLERY)
    assert re.fullmatch(r"ui://sdpm/style-gallery-[0-9a-f]{12}\.html", uri)
    assert apps.view_uri(apps.GALLERY) == uri
    monkeypatch.setattr(apps, "view_html", lambda name: "<html>changed</html>")
    assert apps.view_uri(apps.GALLERY) != uri


def test_the_gallery_view_carries_the_bridge_and_fetches_nothing() -> None:
    html = apps.view_html(apps.GALLERY)
    assert "/*__SDPM_BRIDGE__*/" not in html
    assert "window.sdpmBridge" in html and "ui/initialize" in html
    assert apps.APP_TOOL in html and '"style_previews"' in html
    assert not re.search(r"https?://", html)
    assert "<link" not in html and "@import" not in html
    assert not re.search(r"\ssrc\s*=", html)
    assert ".innerHTML" not in html
    for hook in ('data-action="use"', '"all"', 'id="back"', 'id="status"', 'id="count"', "dataset.style"):
        assert hook in html


def _reader(htmls: dict[str, str]):
    calls = []

    def read(names):
        calls.append(list(names))
        return {n: htmls[n] for n in names if n in htmls}

    return read, calls


def _style(body: str) -> str:
    return f"<html><head><style>.slide{{}}</style></head><body>\n{body}\n</body></html>"


@pytest.mark.parametrize("names", [[], ["a"] * 7, ["../x"], ["a", "b/c"], "a", None, [3]])
def test_style_previews_refuses_bad_names(names) -> None:
    read, calls = _reader({})
    with pytest.raises(ValueError):
        gallery.style_previews(names, read)
    assert not calls


def test_style_previews_reads_once_and_names_what_is_missing() -> None:
    read, calls = _reader({"a": _style('<div class="slide">1</div><div class="slide">2</div>')})
    got = gallery.style_previews(["a", "nope", "a"], read)
    assert calls == [["a", "nope"]]
    assert got["missing"] == ["nope"]
    assert len(got["previews"]["a"]["slides"]) == 2


def test_style_previews_draw_icons_through_the_given_loader() -> None:
    source = _style('<div class="slide"><svg class="icon"><use href="#t/x"/></svg></div>')
    read, _ = _reader({"a": source, "b": _style('<div class="slide">b</div>')})
    asked = []

    def load(ids):
        asked.append(set(ids))
        return {"t/x": ICON}

    got = gallery.style_previews(["a", "b"], read, load)

    assert asked == [{"t/x"}]
    assert '<symbol id="t/x" viewBox="0 0 24 24">' in got["previews"]["a"]["prelude"]
    assert got["previews"]["b"]["prelude"] == ""
    assert "<symbol" not in source  # the style itself stays reference-only
