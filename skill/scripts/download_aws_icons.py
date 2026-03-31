# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Download AWS Architecture Icons and generate manifest.json.

Downloads the official AWS Architecture Icon set (SVG),
extracts to assets/aws/, and generates a unified manifest.json.

Usage:
    uv run python3 scripts/download_aws_icons.py
"""

import io
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen

# AWS Architecture Icons download page
ASSET_PACKAGE_URL = "https://d1.awsstatic.com/onedam/marketing-channels/website/aws/en_US/architecture/approved/architecture-icons/Icon-package_01302026.31b40d126ed27079b708594940ad577a86150582.zip"

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "aws"

# AWS service abbreviation aliases → tags
AWS_ALIASES: dict[str, list[str]] = {
    "Amazon Simple Queue Service": ["sqs"],
    "Amazon Simple Notification Service": ["sns"],
    "Amazon Simple Email Service": ["ses"],
    "Amazon Simple Storage Service": ["s3"],
    "Amazon Elastic Block Store": ["ebs"],
    "Amazon Elastic File System": ["efs"],
    "Elastic Load Balancing": ["elb"],
    "Amazon Elastic Container Registry": ["ecr"],
    "Amazon Elastic Container Service": ["ecs"],
    "Amazon Elastic Kubernetes Service": ["eks"],
    "Amazon Virtual Private Cloud": ["vpc"],
    "AWS Identity and Access Management": ["iam"],
    "AWS Key Management Service": ["kms"],
    "AWS Certificate Manager": ["acm"],
    "AWS WAF": ["waf"],
    "AWS Systems Manager": ["ssm"],
    "AWS CloudFormation": ["cfn"],
    "AWS Cloud Development Kit": ["cdk"],
    "AWS Command Line Interface": ["cli"],
    "Amazon DynamoDB": ["ddb", "dynamodb"],
    "Amazon Managed Streaming for Apache Kafka": ["msk"],
    "Amazon Managed Workflows for Apache Airflow": ["mwaa"],
    "Amazon EMR": ["emr", "elastic mapreduce"],
    "AWS Lambda": ["lambda"],
}

# Category extraction from file path
_CATEGORY_PATTERN = re.compile(r"Architecture-Service-Icons_\d+/Arch_(.+?)/")
_RESOURCE_CATEGORY_PATTERN = re.compile(r"Resource-Icons_\d+/Res_(.+?)/")


def _extract_category(zip_path: str) -> str:
    """Extract category name from ZIP file path.

    Args:
        zip_path: Path within the ZIP archive.

    Returns:
        Category name (e.g. "Compute", "Storage").
    """
    m = _CATEGORY_PATTERN.search(zip_path)
    if m:
        return m.group(1).replace("-", " ").replace("_", " ")
    m = _RESOURCE_CATEGORY_PATTERN.search(zip_path)
    if m:
        return m.group(1).replace("-", " ").replace("_", " ")
    return "General"


def _classify_type(filename: str, zip_path: str) -> str:
    """Classify icon type from filename and path.

    Args:
        filename: SVG filename.
        zip_path: Full path within ZIP.

    Returns:
        Type string: service, resource, category, group, or general.
    """
    if "Arch_" in filename:
        return "service"
    if "Res_" in filename:
        return "resource"
    if "Category" in zip_path:
        return "category"
    if "Group" in zip_path:
        return "group"
    return "general"


def _name_from_filename(filename: str) -> str:
    """Extract human-readable name from icon filename.

    Args:
        filename: SVG filename (e.g. "Arch_Amazon-S3_48.svg").

    Returns:
        Human-readable name (e.g. "Amazon S3").
    """
    stem = filename.rsplit(".", 1)[0]
    # Remove size suffix like _48, _64
    stem = re.sub(r"_\d+$", "", stem)
    # Remove prefix
    stem = re.sub(r"^(Arch_|Res_)", "", stem)
    # Convert separators to spaces
    name = stem.replace("-", " ").replace("_", " ")
    return name


def _generate_tags(name: str, category: str, icon_type: str) -> list[str]:
    """Generate search tags for an icon.

    Args:
        name: Human-readable icon name.
        category: Icon category.
        icon_type: Icon type.

    Returns:
        List of search tags.
    """
    tags = []
    # Add category as tag
    if category:
        tags.append(category.lower())
    # Add type as tag
    if icon_type:
        tags.append(icon_type)
    # Add alias tags
    for full_name, aliases in AWS_ALIASES.items():
        if full_name.lower() in name.lower() or name.lower() in full_name.lower():
            tags.extend(aliases)
    # Add individual words from name
    for word in name.lower().split():
        if len(word) > 2 and word not in tags:
            tags.append(word)
    return tags


def main() -> None:
    """Download AWS Architecture Icons and generate manifest."""
    print("Downloading AWS Architecture Icons...", file=sys.stderr)
    print(f"  URL: {ASSET_PACKAGE_URL}", file=sys.stderr)

    response = urlopen(ASSET_PACKAGE_URL)  # nosec B310
    zip_data = io.BytesIO(response.read())

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    icons: list[dict] = []
    extracted = 0

    with zipfile.ZipFile(zip_data) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # Only extract 48px SVGs (standard size)
            if not info.filename.endswith(".svg"):
                continue
            if "_48" not in info.filename:
                continue

            filename = Path(info.filename).name
            # Skip macOS metadata files
            if filename.startswith("._"):
                continue
            category = _extract_category(info.filename)
            icon_type = _classify_type(filename, info.filename)
            name = _name_from_filename(filename)
            tags = _generate_tags(name, category, icon_type)

            # Extract SVG file
            out_path = ASSETS_DIR / filename
            out_path.write_bytes(zf.read(info))
            extracted += 1

            icons.append({
                "name": name,
                "file": filename,
                "tags": tags,
                "category": category,
                "type": icon_type,
                "aspectRatio": 1,
            })

    # Sort by category then name
    icons.sort(key=lambda x: (x["category"], x["name"]))

    manifest = {
        "source": "aws",
        "description": "AWS Architecture Icons — official service and resource icons for architecture diagrams",
        "icons": icons,
    }

    manifest_path = ASSETS_DIR / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"  Extracted: {extracted} SVG icons", file=sys.stderr)
    print(f"  Manifest: {manifest_path} ({len(icons)} entries)", file=sys.stderr)
    print("  Done!", file=sys.stderr)


if __name__ == "__main__":
    main()
