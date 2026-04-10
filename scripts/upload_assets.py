#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Upload assets to S3 resource bucket (encrypted at rest via SSE-S3).

Ensure the target S3 bucket has public access blocked.

Upload assets to S3 resource bucket with source-based manifest.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

Uploads asset files (SVG, PNG, etc.) to assets/{source}/ in S3 and
generates a manifest.json compatible with search_assets_tool.

Manifest schema (Layer 1 compatible):
    [{"name": "Amazon S3", "file": "s3.svg", "tags": ["storage"]}]

Usage:
    uv run python scripts/upload_assets.py \
        --dir ./my-icons/ \
        --bucket my-resource-bucket \
        --source my-brand \
        [--region us-east-1]
"""

import argparse
import json
from pathlib import Path

import boto3

SUPPORTED_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"}


def main() -> None:
    """Parse args and upload assets with source-based manifest."""
    parser = argparse.ArgumentParser(description="Upload assets to spec-driven-presentation-maker")
    parser.add_argument("--dir", required=True, help="Local directory with asset files")
    parser.add_argument("--bucket", required=True, help="S3 resource bucket name")
    parser.add_argument("--source", required=True, help="Asset source name (e.g. aws, material, my-brand)")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)
    local_dir = Path(args.dir)

    if not local_dir.is_dir():
        print(f"Error: {local_dir} is not a directory")
        return

    # Check for existing local manifest.json
    local_manifest_path = local_dir / "manifest.json"
    if local_manifest_path.exists():
        manifest = json.loads(local_manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, list):
            manifest = manifest.get("assets", manifest.get("icons", []))
        print(f"Using existing manifest.json ({len(manifest)} entries)")
    else:
        # Auto-generate manifest from files
        manifest = _generate_manifest(local_dir)
        print(f"Generated manifest from files ({len(manifest)} entries)")

    # Upload asset files
    uploaded = 0
    for f in sorted(local_dir.rglob("*")):
        if f.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        rel = f.relative_to(local_dir)
        if ".." in rel.parts:
            print(f"  Skipping path traversal: {rel}")
            continue
        s3_key = f"assets/{args.source}/{rel}"
        print(f"  {rel} → s3://{args.bucket}/{s3_key}")
        s3.upload_file(str(f), args.bucket, s3_key)
        uploaded += 1

    # Upload manifest
    manifest_key = f"assets/{args.source}/manifest.json"
    s3.put_object(
        Bucket=args.bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )

    print(f"\nDone: {uploaded} files uploaded, manifest at s3://{args.bucket}/{manifest_key}")


def _generate_manifest(local_dir: Path) -> list[dict]:
    """Auto-generate manifest entries from files in directory.

    Args:
        local_dir: Directory containing asset files.

    Returns:
        List of manifest entries with name, file, tags.
    """
    entries: list[dict] = []
    for f in sorted(local_dir.rglob("*")):
        if f.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        rel = f.relative_to(local_dir)
        name = f.stem.replace("_", " ").replace("-", " ").title()
        entries.append({
            "name": name,
            "file": str(rel),
            "tags": [],
        })
    return entries


if __name__ == "__main__":
    main()
