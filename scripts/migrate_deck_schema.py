#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Migrate deck records from DECK#{id}/META to USER#{userId}/DECK#{id}.

One-shot script. Safe to re-run (skips already migrated records).

Usage:
    python scripts/migrate_deck_schema.py \
        --table SdpmData-DecksTable1391E269-158SGYT576617 \
        --region us-east-1
"""

import argparse

import boto3


def main() -> None:
    """Scan old DECK# records, write new USER# records, delete old ones."""
    parser = argparse.ArgumentParser(description="Migrate deck DDB schema")
    parser.add_argument("--table", required=True, help="DynamoDB table name")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    table = dynamodb.Table(args.table)

    # Scan for old-format DECK# records
    resp = table.scan(
        FilterExpression="begins_with(PK, :prefix) AND SK = :sk",
        ExpressionAttributeValues={":prefix": "DECK#", ":sk": "META"},
    )
    items = resp.get("Items", [])
    print(f"Found {len(items)} old DECK# records")

    migrated = 0
    for item in items:
        deck_id = item["PK"].replace("DECK#", "")
        user_id = item.get("createdBy")
        if not user_id:
            print(f"  SKIP {deck_id}: no createdBy")
            continue

        new_pk = f"USER#{user_id}"
        new_sk = f"DECK#{deck_id}"

        # Build new item (remove old PK/SK, set new ones)
        new_item = {k: v for k, v in item.items() if k not in ("PK", "SK")}
        new_item["PK"] = new_pk
        new_item["SK"] = new_sk

        if args.dry_run:
            print(f"  MIGRATE {deck_id}: {item['PK']}/META -> {new_pk}/{new_sk}")
        else:
            table.put_item(Item=new_item)
            table.delete_item(Key={"PK": item["PK"], "SK": "META"})
            print(f"  MIGRATED {deck_id}")
        migrated += 1

    print(f"{'Would migrate' if args.dry_run else 'Migrated'}: {migrated}/{len(items)}")


if __name__ == "__main__":
    main()
