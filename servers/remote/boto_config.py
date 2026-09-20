# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""botocore configs for the remote server.

On AgentCore Runtime platform V2 a restored microVM has been seen to stall
while opening new outbound connections (S3 list unanswered for 9 min;
start_code_interpreter_session stuck for 53 s and later indefinitely — both
with botocore's default 60 s timeouts and legacy retries). A short connect
timeout turns such a stall into a quick retry on a fresh connection.

Two configs, because ``read_timeout`` is the idle time between bytes and a
retry re-sends the request:

- ``SHORT_API`` — for calls that answer promptly (S3, DynamoDB, SSM, Code
  Interpreter session start/stop, file writes, embeddings).
- ``LONG_CALL`` — for ``invoke_code_interpreter`` running user code, which may
  stay silent for minutes; it must never be retried (a retry would execute the
  code twice) and needs a read timeout above the sandbox's own 300 s limit.
"""

from botocore.config import Config

SHORT_API = Config(
    connect_timeout=5,
    read_timeout=30,
    retries={"mode": "standard", "max_attempts": 3},
    tcp_keepalive=True,
)

LONG_CALL = Config(
    connect_timeout=5,
    read_timeout=600,
    retries={"mode": "standard", "max_attempts": 1},
    tcp_keepalive=True,
)
