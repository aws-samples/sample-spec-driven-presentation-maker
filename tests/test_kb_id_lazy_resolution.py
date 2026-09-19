# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""The remote MCP server must not resolve the KB id at import time.

Background: AgentCore Runtime platformVersion V2 snapshots the process once
initialization completes, and every restored instance inherits that memory state.
Anything read at import is therefore frozen for the life of the snapshot. The KB
id lives in SSM precisely so it can change without a redeploy, so reading it at
import pinned the runtime to a stale id until the next runtime update. On V1 the
~40-minute container recycling hid the problem by re-reading on its own.

These tests pin the lazy behaviour so the eager read cannot come back.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def server_mod(monkeypatch):
    """Import servers/remote/server.py fresh, with boto3 stubbed out.

    Loaded from its file path under a unique module name rather than by plain
    ``import server``: ``servers/local/server.py`` has the same module name and
    other tests put ``servers/local`` on sys.path, so a bare import resolves to
    whichever landed in sys.modules first.

    Returns (module, calls, ssm) where calls records every boto3.client(service)
    the module asked for, so a test can assert what did and did not happen during
    import.
    """
    for var, val in {
        "DECKS_TABLE": "decks-test",
        "PPTX_BUCKET": "pptx-test",
        "RESOURCE_BUCKET": "resource-test",
        "KB_SSM_PARAM": "/sdpm/kb-id",
        "VECTOR_BUCKET_NAME": "vectors-test",
        "VECTOR_INDEX_NAME": "index-test",
        "AWS_DEFAULT_REGION": "ap-northeast-1",
    }.items():
        monkeypatch.setenv(var, val)
    monkeypatch.delenv("KB_ID", raising=False)

    boto3 = pytest.importorskip("boto3")
    pytest.importorskip("mcp.server.fastmcp")

    calls: list[str] = []
    ssm = MagicMock()
    ssm.get_parameter.return_value = {"Parameter": {"Value": "kb-from-ssm-1"}}

    def fake_client(service, *a, **kw):
        calls.append(service)
        return ssm if service == "ssm" else MagicMock()

    monkeypatch.setattr(boto3, "client", fake_client)

    remote = _ROOT / "servers" / "remote"
    for p in (str(_ROOT), str(remote), str(_ROOT / "sdpm")):
        if p not in sys.path:
            sys.path.insert(0, p)

    name = "sdpm_remote_server_under_test"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, remote / "server.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:  # pragma: no cover - environment-dependent
        sys.modules.pop(name, None)
        pytest.skip(f"servers/remote/server.py not importable here: {e}")
    yield module, calls, ssm
    sys.modules.pop(name, None)


def test_import_does_not_read_ssm(server_mod):
    """The regression guard: no SSM call may happen during import."""
    _server, calls, ssm = server_mod
    assert "ssm" not in calls, f"boto3 clients created at import: {calls}"
    assert ssm.get_parameter.call_count == 0


def test_kb_id_is_resolved_on_first_use(server_mod):
    server, _calls, ssm = server_mod
    assert server._kb_configured is True

    kb = server._get_kb_sync()

    assert kb is not None
    assert ssm.get_parameter.call_count == 1
    ssm.get_parameter.assert_called_with(Name="/sdpm/kb-id")


def test_resolution_is_cached_within_ttl(server_mod):
    server, _calls, ssm = server_mod

    first = server._get_kb_sync()
    second = server._get_kb_sync()

    assert first is second
    assert ssm.get_parameter.call_count == 1, "TTL 内なので SSM は 1 回だけ"


def test_resolution_refreshes_after_ttl(server_mod, monkeypatch):
    """A changed SSM value must be picked up without redeploying."""
    server, _calls, ssm = server_mod

    server._get_kb_sync()
    ssm.get_parameter.return_value = {"Parameter": {"Value": "kb-from-ssm-2"}}
    # Pretend the cache entry is older than the TTL.
    monkeypatch.setattr(server, "_kb_sync_resolved_at", 0.0)

    server._get_kb_sync()

    assert ssm.get_parameter.call_count == 2


def test_ssm_failure_keeps_serving_the_previous_value(server_mod):
    """A transient SSM error must not disable the KB for the process lifetime."""
    server, _calls, ssm = server_mod

    good = server._get_kb_sync()
    server._kb_sync_resolved_at = 0.0
    ssm.get_parameter.side_effect = RuntimeError("SSM unavailable")

    still = server._get_kb_sync()

    assert still is good


def test_search_slides_is_registered_from_config_not_from_a_successful_read(server_mod):
    """Tool registration must depend on configuration, not on the SSM read.

    Previously the tool was registered inside `if _kb_id and ...`, so a transient
    SSM failure at startup removed search_slides for the life of the process.
    """
    server, _calls, _ssm = server_mod
    assert server._kb_configured is True
    assert hasattr(server, "search_slides")
