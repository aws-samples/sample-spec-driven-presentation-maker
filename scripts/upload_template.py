#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Upload a PowerPoint template to S3 (encrypted at rest via SSE-S3).

Ensure the target S3 bucket has public access blocked and versioning enabled.

Upload a PowerPoint template to S3 and register in DynamoDB.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

Runs analyze-template automatically and stores results in DDB.

Usage:
    python scripts/upload_template.py \
        --file template.pptx \
        --name "Corporate 2026" \
        --bucket my-sdpm-bucket \
        --table my-sdpm-table \
        [--default] \
        [--region us-east-1]
"""

import argparse
import json
import uuid
from datetime import datetime, timezone

import boto3


def main() -> None:
    """Parse args and upload template."""
    parser = argparse.ArgumentParser(description="Upload template to spec-driven-presentation-maker")
    parser.add_argument("--file", required=True, help="Path to .pptx template file")
    parser.add_argument("--name", required=True, help="Display name for the template")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--table", required=True, help="DynamoDB table name")
    parser.add_argument("--default", action="store_true", help="Set as default template")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)
    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    table = dynamodb.Table(args.table)

    template_id = str(uuid.uuid4())[:8]
    s3_key = f"templates/{template_id}.pptx"
    now = datetime.now(timezone.utc).isoformat()

    # Upload to S3
    print(f"Uploading {args.file} to s3://{args.bucket}/{s3_key}")
    s3.upload_file(args.file, args.bucket, s3_key)

    # Run analyze-template and extract fonts if available
    analysis_json = "{}"
    fonts = {"fullwidth": None, "halfwidth": None}
    try:
        from pathlib import Path as P
        from sdpm.analyzer import analyze_template, extract_fonts
        analysis = analyze_template(P(args.file))
        analysis_json = json.dumps(analysis, ensure_ascii=False)
        fonts = extract_fonts(P(args.file))
        print(f"Template analysis complete: {len(analysis.get('layouts', []))} layouts, fonts={fonts}")
    except ImportError:
        print("Warning: sdpm.analyzer not available, skipping analysis")

    # Register in DynamoDB
    item = {
        "PK": f"TEMPLATE#{template_id}",
        "SK": "META",
        "name": args.name,
        "s3Key": s3_key,
        "analysisJson": analysis_json,
        "fonts": fonts,
        "isDefault": args.default,
        "createdAt": now,
        "updatedAt": now,
    }
    table.put_item(Item=item)
    print(f"Template registered: {template_id} ({args.name})")

    if args.default:
        print("Set as default template")


if __name__ == "__main__":
    main()
