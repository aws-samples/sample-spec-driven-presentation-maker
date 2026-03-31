#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Verify concurrent invocation behavior on AgentCore Runtime.

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Tests whether two requests with the same runtimeSessionId can run
concurrently on the same container, and whether asyncio.Event-style
cancellation is feasible.

Usage:
    # Set Cognito credentials
    export COGNITO_USERNAME="your-username"
    export COGNITO_PASSWORD="<YOUR_PASSWORD>"

    # Or provide a JWT token directly
    export JWT_TOKEN="eyJ..."

    python scripts/verify_concurrent_session.py
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
USER_POOL_ID = os.environ.get("USER_POOL_ID", "<USER_POOL_ID>")
CLIENT_ID = os.environ.get("CLIENT_ID", "<CLIENT_ID>")
RUNTIME_ARN = os.environ.get("RUNTIME_ARN", "<RUNTIME_ARN>")
ENCODED_ARN = urllib.parse.quote(RUNTIME_ARN, safe="")
ENDPOINT = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{ENCODED_ARN}/invocations?qualifier=DEFAULT"

# Use a fixed session ID so both requests hit the same session (must be >= 33 chars)
SESSION_ID = "test-concurrent-session-000000000000"


def get_jwt_token() -> str:
    """Get JWT access token from env var or Cognito USER_PASSWORD_AUTH.

    Returns:
        JWT access token string.
    """
    token = os.environ.get("JWT_TOKEN", "")
    if token:
        return token

    username = os.environ.get("COGNITO_USERNAME", "")
    password = os.environ.get("COGNITO_PASSWORD", "")
    if not username or not password:
        print("ERROR: Set JWT_TOKEN or both COGNITO_USERNAME and COGNITO_PASSWORD")
        sys.exit(1)

    client = boto3.client("cognito-idp", region_name=REGION)
    resp = client.initiate_auth(
        ClientId=CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    return resp["AuthenticationResult"]["AccessToken"]


async def send_request(
    token: str,
    prompt: str,
    label: str,
    duration_limit: float = 30.0,
) -> dict:
    """Send a streaming request to AgentCore Runtime and collect events.

    Args:
        token: JWT access token.
        prompt: User prompt to send.
        label: Label for logging (e.g. "req-1", "req-2").
        duration_limit: Max seconds to read before giving up.

    Returns:
        Dict with timing and event info.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": SESSION_ID,
    }
    payload = {
        "prompt": prompt,
        "runtimeSessionId": SESSION_ID,
    }

    result = {
        "label": label,
        "prompt": prompt,
        "start_time": None,
        "first_event_time": None,
        "end_time": None,
        "event_count": 0,
        "error": None,
        "events_sample": [],
    }

    t0 = time.monotonic()
    result["start_time"] = t0

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ENDPOINT,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=duration_limit + 10),
            ) as resp:
                print(f"[{label}] HTTP {resp.status} at t={time.monotonic() - t0:.2f}s")

                if resp.status != 200:
                    body = await resp.text()
                    result["error"] = f"HTTP {resp.status}: {body[:200]}"
                    return result

                async for line in resp.content:
                    elapsed = time.monotonic() - t0
                    decoded = line.decode("utf-8", errors="replace").strip()

                    if not decoded:
                        continue

                    if result["first_event_time"] is None:
                        result["first_event_time"] = elapsed

                    result["event_count"] += 1

                    # Keep first 5 events as sample
                    if len(result["events_sample"]) < 5:
                        result["events_sample"].append(
                            {"t": round(elapsed, 2), "data": decoded[:120]}
                        )

                    # Print keepalive and key events
                    if "keepalive" in decoded or result["event_count"] <= 3:
                        print(f"[{label}] t={elapsed:.2f}s event#{result['event_count']}: {decoded[:80]}")

                    if elapsed > duration_limit:
                        print(f"[{label}] Duration limit reached at t={elapsed:.2f}s")
                        break

    except asyncio.CancelledError:
        print(f"[{label}] Cancelled at t={time.monotonic() - t0:.2f}s")
        result["error"] = "cancelled"
    except Exception as e:
        result["error"] = str(e)
        print(f"[{label}] Error at t={time.monotonic() - t0:.2f}s: {e}")
    finally:
        result["end_time"] = time.monotonic() - t0

    return result


async def test_concurrent(token: str) -> None:
    """Test 1: Send two requests concurrently with the same sessionId.

    Args:
        token: JWT access token.
    """
    print("=" * 60)
    print("TEST 1: Concurrent invocation with same sessionId")
    print("=" * 60)

    # Start req-1 with a slow prompt
    task1 = asyncio.create_task(
        send_request(
            token=token,
            prompt="Count slowly from 1 to 20, one number per line. Take your time.",
            label="req-1",
            duration_limit=30.0,
        )
    )

    # Wait 3 seconds, then send req-2
    await asyncio.sleep(3)
    print("\n--- Sending req-2 while req-1 is still streaming ---\n")

    task2 = asyncio.create_task(
        send_request(
            token=token,
            prompt="Say hello.",
            label="req-2",
            duration_limit=20.0,
        )
    )

    r1, r2 = await asyncio.gather(task1, task2)

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for r in [r1, r2]:
        print(f"\n[{r['label']}]")
        print(f"  First event at: {r['first_event_time']:.2f}s" if r["first_event_time"] else "  No events received")
        print(f"  Total events: {r['event_count']}")
        print(f"  Duration: {r['end_time']:.2f}s")
        if r["error"]:
            print(f"  Error: {r['error']}")

    # Analysis
    print("\n" + "=" * 60)
    print("ANALYSIS")
    print("=" * 60)

    if r2["first_event_time"] is not None and r2["first_event_time"] < 5:
        print("✅ req-2 got events quickly → concurrent invocation WORKS")
        print("   asyncio.Event cancellation approach is FEASIBLE")
    elif r2["first_event_time"] is not None and r2["first_event_time"] > 15:
        print("❌ req-2 was delayed → Runtime likely serializes same-session requests")
        print("   asyncio.Event approach may NOT work")
    elif r2["error"]:
        print(f"⚠️  req-2 errored: {r2['error']}")
        print("   Need to investigate further")
    else:
        print("⚠️  Inconclusive — check event timings above")


async def test_abort_detection(token: str) -> None:
    """Test 2: Abort req-1 and see if server detects it via keepalive.

    Args:
        token: JWT access token.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Abort detection via keepalive")
    print("=" * 60)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": SESSION_ID + "-abort",
    }
    payload = {
        "prompt": "Count slowly from 1 to 50, one number per line.",
        "runtimeSessionId": SESSION_ID + "-abort",
    }

    t0 = time.monotonic()
    event_count = 0

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ENDPOINT,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                print(f"HTTP {resp.status} at t={time.monotonic() - t0:.2f}s")

                async for line in resp.content:
                    elapsed = time.monotonic() - t0
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if not decoded:
                        continue

                    event_count += 1
                    if event_count <= 3 or "keepalive" in decoded:
                        print(f"  t={elapsed:.2f}s event#{event_count}: {decoded[:80]}")

                    # Abort after 8 seconds
                    if elapsed > 8:
                        print(f"\n  >>> ABORTING at t={elapsed:.2f}s (event#{event_count}) <<<\n")
                        break

        # Connection closed. Now wait and see if server logs anything.
        print(f"  Connection closed at t={time.monotonic() - t0:.2f}s")
        print("  (Check server logs for error/cleanup after this point)")

    except Exception as e:
        print(f"  Error: {e}")


async def main() -> None:
    """Run all verification tests."""
    token = get_jwt_token()
    print(f"Token obtained (length={len(token)})\n")

    await test_concurrent(token)
    await test_abort_detection(token)


if __name__ == "__main__":
    asyncio.run(main())
