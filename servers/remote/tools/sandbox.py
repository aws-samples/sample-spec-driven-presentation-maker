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
_WORKSPACE_PREFIXES = ("deck.json", "slides/", "specs/", "includes/", "attachments/")
_IMMUTABLE_IMPORT_PREFIX = "attachments/imports/"


# Helpers injected into every sandbox session so agent code can be written once
# and run unchanged on Local (AST-restricted subprocess) and Cloud (AgentCore
# Code Interpreter). These mirror servers/local/sandbox.py's _RUNNER_WITH_DECK.
_HELPERS_PY = '''\
import json as _json
from pathlib import Path as _Path

def _assert_writable(path):
    normalized = _Path(path)
    if len(normalized.parts) >= 2 and normalized.parts[:2] == ("attachments", "imports"):
        raise PermissionError(f"Committed import bundles are read-only: {path}")

def read_json(path):
    return _json.loads(_Path(path).read_text(encoding="utf-8"))

def write_json(path, data):
    _assert_writable(path)
    p = _Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")

def read_text(path):
    return _Path(path).read_text(encoding="utf-8")

def write_text(path, text):
    _assert_writable(path)
    p = _Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

def list_files(subdir="."):
    d = _Path(subdir)
    if not d.is_dir():
        raise FileNotFoundError(f"Not a directory: {subdir}")
    return sorted(f.name for f in d.iterdir() if f.is_file())
'''

# Prepended to every user code invocation so read_json / write_json / ...
# are available without an explicit import. Agents must NOT write their own
# 'from _sdpm_helpers import ...' line — the injection handles it so Local
# and Cloud guide code can stay identical (Local's AST forbids import).
_HELPERS_IMPORT = (
    "from _sdpm_helpers import read_json, write_json, read_text, write_text, list_files\n"
)



