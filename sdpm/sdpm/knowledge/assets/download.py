# SPDX-License-Identifier: MIT-0
"""Download official asset catalogs into an SDPM asset directory."""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from urllib.request import urlopen

from sdpm.config import assets_install_dir

ASSET_PACKAGE_URL = "https://d1.awsstatic.com/onedam/marketing-channels/website/aws/en_US/architecture/approved/architecture-icons/Icon-package_01302026.31b40d126ed27079b708594940ad577a86150582.zip"
MATERIAL_REPO_URL = "https://github.com/marella/material-symbols.git"
MATERIAL_SVG_SUBDIR = "svg/400/outlined"
SUPPORTED_SOURCES = ("aws", "material")

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

_CATEGORY_PATTERN = re.compile(r"Architecture-Service-Icons_\d+/Arch_(.+?)/")
_RESOURCE_CATEGORY_PATTERN = re.compile(r"Resource-Icons_\d+/Res_(.+?)/")

MATERIAL_CATEGORIES: dict[str, list[str]] = {
    "action": [
        "search", "home", "settings", "delete", "done", "info", "check_circle",
        "visibility", "favorite", "bookmark", "lock", "thumb_up", "build",
        "code", "bug_report", "schedule", "trending_up", "analytics",
        "dashboard", "receipt", "assignment", "launch", "open_in_new",
        "power_settings_new", "shopping_cart", "account_balance",
    ],
    "communication": [
        "email", "chat", "phone", "message", "forum", "call",
        "contact_mail", "contact_phone", "notifications",
    ],
    "content": [
        "add", "remove", "create", "save", "send", "link", "flag",
        "filter_list", "sort", "copy", "paste", "undo", "redo",
    ],
    "navigation": [
        "arrow_back", "arrow_forward", "arrow_upward", "arrow_downward",
        "chevron_left", "chevron_right", "expand_more", "expand_less",
        "menu", "close", "refresh", "fullscreen", "more_vert", "more_horiz",
    ],
    "file": [
        "folder", "file", "upload", "download", "cloud", "cloud_upload",
        "cloud_download", "attach_file", "description",
    ],
    "hardware": [
        "computer", "phone_android", "phone_iphone", "tablet", "tv",
        "keyboard", "mouse", "memory", "storage", "dns", "router",
    ],
    "social": [
        "person", "group", "people", "share", "public", "school",
        "work", "business", "engineering",
    ],
    "alert": ["warning", "error", "notification_important"],
    "editor": [
        "format_bold", "format_italic", "format_list_bulleted",
        "format_list_numbered", "title", "table_chart",
    ],
    "maps": ["place", "map", "directions", "local_shipping", "flight", "hotel"],
}

_ICON_TO_CATEGORY = {
    icon: category
    for category, icons in MATERIAL_CATEGORIES.items()
    for icon in icons
}


def _extract_category(zip_path: str) -> str:
    """Extract an AWS icon category from its ZIP path."""
    match = _CATEGORY_PATTERN.search(zip_path)
    if match:
        return match.group(1).replace("-", " ").replace("_", " ")
    match = _RESOURCE_CATEGORY_PATTERN.search(zip_path)
    if match:
        return match.group(1).replace("-", " ").replace("_", " ")
    return "General"


def _classify_type(filename: str, zip_path: str) -> str:
    """Classify an AWS icon as service, resource, category, group, or general."""
    if "Arch_" in filename:
        return "service"
    if "Res_" in filename:
        return "resource"
    if "Category" in zip_path:
        return "category"
    if "Group" in zip_path:
        return "group"
    return "general"


def _is_target_entry(zip_path: str) -> bool:
    """Return whether a ZIP entry is the desired SVG size variant."""
    if not zip_path.endswith(".svg"):
        return False
    if "Architecture-Group-Icons" in zip_path:
        return "_32" in zip_path
    return "_48" in zip_path


