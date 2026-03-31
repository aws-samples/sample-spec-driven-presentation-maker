#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Backfill KB vectors for all existing decks.

Scans DDB for all deck records, reads presentation.json from S3,
and syncs vectors via KBSync.

Usage:
    python scripts/backfill_vectors.py \
        --table DECKS_TABLE \
        --bucket PPTX_BUCKET \
        --kb-id KB_ID \
        --vector-bucket VECTOR_BUCKET_NAME \
        --vector-index VECTOR_INDEX_NAME \
        --region us-east-1
"""

import argparse
import json
import sys
from pathlib import Path

# Add mcp-server to path for KBSync import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp-server"))

import boto3  # noqa: E402

from tools.kb_sync import KBSync  # noqa: E402


def main() -> None:
    """Scan all decks and backfill KB vectors."""
    parser = argparse.ArgumentParser(description="Backfill KB vectors")
    parser.add_argument("--table", required=True, help="DynamoDB table name")
    parser.add_argument("--bucket", required=True, help="PPTX S3 bucket name")
    parser.add_argument("--kb-id", required=True, help="Bedrock KB ID")
    parser.add_argument("--vector-bucket", required=True, help="S3 Vector Bucket name")
    parser.add_argument("--vector-index", required=True, help="S3 Vector Index name")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    args = parser.parse_args()

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    table = dynamodb.Table(args.table)
    s3_client = boto3.client("s3", region_name=args.region)

    kb_sync = KBSync(
        kb_id=args.kb_id,
        vector_bucket_name=args.vector_bucket,
        vector_index_name=args.vector_index,
        region=args.region,
    )

    # Scan for all deck records (PK starts with USER#, SK starts with DECK#)
    decks: list[dict] = []
    scan_kwargs: dict = {
        "FilterExpression": "begins_with(PK, :pk) AND begins_with(SK, :sk) AND attribute_not_exists(deletedAt)",
        "ExpressionAttributeValues": {":pk": "USER#", ":sk": "DECK#"},
    }
    while True:
        resp = table.scan(**scan_kwargs)
        decks.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    print(f"Found {len(decks)} decks to backfill")

    for i, deck in enumerate(decks):
        user_id = deck["PK"].replace("USER#", "")
        deck_id = deck["SK"].replace("DECK#", "")
        deck_name = deck.get("name", "")
        visibility = deck.get("visibility", "private")

        try:
            resp = s3_client.get_object(
                Bucket=args.bucket,
                Key=f"decks/{deck_id}/presentation.json",
            )
            presentation = json.loads(resp["Body"].read())
            slides = presentation.get("slides", [])

            if not slides:
                print(f"  [{i+1}/{len(decks)}] {deck_id} ({deck_name}) — no slides, skipping")
                continue

            kb_sync.sync_deck(
                deck_id=deck_id,
                user_id=user_id,
                deck_name=deck_name,
                visibility=visibility,
                slides=slides,
            )
            print(f"  [{i+1}/{len(decks)}] {deck_id} ({deck_name}) — {len(slides)} slides synced")

        except Exception as e:
            print(f"  [{i+1}/{len(decks)}] {deck_id} ({deck_name}) — ERROR: {e}")

    print("Backfill complete")


if __name__ == "__main__":
    main()