def execute_in_sandbox(
    code: str,
    storage: Storage,
    region: str,
    deck_id: str | None = None,
    persist_writes: bool = True,
) -> tuple[str, list[dict], list[dict], list[str]]:
    """Execute Python code in Amazon Bedrock AgentCore Code Interpreter sandbox.

    When deck_id is provided, the entire deck workspace is loaded into the
    sandbox filesystem. The user code can read/write any file via normal
    file I/O (open, json.load, etc.). Modified and new files are always
    written back to S3 (diff against the session-start snapshot) — there is
    no "unsaved" state.

    Args:
        code: Python code to execute.
        storage: Storage backend for S3 operations.
        region: AWS region for Code Interpreter API.
        deck_id: If provided, loads deck workspace into sandbox.
        persist_writes: Set False to run without write-back (used when the
            caller only has read access to the deck).

    Returns:
        Tuple of (output, outline_warnings, lint_diagnostics, changed paths).
    """

    client = boto3.client("bedrock-agentcore", region_name=region)

    session = client.start_code_interpreter_session(
        codeInterpreterIdentifier="aws.codeinterpreter.v1",
        name=f"pptx-{deck_id or 'calc'}",
        sessionTimeoutSeconds=300,
    )
    session_id = session["sessionId"]
    logger.info("Code Interpreter session started: %s", session_id)

    try:
        # Load deck workspace into sandbox (baseline snapshot for diff-based
        # write-back)
        baseline: dict[str, str] = {}
        if deck_id:
            baseline = _upload_deck_workspace(client, session_id, storage, deck_id)

        # Inject shared sandbox helpers (read_json / write_json / ...) so user
        # code can use the same API on Local and Cloud.
        _inject_helpers(client, session_id)

        # Execute user code (prefixed with helper import so agents can use
        # read_json / write_json / ... without an explicit import).
        response = client.invoke_code_interpreter(
            codeInterpreterIdentifier="aws.codeinterpreter.v1",
            sessionId=session_id,
            name="executeCode",
            arguments={"language": "python", "code": _HELPERS_IMPORT + code},
        )
        output = _collect_stream(response)

        # Always write modified workspace files back to S3 — writes persist
        # unconditionally (diff-based, changed/new files only).
        outline_warnings: list[dict] = []
        lint_diagnostics: list[dict] = []
        changed_paths: list[str] = []
        if deck_id and persist_writes:
            outline_warnings, lint_diagnostics, changed_paths = _save_deck_workspace(
                client, session_id, storage, deck_id, baseline=baseline,
            )
            if changed_paths:
                logger.info(
                    "Deck workspace saved for deck %s (%d changed files)",
                    deck_id, len(changed_paths),
                )

        return output, outline_warnings, lint_diagnostics, changed_paths

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
) -> dict[str, str]:
    """Download all deck files from S3 and write them into the sandbox.

    Args:
        client: Bedrock AgentCore client.
        session_id: Code Interpreter session ID.
        storage: Storage backend.
        deck_id: Deck identifier.

    Returns:
        Mapping of relative path → uploaded text content (baseline snapshot
        used for diff-based write-back).
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
            "code": "import os\nfor d in ('slides', 'specs', 'includes', 'images', 'attachments'):\n    os.makedirs(d, exist_ok=True)\n",
        },
    )

    return {f["path"]: f["text"] for f in file_contents}


def _save_deck_workspace(
    client: Any,
    session_id: str,
    storage: Storage,
    deck_id: str,
    baseline: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict], list[str]]:
    """Read workspace files from sandbox via prefix scan and write back to S3.

    Scans the sandbox for files matching _WORKSPACE_PREFIXES instead of
    relying on the upload paths list. This ensures newly created files
    (e.g., slides/{slug}.json) are automatically saved.

    Diff-based: files whose content equals the baseline (what was uploaded
    at session start) are skipped. This keeps the always-persist contract
    cheap and prevents a stale sandbox copy from clobbering files another
    writer changed on S3 in the meantime.

    Args:
        client: Bedrock AgentCore client.
        session_id: Code Interpreter session ID.
        storage: Storage backend.
        deck_id: Deck identifier.
        baseline: Relative path → content as uploaded at session start.

    Returns:
        Tuple of (outline_warnings, lint_diagnostics, changed relative paths).
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
    file_map = {
        path: text for path, text in file_map.items()
        if not path.startswith(_IMMUTABLE_IMPORT_PREFIX)
    }

    # Diff against the session-start baseline — only changed/new files are
    # written back. Unchanged files are skipped so a stale sandbox copy can
    # never overwrite a newer S3 write from a parallel session.
    if baseline:
        file_map = {p: t for p, t in file_map.items() if baseline.get(p) != t}

    # Lint outline.md before saving — warn on failure
    outline_warnings: list[dict] = []
    outline_key = "specs/outline.md"
    if outline_key in file_map and file_map[outline_key].strip():
        from sdpm.engine.schema.lint_outline import lint_outline

        outline_warnings = lint_outline(file_map[outline_key])
        if outline_warnings:
            logger.warning("outline.md lint warnings for deck %s: %s", deck_id, outline_warnings)

    # Lint and sanitize slide JSON before saving
    lint_diagnostics: list[dict] = []
    from sdpm.engine.schema.lint import lint_and_sanitize

    for rel_path in list(file_map.keys()):
        if rel_path.startswith("slides/") and rel_path.endswith(".json"):
            try:
                slide_data = json.loads(file_map[rel_path])
                cleaned, diags = lint_and_sanitize(slide_data)
                if diags:
                    slug = rel_path.removeprefix("slides/").removesuffix(".json")
                    for d in diags:
                        d["slug"] = slug
                    lint_diagnostics.extend(diags)
                    # Reserialize only when sanitization changed the content —
                    # keeps Local/Remote semantics aligned (Local skips the
                    # rewrite for diagnostics-only lint results).
                    if cleaned != slide_data:
                        file_map[rel_path] = json.dumps(cleaned, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass

    # Write back to S3 (changed/new files only)
    prefix = f"decks/{deck_id}/"
    for rel_path, text in file_map.items():
        s3_key = prefix + rel_path
        storage.upload_file(
            key=s3_key,
            data=text.encode("utf-8"),
            content_type=_content_type(rel_path),
        )

    return outline_warnings, lint_diagnostics, sorted(file_map.keys())


def _inject_helpers(client: Any, session_id: str) -> None:
    """Write the shared helper module into the sandbox cwd.

    Runs after _upload_deck_workspace so `_sdpm_helpers.py` sits alongside
    the deck files. User code gets these helpers via the `_HELPERS_IMPORT`
    prefix prepended to every invocation in `execute_in_sandbox`.
    """
    _write_files(client, session_id, [{"path": "_sdpm_helpers.py", "text": _HELPERS_PY}])


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
