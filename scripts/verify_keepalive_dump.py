#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Dump all raw SSE data from AgentCore Runtime to verify keepalive behavior.

Args:
    Reads COGNITO_USERNAME/COGNITO_PASSWORD or JWT_TOKEN from env.
"""

import asyncio
import json
import os
import sys
import time
import urllib.parse

import aiohttp
import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
CLIENT_ID = os.environ.get("CLIENT_ID", "<CLIENT_ID>")
RUNTIME_ARN = os.environ.get("RUNTIME_ARN", "<RUNTIME_ARN>")
ENCODED_ARN = urllib.parse.quote(RUNTIME_ARN, safe="")
ENDPOINT = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{ENCODED_ARN}/invocations?qualifier=DEFAULT"
SESSION_ID = "test-keepalive-dump-00000000000000"


def get_jwt_token() -> str:
    """Get JWT access token from env var or Cognito."""
    token = os.environ.get("JWT_TOKEN", "")
    if token:
        return token
    username = os.environ.get("COGNITO_USERNAME", "")
    password = os.environ.get("COGNITO_PASSWORD", "")
    if not username or not password:
        print("ERROR: Set JWT_TOKEN or COGNITO_USERNAME + COGNITO_PASSWORD")
        sys.exit(1)
    client = boto3.client("cognito-idp", region_name=REGION)
    resp = client.initiate_auth(
        ClientId=CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    return resp["AuthenticationResult"]["AccessToken"]


async def main() -> None:
    """Dump every raw byte/line from SSE stream for 25 seconds."""
    token = get_jwt_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": SESSION_ID,
    }
    payload = {
        "prompt": "Write a 500-word essay about the history of computers. Be very detailed.",
        "runtimeSessionId": SESSION_ID,
    }

    t0 = time.monotonic()
    print(f"Sending request...")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            ENDPOINT,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            print(f"HTTP {resp.status} at t={time.monotonic() - t0:.2f}s")
            print(f"Headers: {dict(resp.headers)}\n")

            count = 0
            async for raw_line in resp.content:
                elapsed = time.monotonic() - t0
                decoded = raw_line.decode("utf-8", errors="replace")
                count += 1

                # Print EVERYTHING including empty lines
                display = decoded.rstrip("\n").rstrip("\r")
                if display:
                    print(f"[{elapsed:7.2f}s] #{count:3d} | {display[:150]}")
                else:
                    print(f"[{elapsed:7.2f}s] #{count:3d} | (empty line)")

                if elapsed > 25:
                    print(f"\n--- 25s limit reached, {count} lines total ---")
                    break

    print(f"\nDone. Total lines: {count}, duration: {time.monotonic() - t0:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
