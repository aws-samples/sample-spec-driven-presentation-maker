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
- ``LONG_CALL`` — for ``invoke_code_interpreter`` running user code
  (run_python / run_style_python). The call stays silent until the code ends,
  so its read timeout is the execution limit: ``USER_CODE_TIMEOUT_S``, below
  the sandbox's own 300 s session limit. It is never retried (a retry would
  execute the code twice).
"""

from botocore.config import Config

# Execution limit for user code. Legitimate run_python calls on dev took at
# most 17 s (p99 6 s); the same limit as Local's sandbox.
USER_CODE_TIMEOUT_S = 120

SHORT_API = Config(
    connect_timeout=5,
    read_timeout=30,
    retries={"mode": "standard", "max_attempts": 3},
    tcp_keepalive=True,
)

LONG_CALL = Config(
    connect_timeout=5,
    read_timeout=USER_CODE_TIMEOUT_S,
    # total_max_attempts counts the first request; max_attempts counts only
    # retries, so max_attempts=1 would re-send the code once (240 s, two runs).
    retries={"mode": "standard", "total_max_attempts": 1},
    tcp_keepalive=True,
)
