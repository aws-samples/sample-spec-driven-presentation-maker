# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""PNG worker — SQS polling loop for PPTX→PNG conversion jobs."""

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

import json
import logging
import os
import signal

import boto3
from handlers.png import handle_png

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("png-worker")

QUEUE_URL: str = os.environ["QUEUE_URL"]
AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")

_shutdown = False


def _signal_handler(signum: int, frame: object) -> None:
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    global _shutdown
    logger.info("Received signal %d, shutting down...", signum)
    _shutdown = True


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


def _to_png_job(body: dict) -> dict:
    """Convert SQS message body to PNG job payload.

    Handles both direct messages and EventBridge S3 event envelopes.

    Args:
        body: Parsed SQS message body.

    Returns:
        Dict with bucket, key, deckId.
    """
    if "detail" in body:
        detail = body["detail"]
        bucket = detail["bucket"]["name"]
        key = detail["object"]["key"]
        parts = key.split("/")
        deck_id = parts[1] if len(parts) >= 3 else "unknown"
        return {"bucket": bucket, "key": key, "deckId": deck_id}
    return body.get("payload", body)


def main() -> None:
    """Main SQS polling loop."""
    sqs = boto3.client("sqs", region_name=AWS_REGION)
    logger.info("PNG worker started. Polling %s", QUEUE_URL)

    while not _shutdown:
        resp = sqs.receive_message(
            QueueUrl=QUEUE_URL, MaxNumberOfMessages=1,
            WaitTimeSeconds=20, VisibilityTimeout=180,
        )
        for msg in resp.get("Messages", []):
            try:
                body = json.loads(msg["Body"])
                payload = _to_png_job(body)
                logger.info("Processing: deckId=%s", payload.get("deckId"))
                handle_png(payload)
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
            except Exception:
                logger.exception("PNG job failed.")

    logger.info("PNG worker shutdown complete.")


if __name__ == "__main__":
    main()
