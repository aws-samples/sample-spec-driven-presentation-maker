# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Local agent server for test_agent_stop_guard: the real basic_agent, factory, streaming
and composer, with fakes only at the edges (agent_stop_fakes). Listens on 127.0.0.1.

usage: agent_stop_server.py <port> <record file>
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT / "tests")]
os.environ["MEMORY_ID"] = "memory-test"
os.environ.setdefault("AWS_REGION", "us-east-1")

from agent_stop_fakes import FakeMCP, Recorder, ScriptedModel, patch_memory_backend  # noqa: E402

recorder = Recorder(Path(sys.argv[2]))
patch_memory_backend(recorder)

import basic_agent  # noqa: E402
import factory  # noqa: E402

factory.BedrockModel = lambda **_kwargs: ScriptedModel(recorder)
factory._MCP_FACTORIES = [lambda jwt_token, session_id="", tool_filters=None: FakeMCP(recorder, "parent")]
factory.mcp_agentcore_runtime = lambda **_kwargs: FakeMCP(recorder, "composer")

basic_agent.main(port=int(sys.argv[1]))
