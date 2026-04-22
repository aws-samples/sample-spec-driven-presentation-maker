# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Sandbox code execution via Amazon Bedrock AgentCore Code Interpreter.

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Wraps the Code Interpreter API to execute Python code in an isolated sandbox.
Used by run_python MCP tool for deck workspace editing and general computation.

Deck workspace layout (when deck_id is provided):
    deck.json           — deck metadata (new format)
    slides/             — per-slide JSON files (new format)
    presentation.json   — slide data (legacy format)
    specs/              — brief.md, art-direction.html, outline.md
    includes/           — code block JSON files
"""

import json
import logging
from pathlib import PurePosixPath
from typing import Any

import boto3

from storage import Storage

logger = logging.getLogger(__name__)

# Files managed by the deck workspace — only these are synced back to S3.
_WORKSPACE_PREFIXES = ("deck.json", "slides/", "specs/", "includes/")


def execute_in_sandbox(
    code: str,
    storage: Storage,
    region: str,
    deck_id: str | None = None,
    save: bool = False,
    files: list[str] | None = None,
) -> tuple[str, bool]:
    """Execute Python code in Amazon Bedrock AgentCore Code Interpreter sandbox.

    When deck_id is provided, the entire deck workspace is loaded into the
    sandbox filesystem. The user code can read/write any file via normal
    file I/O (open, json.load, etc.). If save=True, modified and new files
    are written back to S3.

    Args:
        code: Python code to execute.
        storage: Storage backend for S3 operations.
        region: AWS region for Code Interpreter API.
        deck_id: If provided, loads deck workspace into sandbox.
        save: If True, writes changed files back to S3. Requires deck_id.
        files: Additional S3 keys to download into sandbox by basename.

    Returns:
        Tuple of (code execution output, outline_rejected flag).

    Raises:
        ValueError: If save=True without deck_id, or duplicate filenames in files.
    """
    if save and not deck_id:
        raise ValueError("save=True requires deck_id")

    if files:
        basenames = [key.rsplit("/", 1)[-1] for key in files]
        seen: set[str] = set()
        for name in basenames:
            if name in seen:
                raise ValueError(f"Duplicate filename: {name}")
            seen.add(name)

    client = boto3.client("bedrock-agentcore", region_name=region)

    session = client.start_code_interpreter_session(
        codeInterpreterIdentifier="aws.codeinterpreter.v1",
        name=f"pptx-{deck_id or 'calc'}",
        sessionTimeoutSeconds=300,
    )
    session_id = session["sessionId"]
    logger.info("Code Interpreter session started: %s", session_id)

    try:
        # Load deck workspace into sandbox
        if deck_id:
            _upload_deck_workspace(client, session_id, storage, deck_id)

        # Upload additional files by basename
        if files:
            file_contents = []
            for key in files:
                data = storage.download_file_from_pptx_bucket(key)
                basename = key.rsplit("/", 1)[-1]
                file_contents.append({"path": basename, "text": data.decode("utf-8")})
            _write_files(client, session_id, file_contents)

        # Execute user code
        response = client.invoke_code_interpreter(
            codeInterpreterIdentifier="aws.codeinterpreter.v1",
            sessionId=session_id,
            name="executeCode",
            arguments={"language": "python", "code": code},
        )
        output = _collect_stream(response)

        # Save modified workspace files back to S3
        outline_rejected = False
        if save and deck_id:
            outline_rejected = _save_deck_workspace(
                client, session_id, storage, deck_id,
            )
            logger.info("Deck workspace saved for deck %s", deck_id)

        return output, outline_rejected

    finally:
        client.stop_code_interpreter_session(
            codeInterpreterIdentifier="aws.codeinterpreter.v1",
            sessionId=session_id,
        )
        logger.info("Code Interpreter session stopped: %s", session_id)


def _upload_deck_workspace(
    client: Any,
    session_id: str,
    storage: Storage,
    deck_id: str,
) -> list[str]:
    """Download all deck files from S3 and write them into the sandbox.

    Args:
        client: Bedrock AgentCore client.
        session_id: Code Interpreter session ID.
        storage: Storage backend.
        deck_id: Deck identifier.

    Returns:
        List of relative paths written to the sandbox.
    """
    prefix = f"decks/{deck_id}/"
    keys = storage.list_files(prefix=prefix, bucket=storage.pptx_bucket)

    file_contents: list[dict[str, str]] = []
    for key in keys:
        rel_path = key.removeprefix(prefix)
        if not any(rel_path.startswith(p) for p in _WORKSPACE_PREFIXES):
            continue
        try:
            data = storage.download_file_from_pptx_bucket(key)
            file_contents.append({"path": rel_path, "text": data.decode("utf-8")})
        except Exception:
            logger.warning("Skipping non-text file: %s", key)

    if file_contents:
        _write_files(client, session_id, file_contents)
        logger.info("Uploaded %d files to sandbox for deck %s", len(file_contents), deck_id)

    # Ensure workspace directories exist even when empty, so agent code like
    # open("slides/title.json", "w") works on the first write without needing
    # an explicit os.makedirs step.
    client.invoke_code_interpreter(
        codeInterpreterIdentifier="aws.codeinterpreter.v1",
        sessionId=session_id,
        name="executeCode",
        arguments={
            "language": "python",
            "code": "import os\nfor d in ('slides', 'specs', 'includes', 'images'):\n    os.makedirs(d, exist_ok=True)\n",
        },
    )

    return [f["path"] for f in file_contents]


def _save_deck_workspace(
    client: Any,
    session_id: str,
    storage: Storage,
    deck_id: str,
) -> bool:
    """Read workspace files from sandbox via prefix scan and write back to S3.

    Scans the sandbox for files matching _WORKSPACE_PREFIXES instead of
    relying on the upload paths list. This ensures newly created files
    (e.g., slides/{slug}.json) are automatically saved.

    If specs/outline.md is present and fails lint, it is excluded from the
    S3 write-back (rejected).

    Args:
        client: Bedrock AgentCore client.
        session_id: Code Interpreter session ID.
        storage: Storage backend.
        deck_id: Deck identifier.

    Returns:
        True if outline.md was rejected due to lint failure, False otherwise.
    """
    # Scan sandbox for all workspace files via executeCode
    prefixes_repr = repr(_WORKSPACE_PREFIXES)
    code = (
        "import json, os\n"
        f"_prefixes = {prefixes_repr}\n"
        "_result = {}\n"
        "for root, dirs, files in os.walk('.'):\n"
        "    for f in files:\n"
        "        rel = os.path.relpath(os.path.join(root, f), '.')\n"
        "        if any(rel == p or rel.startswith(p) for p in _prefixes):\n"
        "            try:\n"
        "                with open(rel, 'r') as fh:\n"
        "                    _result[rel] = fh.read()\n"
        "            except Exception:\n"
        "                pass\n"
        "print(json.dumps(_result))\n"
    )
    response = client.invoke_code_interpreter(
        codeInterpreterIdentifier="aws.codeinterpreter.v1",
        sessionId=session_id,
        name="executeCode",
        arguments={"language": "python", "code": code},
    )
    raw = _collect_stream(response)

    file_map: dict[str, str] = json.loads(raw)

    # Lint outline.md before saving — reject on failure
    outline_rejected = False
    outline_key = "specs/outline.md"
    if outline_key in file_map and file_map[outline_key].strip():
        from sdpm.schema.lint_outline import lint_outline

        if lint_outline(file_map[outline_key]):
            del file_map[outline_key]
            outline_rejected = True
            logger.warning("outline.md lint failed for deck %s — not saved", deck_id)

    # Write back to S3
    prefix = f"decks/{deck_id}/"
    for rel_path, text in file_map.items():
        s3_key = prefix + rel_path
        storage.upload_file(
            key=s3_key,
            data=text.encode("utf-8"),
            content_type=_content_type(rel_path),
        )

    return outline_rejected


def _write_files(client: Any, session_id: str, content: list[dict[str, str]]) -> None:
    """Write files into the sandbox.

    Args:
        client: Bedrock AgentCore client.
        session_id: Code Interpreter session ID.
        content: List of dicts with 'path' and 'text' keys.
    """
    client.invoke_code_interpreter(
        codeInterpreterIdentifier="aws.codeinterpreter.v1",
        sessionId=session_id,
        name="writeFiles",
        arguments={"content": content},
    )


def _collect_stream(response: dict[str, Any]) -> str:
    """Collect text output from Code Interpreter streaming response.

    Args:
        response: invoke_code_interpreter response with 'stream' key.

    Returns:
        Concatenated text output.
    """
    texts: list[str] = []
    for event in response["stream"]:
        if "result" in event:
            result = event["result"]
            if "content" in result:
                for item in result["content"]:
                    if item.get("type") == "text":
                        texts.append(item["text"])
    return "\n".join(texts)


def _content_type(path: str) -> str:
    """Determine content type from file extension.

    Args:
        path: File path.

    Returns:
        MIME content type string.
    """
    suffix = PurePosixPath(path).suffix.lower()
    return {
        ".json": "application/json",
        ".md": "text/markdown",
    }.get(suffix, "text/plain")
