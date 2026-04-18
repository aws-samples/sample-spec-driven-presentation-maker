# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""FastMCP Streamable HTTP server for Amazon Bedrock AgentCore Runtime (main entry point).

Security: AWS manages infrastructure security. You manage access control,
data classification, and IAM policies. See SECURITY.md for details.

Hosts all spec-driven-presentation-maker tools as MCP tools on 0.0.0.0:8000/mcp.
user_id is extracted from the Runtime-injected HTTP header.

Storage backend: AwsStorage (Amazon DynamoDB + S3) by default.
To use a custom backend, replace AwsStorage with your Storage ABC implementation.
"""

import json
import logging
import os
import re
import sys
from contextvars import ContextVar
from pathlib import Path

# Add skill/ to sys.path so sdpm engine is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skill"))

import boto3  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from shared.authz import authorize  # noqa: E402
from storage.aws import AwsStorage  # noqa: E402
from tools import assets, reference, preview, generate  # noqa: E402
from tools import sandbox as sandbox_mod  # noqa: E402
from tools import template as template_mod  # noqa: E402
from tools import init as init_mod  # noqa: E402
from tools import code_block as code_block_mod  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("sdpm.mcp")

# --- MCP Server Instructions ---

_INSTRUCTIONS = """spec-driven-presentation-maker: AI-powered PowerPoint generation from JSON.

## Architecture
- The agent edits workspace files via `run_python(deck_id=..., save=True)` using normal file I/O
- MCP tools handle: workflow guidance, initialization, PPTX generation, preview, references
- MCP tools do NOT handle: slide editing, spec writing (agent responsibility via run_python)

**Critical constraint:** Do NOT make any decisions about slide structure, content, design, or layout before loading the workflow. The workflow files contain the full process including briefing, outline, and art direction. Wait until the workflow is loaded and follow it step by step.

## Workflow: New Presentation