def _name_from_filename(filename: str) -> str:
    """Convert an AWS icon filename to a human-readable name."""
    stem = filename.rsplit(".", 1)[0]
    stem = re.sub(r"_\d+$", "", stem)
    stem = re.sub(r"^(Arch_|Res_)", "", stem)
    return stem.replace("-", " ").replace("_", " ")


def _generate_aws_tags(name: str, category: str, icon_type: str) -> list[str]:
    tags = []
    if category:
        tags.append(category.lower())
    if icon_type:
        tags.append(icon_type)
    for full_name, aliases in AWS_ALIASES.items():
        if full_name.lower() in name.lower() or name.lower() in full_name.lower():
            tags.extend(aliases)
    for word in name.lower().split():
        if len(word) > 2 and word not in tags:
            tags.append(word)
    return tags


def _categorize(name: str) -> str:
    """Return the category for a Material Symbol."""
    return _ICON_TO_CATEGORY.get(name, "general")


def _generate_material_tags(name: str, category: str) -> list[str]:
    tags = [category]
    for word in name.replace("_", " ").split():
        if len(word) > 1 and word not in tags:
            tags.append(word)
    return tags


def _write_atomic(path: Path, text: str) -> None:
    """Write the manifest last and atomically — readers see either no catalog or a complete one."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _install_aws(destination: Path) -> dict:
    print("Downloading AWS Architecture Icons...", file=sys.stderr)
    print(f"  URL: {ASSET_PACKAGE_URL}", file=sys.stderr)

    response = urlopen(ASSET_PACKAGE_URL)  # nosec B310
    zip_data = io.BytesIO(response.read())
    destination.mkdir(parents=True, exist_ok=True)

    icons: list[dict] = []
    with zipfile.ZipFile(zip_data) as archive:
        for info in archive.infolist():
            if info.is_dir() or not _is_target_entry(info.filename):
                continue
            filename = Path(info.filename).name
            if filename.startswith("._"):
                continue
            category = _extract_category(info.filename)
            icon_type = _classify_type(filename, info.filename)
            name = _name_from_filename(filename)
            (destination / filename).write_bytes(archive.read(info))
            icons.append({
                "name": name,
                "file": filename,
                "tags": _generate_aws_tags(name, category, icon_type),
                "category": category,
                "type": icon_type,
                "aspectRatio": 1,
            })

    icons.sort(key=lambda item: (item["category"], item["name"]))
    manifest = {
        "source": "aws",
        "description": "AWS Architecture Icons — official service and resource icons for architecture diagrams",
        "recolorProtected": True,
        "icons": icons,
    }
    manifest_path = destination / "manifest.json"
    _write_atomic(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False))

    print(f"  Extracted: {len(icons)} SVG icons", file=sys.stderr)
    print(f"  Manifest: {manifest_path} ({len(icons)} entries)", file=sys.stderr)
    print("  Done!", file=sys.stderr)
    return {"source": "aws", "count": len(icons), "manifest": str(manifest_path)}


def _install_material(destination: Path) -> dict:
    print("Downloading Material Symbols (outlined, weight 400)...", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / "material-symbols"
        print("  Cloning (sparse)...", file=sys.stderr)
        subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            ["git", "clone", "--depth=1", "--filter=blob:none", "--sparse", MATERIAL_REPO_URL, str(repo_dir)],
            check=True,
            capture_output=True,
        )
        subprocess.run(  # nosec B603 # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            ["git", "sparse-checkout", "set", MATERIAL_SVG_SUBDIR],
            cwd=str(repo_dir),
            check=True,
            capture_output=True,
        )

        svg_dir = repo_dir / MATERIAL_SVG_SUBDIR
        if not svg_dir.exists():
            print(f"  Error: {MATERIAL_SVG_SUBDIR} not found in repo", file=sys.stderr)
            sys.exit(1)
        destination.mkdir(parents=True, exist_ok=True)

        icons: list[dict] = []
        for svg_file in sorted(svg_dir.glob("*.svg")):
            name = svg_file.stem
            category = _categorize(name)
            shutil.copy2(svg_file, destination / svg_file.name)
            icons.append({
                "name": name.replace("_", " ").title(),
                "file": svg_file.name,
                "tags": _generate_material_tags(name, category),
                "category": category,
                "type": "outlined",
                "aspectRatio": 1,
            })

    icons.sort(key=lambda item: (item["category"], item["name"]))
    manifest = {
        "source": "material",
        "description": "Material Symbols by Google — general-purpose icons for UI and presentations (Apache 2.0)",
        "icons": icons,
    }
    manifest_path = destination / "manifest.json"
    _write_atomic(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False))

    print(f"  Extracted: {len(icons)} SVG icons", file=sys.stderr)
    print(f"  Manifest: {manifest_path} ({len(icons)} entries)", file=sys.stderr)
    print("  Done!", file=sys.stderr)
    return {"source": "material", "count": len(icons), "manifest": str(manifest_path)}


def install_assets(sources: list[str], dest: Path | None = None) -> dict:
    """Install official asset catalogs and return per-source results.

    Args:
        sources: Source names to install. Supported values are ``aws`` and
            ``material``.
        dest: Base assets directory. Defaults to :func:`assets_install_dir`.
    """
    normalized = list(dict.fromkeys(source.strip().lower() for source in sources if source.strip()))
    unsupported = [source for source in normalized if source not in SUPPORTED_SOURCES]
    if unsupported:
        choices = ", ".join(SUPPORTED_SOURCES)
        raise ValueError(f"Unsupported asset source(s): {', '.join(unsupported)}. Choose from: {choices}")
    if not normalized:
        raise ValueError("At least one asset source is required")

    base = Path(dest).expanduser() if dest is not None else assets_install_dir()
    installers = {"aws": _install_aws, "material": _install_material}
    results = [installers[source](base / source) for source in normalized]
    return {"destination": str(base), "sources": results}


_background: dict = {"state": "idle", "error": None, "thread": None}
_background_lock = threading.Lock()


def install_status() -> dict:
    """State of the background installation: idle | running | done | failed."""
    return {"state": _background["state"], "error": _background["error"]}


def ensure_assets_installed_async() -> bool:
    """Install the official catalogs in a background thread if none is present.

    Called by long-lived hosts at startup so that a clone-free setup needs no
    separate install step. Returns True when an installation was started. Never
    raises — a failure is recorded in :func:`install_status` and the host keeps
    serving; ``search_assets`` reports the state to the agent.
    """
    from sdpm.knowledge.assets import assets_installed, invalidate_manifest_cache

    with _background_lock:
        if _background["state"] == "running" or assets_installed():
            return False
        _background["state"] = "running"
        _background["error"] = None

    def _run() -> None:
        try:
            install_assets(list(SUPPORTED_SOURCES))
            invalidate_manifest_cache()
            _background["state"] = "done"
        except Exception as error:  # noqa: BLE001 - reported through install_status
            _background["error"] = str(error)
            _background["state"] = "failed"
            print(f"Asset installation failed: {error}", file=sys.stderr)

    thread = threading.Thread(target=_run, name="sdpm-install-assets", daemon=True)
    _background["thread"] = thread
    thread.start()
    return True


def _parse_sources(value: str) -> list[str]:
    return [source.strip() for source in value.split(",") if source.strip()]


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for installing one or more asset catalogs."""
    parser = argparse.ArgumentParser(description="Install official asset catalogs for SDPM.")
    parser.add_argument(
        "--sources",
        default=",".join(SUPPORTED_SOURCES),
        help="Comma-separated sources to install (default: aws,material)",
    )
    args = parser.parse_args(argv)
    try:
        install_assets(_parse_sources(args.sources))
    except ValueError as error:
        parser.error(str(error))


def source_main(source: str, argv: list[str] | None = None) -> None:
    """Compatibility CLI used by the historical per-source scripts."""
    parser = argparse.ArgumentParser(description=f"Install the {source} asset catalog for SDPM.")
    parser.parse_args(argv)
    install_assets([source])