→ Read `read_workflows(["create-new-1-briefing"])` to start. Follow each file's Next Step from there.
"""

# TODO: Add these workflows when web UI supports them
# ## Workflow B: Edit Existing PPTX
# When an existing PPTX is provided.
# → Read `read_workflows(["edit-existing"])` to start.
#
# ## Workflow C: Hand-Edit Sync
# When the user hand-edits the generated PPTX in PowerPoint and then asks for further changes.
# → Read `read_workflows(["create-new-4-hand-edit-sync"])` to start.
#
# ## Workflow D: Create Style
# When the user wants to create a new reusable style guide.
# → Read `read_workflows(["create-style"])` to start.

mcp = FastMCP(
    "spec-driven-presentation-maker",
    host="0.0.0.0",
    stateless_http=True,
    instructions=_INSTRUCTIONS,
)

# --- HTTP Request ContextVar (for extracting user_id from Runtime header) ---
_current_request_headers: ContextVar[dict] = ContextVar("_current_request_headers", default={})


class _CaptureHeadersMiddleware:
    """Raw ASGI middleware to capture HTTP headers into a ContextVar.

    Compatible with streaming responses (unlike BaseHTTPMiddleware).
    """

    def __init__(self, app):  # type: ignore
        """Wrap an ASGI app.

        Args:
            app: The ASGI application to wrap.
        """
        self.app = app

    async def __call__(self, scope, receive, send):  # type: ignore
        """Capture headers from HTTP requests into ContextVar."""
        if scope["type"] == "http":
            headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
            token = _current_request_headers.set(headers)
            try:
                await self.app(scope, receive, send)
            finally:
                _current_request_headers.reset(token)
        else:
            await self.app(scope, receive, send)

# --- Storage backend (swap this to use a custom implementation) ---

_region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_table_name = os.environ.get("DECKS_TABLE", "")
_pptx_bucket = os.environ.get("PPTX_BUCKET", "")
_resource_bucket = os.environ.get("RESOURCE_BUCKET", "")
_kb_id = os.environ.get("KB_ID", "")
_kb_ssm_param = os.environ.get("KB_SSM_PARAM", "")
_vector_bucket_name = os.environ.get("VECTOR_BUCKET_NAME", "")
_vector_index_name = os.environ.get("VECTOR_INDEX_NAME", "")

if not _table_name:
    raise ValueError("DECKS_TABLE environment variable is required")
if not _pptx_bucket:
    raise ValueError("PPTX_BUCKET environment variable is required")
if not _resource_bucket:
    raise ValueError("RESOURCE_BUCKET environment variable is required")

_storage = AwsStorage(
    table=boto3.resource("dynamodb", region_name=_region).Table(_table_name),
    s3_client=boto3.client("s3", region_name=_region),
    pptx_bucket=_pptx_bucket,
    resource_bucket=_resource_bucket,
)


def _get_user_id() -> str:
    """Extract user ID from JWT sub claim in Authorization header.

    Amazon Bedrock AgentCore Runtime validates the JWT and passes it through via
    requestHeaderAllowlist. We decode without signature verification
    since Runtime has already validated the token.

    Returns:
        User ID string (JWT sub claim).

    Raises:
        ValueError: If Authorization header is missing or JWT has no sub.
    """
    headers = _current_request_headers.get()
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        import base64

        token = auth[7:].strip()
        try:
            payload = token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            sub = claims.get("sub", "")
            if sub:
                return sub
        except (IndexError, ValueError, json.JSONDecodeError):
            pass
    logger.warning("User ID extraction failed — missing or invalid JWT")
    raise ValueError("User ID not found. Provide a valid JWT Bearer token.")


def _check_deck_access(deck_id: str, action: str = "read") -> None:
    """Verify current user has permission for the specified action on the deck.

    Args:
        deck_id: Deck identifier to check.
        action: The operation being attempted (must be a key in DEFAULT_PERMISSIONS).

    Raises:
        ValueError: If access denied or deck_id is empty.
    """
    if not deck_id or not deck_id.strip():
        raise ValueError("deck_id cannot be empty")
    user_id = _get_user_id()
    decision = authorize(user_id=user_id, deck_id=deck_id, action=action, table=_storage.table)
    if not decision.allowed:
        logger.warning("Access denied: user=%s deck=%s action=%s reason=%s", user_id, deck_id, action, decision.reason)
        raise ValueError(f"Access denied: {decision.reason}")


# --- Workflow Tools ---


@mcp.tool()
def init_presentation(name: str) -> str:
    """Initialize a presentation. Creates a deck and empty workspace in S3.
    Call after Phase 1 hearing, before building slides.

    Workflow equivalent: ``init {name}``

    Args:
        name: Presentation name (e.g. "lambda-overview").

    Returns:
        JSON with deckId and workspace file list.
    """
    return json.dumps(
        init_mod.init_presentation(
            name=name.strip(), user_id=_get_user_id(),
            storage=_storage,
        ),
        ensure_ascii=False,
    )


@mcp.tool()
def analyze_template(template: str) -> str:
    """Get pre-analyzed template information — layouts, theme colors, fonts.
    Call this to understand what layouts are available before building slides.

    Args:
        template: Template name from list_templates. Required.

    Returns:
        JSON with layouts, theme colors, and font information.
    """
    if not template or not template.strip():
        return json.dumps({"error": "template is required"})
    return json.dumps(
        template_mod.analyze_template(template_name=template, storage=_storage),
        ensure_ascii=False,
    )


# --- Conversion Tools ---


@mcp.tool()
def save_web_image(url: str, deck_id: str, filename: str = "") -> str:
    """Download an image from a URL and save it to the deck workspace for use in slides.

    Use this after web_fetch(include_images=true) identifies images you want to use.
    The image is saved to decks/{deck_id}/images/{filename} and can be referenced
    in slide JSON as "images/{filename}".

    Args:
        url: The image URL to download.
        deck_id: The deck ID to save the image into.
        filename: Optional filename. If omitted, derived from the URL.

    Returns:
        JSON with the saved image path (use as "src" in slide elements).
    """
    import mimetypes
    import urllib.parse

    import requests as http_requests

    _check_deck_access(deck_id, action="edit_slide")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return json.dumps({"error": f"Only http/https URLs are allowed, got: {parsed.scheme}"})

    try:
        resp = http_requests.get(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; sdpm-agent/1.0)"}, timeout=30
        )
        resp.raise_for_status()
        data = resp.content
        ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    except Exception as e:
        return json.dumps({"error": f"Failed to download: {e}"})

    allowed = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}
    if ct not in allowed:
        return json.dumps({"error": f"Not an image: {ct}"})

    if not filename:
        basename = os.path.basename(url.split("?")[0].split("#")[0]) or "image"
        ext = mimetypes.guess_extension(ct) or ".png"
        if not basename.endswith(ext):
            basename = basename.rsplit(".", 1)[0] + ext if "." in basename else basename + ext
        filename = basename

    key = f"decks/{deck_id}/images/{filename}"
    _storage.upload_file(key=key, data=data, content_type=ct)
    src = f"images/{filename}"
    logger.info("save_web_image: %s → %s (%d bytes)", url, key, len(data))
    return json.dumps({"status": "ok", "src": src, "size": len(data)})


@mcp.tool()
def read_uploaded_file(upload_id: str, deck_id: str, page_start: int = 0) -> list:
    """Read an uploaded file's content. Returns text for documents, visual preview for images/PDFs.

    For images: saves original to deck workspace for use in slides, returns visual preview.
    For PDFs: extracts text and embedded images, saves images to deck workspace.
      Use page_start to paginate through long PDFs (e.g. page_start=20 for pages 21-40).
    For PPTX: returns extracted text and guidance to use pptx_to_json.

    Args:
        deck_id: The deck ID. Must be initialized first via init_presentation().
        upload_id: The upload identifier from the [Attached: ...] message.
        page_start: Page offset for PDF pagination (default 0). Use the value from the truncation message.

    Returns:
        Text content and/or image previews for visual analysis.
    """
    from tools.upload import read_uploaded_file as _read

    _check_deck_access(deck_id, action="edit_slide")
    return _read(
        upload_id=upload_id,
        deck_id=deck_id,
        user_id=_get_user_id(),
        storage=_storage,
        page_start=page_start,
    )


@mcp.tool()
def pptx_to_json(deck_id: str, upload_id: str) -> str:
    """Convert an uploaded PPTX file to JSON representation for editing.
    Downloads the PPTX from S3, converts via Engine, and saves presentation.json to the deck workspace.

    Args:
        deck_id: The deck ID to save the converted JSON into.
        upload_id: The upload ID of the PPTX file.

    Returns:
        JSON with slide count and conversion status.
    """
    import tempfile
    import traceback
    from sdpm.converter import pptx_to_json as _convert

    _check_deck_access(deck_id, action="edit_slide")
    user_id = _get_user_id()

    try:
        # Look up upload record from DynamoDB
        resp = _storage.table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"UPLOAD#{upload_id}"})
        item = resp.get("Item")
        if not item:
            return json.dumps({"error": f"Upload {upload_id} not found"})

        s3_key = item.get("s3KeyRaw", "")
        if not s3_key:
            return json.dumps({"error": "No S3 key for upload"})

        # Download PPTX to temp dir and convert
        work_dir = Path(tempfile.mkdtemp())
        pptx_path = work_dir / "input.pptx"
        pptx_path.write_bytes(_storage.download_file_from_pptx_bucket(s3_key))
        result = _convert(pptx_path)

        # Upload extracted images to S3 deck workspace
        images_dir = pptx_path.with_suffix('') / "images"
        image_count = 0
        if images_dir.is_dir():
            import mimetypes
            for img_file in images_dir.iterdir():
                if img_file.is_file():
                    s3_img_key = f"decks/{deck_id}/images/{img_file.name}"
                    ct = mimetypes.guess_type(img_file.name)[0] or "application/octet-stream"
                    _storage.upload_file(key=s3_img_key, data=img_file.read_bytes(), content_type=ct)
                    image_count += 1

        # Cleanup
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)

        # Save as presentation.json in deck workspace
        pres_json = json.dumps(result, ensure_ascii=False)
        pres_key = f"decks/{deck_id}/presentation.json"
        _storage.upload_file(key=pres_key, data=pres_json.encode("utf-8"), content_type="application/json")

        slide_count = len(result.get("slides", []))
        logger.info("pptx_to_json completed: deck=%s slides=%s", deck_id, slide_count)
        return json.dumps({
            "status": "ok",
            "slideCount": slide_count,
            "deckId": deck_id,
            "jsonPath": "presentation.json",
            "hint": f'Use run_python(deck_id="{deck_id}") with open("presentation.json") to read/edit the converted JSON.',
        })
    except Exception as e:
        logger.exception("pptx_to_json failed: deck=%s upload=%s", deck_id, upload_id)
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


# --- Generation Tools ---


@mcp.tool()
def generate_pptx(deck_id: str) -> str:
    """Generate final PPTX from presentation.json. Resolves include references automatically.
    Call after slides are written to presentation.json.

    Args:
        deck_id: The deck ID to generate PPTX from.

    Returns:
        JSON with status and pptxS3Key.
    """
    _check_deck_access(deck_id, action="generate_pptx")
    import traceback
    try:
        result = generate.generate_pptx(
            deck_id=deck_id, user_id=_get_user_id(), storage=_storage,
            kb_sync=_kb_sync,
        )
        logger.info("generate_pptx completed: deck=%s slides=%s", deck_id, result.get("slideCount"))
        return json.dumps(result)
    except Exception as e:
        logger.exception("generate_pptx failed: deck=%s", deck_id)
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


@mcp.tool()
def get_preview(deck_id: str, slide_numbers: list[int], quality: str = "high") -> list:
    """Get PNG preview images for visual review by the agent.

    Returns actual slide images that the model can see and analyze.
    Available after generate_pptx completes.

    - quality="low" (800px): Review all slides at once — check flow, structure, design consistency.
    - quality="high" (1280px): Precise review of specific slides — check text, layout details.

    Args:
        deck_id: The deck ID.
        slide_numbers: List of 1-based slide numbers to preview (required, at least one).
        quality: "low" (800px, ~480 tokens/slide) or "high" (1280px, ~1229 tokens/slide).

    Returns:
        List of text labels and slide images for visual inspection.
    """
    _check_deck_access(deck_id, action="preview")
    if not slide_numbers:
        return [{"type": "text", "text": "Error: slide_numbers must not be empty"}]
    if quality not in ("low", "high"):
        quality = "high"
    try:
        return preview.get_preview(
            deck_id=deck_id, slide_numbers=slide_numbers, storage=_storage, quality=quality,
        )
    except _storage._s3.exceptions.NoSuchKey:
        return [{"type": "text", "text": f"Preview not available yet. Run generate_pptx(deck_id=\"{deck_id}\") first."}]
    except Exception as e:
        if "NoSuchKey" in str(e):
            return [{"type": "text", "text": f"Preview not available yet. Run generate_pptx(deck_id=\"{deck_id}\") first."}]
        raise


def _build_pptx(tmpdir: Path, slides: list[dict], build_kwargs: dict) -> Path:
    """Build PPTX from slides JSON. Returns path to built file."""
    from sdpm.builder import PPTXBuilder, resolve_override

    builder = PPTXBuilder(**build_kwargs)
    id_map: dict[str, dict] = {}
    for s in slides:
        if "id" in s:
            id_map[s["id"]] = s
    for s in slides:
        builder.add_slide(resolve_override(s, id_map))
    pptx_path = tmpdir / "measure.pptx"
    builder.save(pptx_path)
    return pptx_path


def _export_svg(tmpdir: Path, pptx_path: Path) -> Path:
    """PPTX → SVG via LibreOffice. Returns svg_path."""
    import subprocess
    env = os.environ.copy()
    env["HOME"] = str(tmpdir)
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "svg", "--outdir", str(tmpdir), str(pptx_path)],
        env=env, capture_output=True, text=True, timeout=120, check=True,
    )
    return tmpdir / "measure.svg"


def _run_measure(tmpdir: Path, pptx_path: Path, slide_numbers: list[int]) -> str:
    """PPTX → SVG → bbox measurement → report string."""
    from sdpm.preview.measure import measure_from_svg, format_measure_report

    svg_path = _export_svg(tmpdir, pptx_path)
    if not svg_path.exists():
        return json.dumps({"error": "LibreOffice SVG export failed"})

    results = measure_from_svg(svg_path=svg_path, slide_indices=slide_numbers)
    return format_measure_report(results)


# --- Asset Tools ---


@mcp.tool()
def search_assets(query: str, source_filter: str = "", limit: int = 20,
                       type_filter: str = "", theme_filter: str = "") -> str:
    """Search icons and assets by keyword. Use list_asset_sources to see available sources.
    Multiple keywords can be space-separated (e.g. "lambda s3 dynamodb").

    Args:
        query: Search keywords, space-separated for multiple queries.
        source_filter: Filter by source name (e.g. "aws", "material").
        limit: Maximum results per keyword.
        type_filter: Filter by type (e.g. "Architecture-Service").
        theme_filter: Filter by theme ("dark" or "light").

    Returns:
        JSON with matching assets.
    """
    return json.dumps(
        assets.search_assets(
            query=query, storage=_storage, source_filter=source_filter, limit=limit,
            type_filter=type_filter, theme_filter=theme_filter,
        ),
    )


@mcp.tool()
def list_asset_sources() -> str:
    """List available asset sources with counts.

    Returns:
        JSON with list of sources.
    """
    return json.dumps(
        assets.list_asset_sources(storage=_storage),
    )


# --- Reference Tools ---


@mcp.tool()
def list_styles() -> str:
    """List available design styles (examples + user styles).

    Workflow equivalent: ``examples styles``

    Returns:
        JSON with list of styles (name, description, scope).
    """
    try:
        user_id = _get_user_id()
    except Exception:
        user_id = ""
    return json.dumps(
        reference.list_styles(storage=_storage, user_id=user_id or None),
        ensure_ascii=False,
    )


@mcp.tool()
def apply_style(deck_id: str, style: str, scope: str = "examples") -> str:
    """Copy a style as the deck's art direction. Call during Art Direction phase.

    Args:
        deck_id: Deck ID.
        style: Style name from list_styles (e.g. "elegant-dark").
        scope: "examples" (default) or "user".

    Returns:
        JSON confirmation.
    """
    _check_deck_access(deck_id)
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", style):
        raise ValueError("Invalid style name")
    if scope not in ("examples", "user"):
        raise ValueError("Invalid scope")
    if scope == "user":
        from shared.resources import resource_s3_key
        user_id = _get_user_id()
        html_key = resource_s3_key("user", user_id, "styles", style)
    else:
        html_key = f"references/examples/styles/{style}.html"
    html_bytes = _storage.download_file_from_pptx_bucket(key=html_key) if scope == "user" \
        else _storage.download_file(key=html_key)
    dest_key = f"decks/{deck_id}/specs/art-direction.html"
    _storage.upload_file(key=dest_key, data=html_bytes, content_type="text/html")
    return json.dumps({"applied": style, "scope": scope, "path": "specs/art-direction.html"})


@mcp.tool()
def save_user_style(name: str, description: str, html: str) -> str:
    """Save (create or update) a user-scoped style.

    Use at the end of the create-style workflow to persist the HTML
    as the current user's personal style.

    Args:
        name: Style name (alphanumeric/dash/underscore, 1-64 chars).
        description: Short description.
        html: Full style HTML.

    Returns:
        JSON with saved style info.
    """
    from tools import user_resources as _ur
    user_id = _get_user_id()
    return json.dumps(
        _ur.save_user_style(
            name=name, description=description, html=html,
            user_id=user_id, storage=_storage,
        ),
        ensure_ascii=False,
    )


@mcp.tool()
def read_examples(names: list[str]) -> str:
    """Read design examples (components/patterns).
    Without page specifier returns a listing of slide descriptions.
    With page specifier returns full content.

    Workflow equivalent: ``examples {name}``

    Examples:
        read_examples(["patterns"]) → listing with page numbers
        read_examples(["patterns/3"]) → full content of page 3
        read_examples(["components/all"]) → all component pages

    Args:
        names: Example names, e.g. ["patterns", "patterns/3", "components/all"].

    Returns:
        JSON with document contents.
    """
    return json.dumps(reference.read_examples(names=names, storage=_storage), ensure_ascii=False)


@mcp.tool()
def list_workflows() -> str:
    """List all available workflow documents (phase-by-phase instructions).

    Returns:
        JSON with list of workflows.
    """
    return json.dumps(reference.list_workflows(storage=_storage), ensure_ascii=False)


@mcp.tool()
def read_workflows(names: list[str]) -> str:
    """Read one or more workflow documents. Use list_workflows first to find names.

    Args:
        names: Workflow names, e.g. ["create-new-2-compose", "slide-json-spec"].

    Returns:
        JSON with document contents.
    """
    return json.dumps(reference.read_workflows(names=names, storage=_storage), ensure_ascii=False)


@mcp.tool()
def list_guides() -> str:
    """List all available guide documents (design rules, review checklists).

    Returns:
        JSON with list of guides.
    """
    return json.dumps(reference.list_guides(storage=_storage), ensure_ascii=False)


@mcp.tool()
def read_guides(names: list[str]) -> str:
    """Read one or more guide documents. Use list_guides first to find names.

    Args:
        names: Guide names, e.g. ["design-rules"].

    Returns:
        JSON with document contents.
    """
    return json.dumps(reference.read_guides(names=names, storage=_storage), ensure_ascii=False)


# --- Utility Tools ---


@mcp.tool()
def list_templates() -> str:
    """List all available templates with name and description.

    Returns:
        JSON with list of templates.
    """
    return json.dumps(
        template_mod.list_templates(storage=_storage),
    )


@mcp.tool()
def code_to_slide(deck_id: str, code: str, name: str,
                       language: str = "python", theme: str = "dark",
                       x: int = 0, y: int = 0,
                       width: int = 800, height: int = 300) -> str:
    """Generate syntax-highlighted code block and save as include file in S3.
    Returns the include path to use in presentation.json:
    {"type": "include", "src": "<returned include_path>"}

    Args:
        deck_id: The deck ID (for S3 path).
        code: Source code text.
        name: Include file name (without extension, e.g. "code-1").
        language: Programming language for syntax highlighting.
        theme: Color theme ("dark" or "light").
        x: X position in pixels.
        y: Y position in pixels.
        width: Width in pixels.
        height: Height in pixels.

    Returns:
        JSON with include_path for use in presentation.json.
    """
    _check_deck_access(deck_id, action="edit_slide")
    return json.dumps(
        code_block_mod.code_block_to_include(
            deck_id=deck_id, code=code, name=name, storage=_storage,
            language=language, theme=theme,
            x=x, y=y, width=width, height=height,
        ),
    )


# --- Code Execution (Code Interpreter) ---


@mcp.tool()
def run_python(code: str, deck_id: str | None = None, save: bool = False,
               files: list[str] | None = None, measure_slides: list[int] | None = None,
               purpose: str = "") -> str:
    """Execute Python code in a secure sandbox.

    Use this tool to edit the deck workspace or for general computation.

    If deck_id is provided, the entire deck workspace is loaded as files:
        presentation.json   — slide data (read/write via json.load/json.dump)
        specs/brief.md     — briefing document
        specs/art-direction.html — design direction (HTML)
        specs/outline.md    — slide outline (1 line = 1 slide = 1 message)
        includes/           — code block JSON files (created by code_to_slide)

    All files are accessible via normal file I/O (open, read, write).
    If save=True, all modified/new workspace files are written back to S3.

    **Always specify measure_slides when editing slides.** Runs validation after
    code execution (requires deck_id):
        - Text bbox measurement (overflow detection via LibreOffice SVG)
        - Lint diagnostics (JSON schema validation)
        - Layout bias detection
    Pass the 1-based slide numbers you edited, e.g. measure_slides=[3, 5].

    If files are provided (S3 keys), they are downloaded and available by filename.
    Supported: text files (CSV, JSON, TXT, Markdown, Python). Binary files are not supported.
    Example: files=["uploads/tmp/user/abc/data.csv"] → accessible as "data.csv" in code.

    Examples:
        Edit slides:   run_python(code="...", deck_id="abc", save=True, measure_slides=[3, 5])
        Edit specs:    run_python(code="open('specs/brief.md','w').write('...')", deck_id="abc", save=True)
        Measure only:  run_python(code="print('ok')", deck_id="abc", measure_slides=[1, 2])
        Compute:       run_python(code="print(2**100)")
        CSV:           run_python(code="import pandas as pd; print(pd.read_csv('data.csv'))",
                                  files=["uploads/tmp/user/x/data.csv"])

    Args:
        code: Python code to execute.
        deck_id: Deck ID to load workspace from. Optional.
        save: If True, save modified workspace files back to S3. Requires deck_id.
        files: S3 keys of files to make available in the sandbox. Optional.
        measure_slides: List of 1-based slide numbers to measure after execution. Requires deck_id.
        purpose: Brief user-facing description of what this code does,
            written in the user's language (e.g. 'Analyzing slide structure',
            'Adding 3 comparison slides'). Shown in the UI.

    Returns:
        JSON string: {"output", "measure"?, "errors"?, "warnings"?}
    """
    if measure_slides and not deck_id:
        return json.dumps({"error": "measure_slides requires deck_id"})
    if deck_id:
        _check_deck_access(deck_id, action="edit_slide" if save else "read")

    output = sandbox_mod.execute_in_sandbox(
        code=code,
        storage=_storage,
        region=_region,
        deck_id=deck_id,
        save=save,
        files=files,
    )

    result: dict = {"output": output}

    # Post-processing: measure_slides triggers PPTX build → measure/lint/bias
    if deck_id and (measure_slides or save):
        import shutil
        import traceback

        try:
            from tools.generate import _prepare_workspace

            user_id = _get_user_id()
            tmpdir, slides, build_kwargs = _prepare_workspace(deck_id, user_id, _storage)
            pptx_path = _build_pptx(tmpdir, slides, build_kwargs)

            # Measure (runs SVG export internally)
            if measure_slides:
                try:
                    result["measure"] = _run_measure(tmpdir, pptx_path, measure_slides)
                except Exception as e:
                    result["measure"] = json.dumps({"error": str(e)})

            # Lint (filter to measured slides; lint uses 0-based index)
            if measure_slides:
                try:
                    from sdpm.schema.lint import lint as lint_slides
                    presentation = json.loads((tmpdir / "presentation.json").read_text(encoding="utf-8"))
                    slide_set = set(measure_slides)
                    lint_diag = [d for d in lint_slides(presentation) if d.get("slide") + 1 in slide_set]
                    if lint_diag:
                        result["errors"] = {"lintDiagnostics": lint_diag}
                except Exception as e:
                    logger.warning("Lint failed: %s", e)

                # Layout bias (filter to measured slides; bias uses 1-based)
                try:
                    from sdpm.preview import check_layout_imbalance_data
                    layout_bias = [b for b in check_layout_imbalance_data(pptx_path, slide_defs=slides) if b.get("slide") in slide_set]
                    if layout_bias:
                        result["warnings"] = {"layoutBias": layout_bias}
                except Exception as e:
                    logger.warning("Layout bias check failed: %s", e)

            if save:
                # Compose: SVG → optimized JSON for WebUI animation
                # Runs synchronously — measured at ~300ms for 8 slides (≪3s threshold)
                try:
                    from tools.compose import extract_optimized_defs, split_slide_components, count_slides
                    import hashlib as _hashlib
                    svg_path = tmpdir / "measure.svg"
                    if not svg_path.exists():
                        _export_svg(tmpdir, pptx_path)
                    if svg_path.exists():
                        import json as _json
                        import time as _time
                        _epoch = int(_time.time())
                        compose_prefix = f"decks/{deck_id}/compose/"

                        # 1. List old compose keys (for cleanup + prev data)
                        old_keys = _storage.list_files(prefix=compose_prefix, bucket=_storage.pptx_bucket)

                        # 2. Load previous slide compose data keyed by sourceHash + slot number
                        prev_by_hash: dict[str, list[dict]] = {}
                        prev_by_slot: list[list[dict]] = []  # ordered by slide number
                        prev_slot_map: dict[int, list[dict]] = {}
                        import re as _re
                        for k in old_keys:
                            if "/slide_" not in k:
                                continue
                            try:
                                raw = _storage.download_file_from_pptx_bucket(k)
                                prev_data = _json.loads(raw)
                                comps = prev_data.get("components", [])
                                h = prev_data.get("sourceHash")
                                if h:
                                    prev_by_hash[h] = comps
                                # Extract slot number from key: slide_{N}_{epoch}.json
                                m = _re.search(r"/slide_(\d+)_", k)
                                if m:
                                    prev_slot_map[int(m.group(1))] = comps
                            except Exception:
                                pass
                        # Build ordered list
                        if prev_slot_map:
                            max_slot = max(prev_slot_map.keys())
                            prev_by_slot = [prev_slot_map.get(i, []) for i in range(1, max_slot + 1)]

                        # 3. Upload defs
                        defs_data = extract_optimized_defs(svg_path)
                        _storage.upload_file(
                            key=f"{compose_prefix}defs_{_epoch}.json",
                            data=_json.dumps(defs_data, ensure_ascii=False).encode(),
                            content_type="application/json",
                        )

                        # 4. Generate compose for all slides with changed flags
                        _total = count_slides(svg_path)
                        for sn in range(1, _total + 1):
                            try:
                                comp_data = split_slide_components(svg_path, sn)
                                # sourceHash from slide JSON
                                src_hash = ""
                                if sn <= len(slides):
                                    src_hash = _hashlib.md5(_json.dumps(slides[sn - 1], sort_keys=True, ensure_ascii=False).encode(), usedforsecurity=False).hexdigest()
                                comp_data["sourceHash"] = src_hash

                                # Diff: find prev slide by sourceHash, fallback to same slot number
                                prev_comps = prev_by_hash.get(src_hash)
                                if prev_comps is None and sn <= len(prev_by_slot):
                                    prev_comps = prev_by_slot[sn - 1]
                                if prev_comps is not None:
                                    # Component-level diff
                                    def _mk(c: dict) -> str:
                                        b = c.get("bbox")
                                        return f"{c['class']}|{b['x']},{b['y']},{b['w']},{b['h']}" if b else f"{c['class']}|none"
                                    def _fp(c: dict) -> str:
                                        return f"{c['class']}|{c.get('text', '')}"
                                    prev_map = {_mk(c): _fp(c) for c in prev_comps}
                                    for c in comp_data["components"]:
                                        k = _mk(c)
                                        c["changed"] = k not in prev_map or prev_map[k] != _fp(c)
                                else:
                                    for c in comp_data["components"]:
                                        c["changed"] = True

                                _storage.upload_file(
                                    key=f"{compose_prefix}slide_{sn}_{_epoch}.json",
                                    data=_json.dumps(comp_data, ensure_ascii=False).encode(),
                                    content_type="application/json",
                                )
                            except Exception:
                                logger.error("compose failed for slide %d", sn, exc_info=True)

                        # 5. Cleanup old compose files
                        for k in old_keys:
                            try:
                                _storage._s3.delete_object(Bucket=_storage.pptx_bucket, Key=k)
                            except Exception:
                                pass
                except Exception:
                    logger.error("compose failed", exc_info=True)

                # tmpdir cleanup (WebP generation only in generate_pptx)
                shutil.rmtree(tmpdir, ignore_errors=True)
            else:
                shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception as e:
            logger.exception("run_python post-processing failed: deck=%s", deck_id)
            result["measure"] = json.dumps({"error": str(e), "traceback": traceback.format_exc()})

    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def grid(spec: str, purpose: str = "") -> str:
    """Compute CSS Grid layout coordinates from a grid specification.
    Use before placing elements to calculate exact positions.

    Args:
        spec: JSON string with grid spec. Keys:
            area: {"x", "y", "w", "h"} (required)
            columns: track-list string, e.g. "1fr 2fr" (default "1fr")
            rows: track-list string (default "1fr")
            gap: str or int, e.g. "20" or "20 40" (row-gap col-gap)
            areas: 2D list of area names (optional)
            items: dict of item overrides (optional)
        purpose: Brief user-facing description (e.g. '3-column icon layout').
            Shown in the UI.

    Returns:
        JSON with named rectangles containing x, y, w, h coordinates.
    """
    from sdpm.layout.grid import compute_grid

    try:
        grid_spec = json.loads(spec)
    except (json.JSONDecodeError, TypeError) as e:
        return json.dumps({"error": f"Invalid grid spec JSON: {e}"})
    result = compute_grid(grid_spec)
    return json.dumps(result, ensure_ascii=False, indent=2)


# --- Search + KB Sync (optional, requires KB) ---

_kb_sync = None

if _kb_ssm_param and _vector_bucket_name:
    # Resolve KB ID from SSM at startup
    try:
        _ssm_client = boto3.client("ssm", region_name=_region)
        _kb_id = _ssm_client.get_parameter(Name=_kb_ssm_param)["Parameter"]["Value"]
    except Exception as e:
        logger.warning("Could not resolve KB ID from SSM %s: %s", _kb_ssm_param, e)
        _kb_id = ""

if _kb_id and _vector_bucket_name and _vector_index_name:
    from tools.kb_sync import KBSync  # noqa: E402

    _kb_sync = KBSync(
        kb_id=_kb_id,
        vector_bucket_name=_vector_bucket_name,
        vector_index_name=_vector_index_name,
        region=_region,
    )

    @mcp.tool()
    def search_slides(
        query: str,
        scope: str = "mine",
        deck_name: str = "",
        layout: str = "",
        days: int = 0,
    ) -> str:
        """Search existing slides by semantic similarity.

        Args:
            query: Natural language search query.
            scope: "mine" for own slides, "public" for public, "all" for both.
            deck_name: Partial match filter on deck name.
            layout: Exact match filter on layout type.
            days: Date range (0=all time, 30=last 30 days).

        Returns:
            JSON with matching slides.
        """
        assert _kb_sync is not None
        results = _kb_sync.search(
            query=query,
            user_id=_get_user_id(),
            scope=scope,
            deck_name=deck_name,
            layout=layout,
            days=days,
        )
        return json.dumps({"results": results}, ensure_ascii=False)


if __name__ == "__main__":
    import uvicorn  # noqa: E402
    app = mcp.streamable_http_app()
    app.add_middleware(_CaptureHeadersMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=8000)
