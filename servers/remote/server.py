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
import time
from contextvars import ContextVar
from pathlib import Path

# Add sdpm/ (skill root) to sys.path so the engine is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "sdpm"))

import boto3  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from shared.authz import authorize  # noqa: E402
from storage.aws import AwsStorage  # noqa: E402
from tools import assets, reference, preview, generate  # noqa: E402
from tools import sandbox as sandbox_mod  # noqa: E402
from tools import template as template_mod  # noqa: E402
from tools import init as init_mod  # noqa: E402
from tools import code_block as code_block_mod  # noqa: E402

from sdpm import tools as contract  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("sdpm.mcp")

# --- MCP Server Instructions ---
#
# DELIBERATE DIVERGENCE from sdpm.tools.instructions (do not "unify"):
# the shared instructions are an interactive workflow menu (choose A-D)
# for human-driven MCP clients. On Cloud, the client is the L4 agent —
# mode behavior arrives through its prompt (personas via
# start_presentation), so the menu would only waste tokens and conflict
# with the already-loaded persona. This short version states just the
# architecture split (run_python vs MCP tools) and the entry workflow.
# Design note: "Local = shared contract instructions, Remote = this
# agent-facing short form" (v0.5 review round 3).

_INSTRUCTIONS = """spec-driven-presentation-maker: AI-powered PowerPoint generation from JSON.

## Architecture
- The agent edits workspace files via `run_python(deck_id=...)` using normal file I/O (writes always persist)
- MCP tools handle: workflow guidance, initialization, PPTX generation, preview, references
- MCP tools do NOT handle: slide editing, spec writing (agent responsibility via run_python)

**Critical constraint:** Do NOT make any decisions about slide structure, content, design, or layout before loading the workflow. The workflow files contain the full process including briefing, outline, and art direction. Wait until the workflow is loaded and follow it step by step.

## Workflow: New Presentation

→ Read `read_workflows(["create-new-1-briefing"])` to start. Follow each file's Next Step from there.
"""

# Edit-existing-PPTX flow on Cloud is driven by read_attachment returning
# guide/guideInstruction in the response header — the spec agent follows
# that pointer instead of a hard-coded workflow name here.
#
# TODO: Add these workflows when web UI supports them
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
def analyze_template(template: str, deck_id: str = "") -> str:
    """Get pre-analyzed template information — layouts, theme colors, fonts.
    Call this to understand what layouts are available before building slides.

    Args:
        template: Template name from list_templates, a legacy "template.pptx",
            or `attachments/imports/{importKey}/deck/template.pptx` from import_attachment.
        deck_id: Required for either deck-owned template form.

    Returns:
        JSON with layouts, theme colors, and font information.
    """
    if not template or not template.strip():
        return json.dumps({"error": "template is required"})

    # Analyze either a legacy deck-root template or a new immutable bundle template.
    if template == "template.pptx" or template.startswith("attachments/imports/"):
        if not deck_id:
            return json.dumps({"error": "deck_id is required for a deck-owned template"})
        if ".." in template.split("/") or (
            template != "template.pptx" and not template.endswith("/deck/template.pptx")
        ):
            return json.dumps({"error": "invalid deck template path"})
        try:
            import tempfile
            from pathlib import Path
            from sdpm.engine.analyzer import analyze_template as _analyze
            template_key = template
            data = _storage.download_file_from_pptx_bucket(f"decks/{deck_id}/{template_key}")
            # TemporaryDirectory (not mkdtemp): this server is long-running,
            # leaked tmpdirs would accumulate. The analysis dict holds no
            # file references, so cleanup on exit is safe.
            with tempfile.TemporaryDirectory() as tmpdir:
                tpl_path = Path(tmpdir) / "template.pptx"
                tpl_path.write_bytes(data)
                analysis = _analyze(tpl_path)
            analysis["templateName"] = template
            return json.dumps(analysis, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"Failed to analyze deck-local template: {e}"})

    return json.dumps(
        template_mod.analyze_template(template_name=template, storage=_storage, user_id=_get_user_id()),
        ensure_ascii=False,
    )


# --- Attachment Tools ---


@mcp.tool()
def read_attachment(source: str, offset: int = 0, limit: int = 10240) -> dict:
    """Read the content of an attached file (text projection with paging).

    Stateless: no conversion state is stored. The file is converted on each call
    (with transparent caching for performance). Works before deck creation —
    no deck_id required.

    Args:
        source: S3 key (`uploads/{userId}/{uuid}/{name}`) from the
            [Attached:...] marker, or an HTTPS URL.
        offset: Starting byte offset in the canonical text projection (0-based).
        limit: Maximum bytes to return (default/max 10240, min 512).

    Returns:
        Text content with line numbers and structured JSON header containing
        source, fileName, mediaType, page metadata, and optional guide hints.
    """
    from tools.attachment import read_attachment as _read

    return _read(
        source=source,
        user_id=_get_user_id(),
        storage=_storage,
        offset=offset,
        limit=limit,
    )


@mcp.tool()
def import_attachment(source: str, deck_id: str, filename: str = "") -> str:
    """Import a file into the deck workspace for use in slides.

    source is an S3 key (`uploads/{userId}/{uuid}/{name}`) from the
    [Attached:...] marker, or an HTTPS URL. Converts and commits an
    immutable bundle into the deck's attachments directory.

    Args:
        source: S3 key from [Attached:...] message, or an HTTP(S) URL.
        deck_id: The deck ID (must be initialized via init_presentation).
        filename: Optional output filename. If omitted, derived from source.

    Returns:
        JSON with saved file paths and image_mapping for use in slide JSON.
    """
    from tools.attachment import import_attachment as _import

    _check_deck_access(deck_id, action="edit_slide")
    return _import(
        source=source,
        deck_id=deck_id,
        user_id=_get_user_id(),
        storage=_storage,
        filename=filename,
    )



# --- Generation Tools ---


@mcp.tool()
def generate_pptx(deck_id: str) -> str:
    """Generate final PPTX — the explicit finalize/handoff step.

    The PPTX artifact already refreshes automatically when the deck changes
    (run_python post-processing); this tool additionally produces the WebP
    preview set, syncs the knowledge base, and returns a full-deck warnings
    report. Resolves include references automatically.

    Args:
        deck_id: The deck ID to generate PPTX from.

    Returns:
        JSON with status, slideCount, slides summary, and optional warnings.
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
def get_preview(deck_id: str, slugs: list[str], quality: str = "high") -> list:
    """Get PNG preview images for visual review by the agent.

    Returns actual slide images that the model can see and analyze.
    Available after generate_pptx completes.

    - quality="low" (800px): Review all slides at once — check flow, structure, design consistency.
    - quality="high" (1280px): Precise review of specific slides — check text, layout details.

    Args:
        deck_id: The deck ID.
        slugs: List of slide slugs to preview (required, at least one). Example: ["intro", "pricing"].
        quality: "low" (800px, ~480 tokens/slide) or "high" (1280px, ~1229 tokens/slide).

    Returns:
        List of text labels and slide images for visual inspection.
    """
    _check_deck_access(deck_id, action="preview")
    if not slugs:
        return [{"type": "text", "text": "Error: slugs must not be empty"}]
    if quality not in ("low", "high"):
        quality = "high"
    try:
        return preview.get_preview(
            deck_id=deck_id, slugs=slugs, storage=_storage, quality=quality,
        )
    except _storage._s3.exceptions.NoSuchKey:
        return [{"type": "text", "text": f"Preview not available yet. Run generate_pptx(deck_id=\"{deck_id}\") first."}]
    except Exception as e:
        if "NoSuchKey" in str(e):
            return [{"type": "text", "text": f"Preview not available yet. Run generate_pptx(deck_id=\"{deck_id}\") first."}]
        raise


def _build_pptx(tmpdir: Path, slides: list[dict], build_kwargs: dict) -> tuple[Path, list[dict]]:
    """Build PPTX from slides JSON. Returns (pptx_path, invalid_layouts)."""
    from sdpm.engine.builder import PPTXBuilder, resolve_override

    builder = PPTXBuilder(**build_kwargs)
    id_map: dict[str, dict] = {}
    for s in slides:
        if "id" in s:
            id_map[s["id"]] = s
    for s in slides:
        builder.add_slide(resolve_override(s, id_map))
    pptx_path = tmpdir / "measure.pptx"
    builder.save(pptx_path)
    return pptx_path, list(builder.invalid_layouts)


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


def _run_measure(tmpdir: Path, pptx_path: Path, slide_numbers: list[int],
                 page_to_slug: dict[int, str] | None = None) -> str:
    """PPTX → SVG → bbox measurement → report string."""
    from sdpm.engine.preview.measure import measure_from_svg, format_measure_report

    svg_path = _export_svg(tmpdir, pptx_path)
    if not svg_path.exists():
        return json.dumps({"error": "LibreOffice SVG export failed"})

    results = measure_from_svg(svg_path=svg_path, slide_indices=slide_numbers)
    return format_measure_report(results, page_to_slug=page_to_slug)


# --- Asset Tools ---


@mcp.tool()
def search_assets(query: str = "", source_filter: str = "", limit: int = 20,
                       type_filter: str = "", theme_filter: str = "") -> str:
    """Search icons and assets by keyword, or discover available sources.

    Discovery mode: call with query="" (empty string) to get a listing of all
    available asset sources with their item counts.
    Multiple keywords can be space-separated (e.g. "lambda s3 dynamodb").

    Args:
        query: Search keywords, space-separated. Empty string triggers discovery mode.
        source_filter: Filter by source name (e.g. "aws", "material").
        limit: Maximum results per keyword.
        type_filter: Filter by type (e.g. "Architecture-Service").
        theme_filter: Filter by theme ("dark" or "light").

    Returns:
        JSON with matching assets, or sources list in discovery mode.
    """
    return json.dumps(
        assets.search_assets(
            query=query, storage=_storage, source_filter=source_filter, limit=limit,
            type_filter=type_filter, theme_filter=theme_filter,
        ),
    )



# --- Reference Tools ---


@mcp.tool()
def list_styles(include_all: bool = False) -> str:
    """List available design styles for presentations.

    Default returns pinned + user styles only. Pass include_all=True for all.

    Returns:
        JSON with list of styles (name, description, pinned, source).
    """
    user_id = _get_user_id()
    return json.dumps(
        reference.list_styles(storage=_storage, user_id=user_id, include_all=include_all),
        ensure_ascii=False,
    )


@mcp.tool()
def apply_style(deck_id: str, style: str) -> str:
    """Copy a style as the deck's art direction. Call during Art Direction phase.

    Searches user styles first, then builtin styles.

    Args:
        deck_id: Deck ID.
        style: Style name from list_styles (e.g. "elegant-dark").

    Returns:
        JSON confirmation.
    """
    _check_deck_access(deck_id)
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", style):
        raise ValueError("Invalid style name")

    user_id = _get_user_id()
    html_bytes = None

    # Try user style first
    user_key = f"user-styles/{user_id}/{style}.html"
    try:
        html_bytes = _storage.download_file_from_pptx_bucket(key=user_key)
    except Exception:
        pass

    # Fall back to builtin (bundled in the image)
    if html_bytes is None:
        from sdpm.knowledge.reference import BUNDLED_STYLES_DIR
        builtin_path = BUNDLED_STYLES_DIR / f"{style}.html"
        if not builtin_path.exists():
            raise FileNotFoundError(f"Style not found: {style}")
        html_bytes = builtin_path.read_bytes()

    dest_key = f"decks/{deck_id}/specs/art-direction.html"
    _storage.upload_file(key=dest_key, data=html_bytes, content_type="text/html")
    return json.dumps({"applied": style, "path": "specs/art-direction.html"})


# --- Reference tools (bound from the shared contract; bundled data baked into the image) ---

mcp.tool()(contract.start_presentation)
mcp.tool()(contract.read_examples)
mcp.tool()(contract.list_workflows)
mcp.tool()(contract.read_workflows)
mcp.tool()(contract.list_guides)
mcp.tool()(contract.read_guides)


# --- Utility Tools ---


@mcp.tool()
def list_templates() -> str:
    """List all available templates with name, source, and description.

    Returns:
        JSON with list of templates.
    """
    return json.dumps(
        template_mod.list_templates(storage=_storage, user_id=_get_user_id()),
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


def _build_relevant(p: str) -> bool:
    """True if a workspace path affects the built PPTX artifact."""
    return (
        p in ("deck.json", "presentation.json", "specs/outline.md")
        or p.startswith(("slides/", "includes/"))
    )


def _post_processing_plan(deck_changed: bool,
                          measure_slides: list[str] | None) -> dict[str, bool]:
    """Decide run_python post-processing actions (the unified contract).

    - build:    cheap python-pptx build — prerequisite for both the artifact
                refresh and the verification pass
    - artifact: refresh the deck's PPTX artifact (follows deck changes
                automatically; failure must surface in the result)
    - verify:   expensive verification (measure / SVG compose / preview) —
                triggered by measure_slides and ONLY by measure_slides

    Contract matrix (pinned by tests/test_run_python_semantics.py):
        changed=False, measure=None → nothing
        changed=True,  measure=None → build + artifact only
        changed=False, measure=[..] → build + verify only
        changed=True,  measure=[..] → build + artifact + verify
    """
    return {
        "build": bool(deck_changed or measure_slides),
        "artifact": bool(deck_changed),
        "verify": bool(measure_slides),
    }


@mcp.tool()
def run_python(purpose: str, code: str, deck_id: str | None = None,
               measure_slides: list[str] | None = None) -> str:
    """Execute Python code in a secure sandbox.

    Use this tool to edit the deck workspace or for general computation.

    If deck_id is provided, the entire deck workspace is loaded as files:
        deck.json           — deck metadata (template, fonts, defaultTextColor)
        slides/{slug}.json  — per-slide data
        specs/brief.md      — briefing document
        specs/art-direction.html — design direction (HTML)
        specs/outline.md    — slide outline (1 line = 1 slide = 1 message)
        includes/           — code block JSON files (created by code_to_slide)
        attachments/        — imported files (CSV, JSON, Markdown) via import_attachment

    Legacy decks with presentation.json are also supported (read-only compat).

    ## Sandbox helpers (preferred — identical API on Local and Cloud)

        read_json(path)          → dict/list   Read a JSON file
        write_json(path, data)   → None        Write data as JSON
        read_text(path)          → str         Read a text file
        write_text(path, text)   → None        Write a text file
        list_files(subdir=".")   → list[str]   List filenames in a subdirectory

    All paths are relative to the deck root. The helpers are injected
    automatically — do NOT write `from _sdpm_helpers import ...` yourself;
    the import is prepended by the sandbox. Using the helpers keeps the
    same code portable between Local (AST-restricted) and Cloud.

    Raw `open()` / `json.load` still work on Cloud for backward compat,
    but new code should prefer the helpers.

    ## Persistence & build (no flags needed)

    - File writes always persist — modified/new workspace files are written
      back to S3 after every execution. There is no "unsaved" state.
      (If you only have read access to the deck, writes are discarded and
      the result notes it.)
    - The deck's PPTX artifact refreshes automatically whenever the deck
      changed (deck.json / slides/ / includes/ / specs/outline.md).
    - measure_slides triggers the expensive verification pass (render + text
      overflow measurement + live-preview compose) for the given slugs only.

    **Always specify measure_slides when editing slides.** Runs validation after
    code execution (requires deck_id):
        - Text bbox measurement (overflow detection via LibreOffice SVG)
        - Lint diagnostics (JSON schema validation)
        - Layout bias detection
    Pass the slugs of slides you edited, e.g. measure_slides=["title", "feature-a"].

    Examples:
        Edit slide:
            data = read_json("slides/title.json")
            data["elements"][0]["text"] = "New Title"
            write_json("slides/title.json", data)
            # run_python(code=<above>, deck_id="abc", measure_slides=["title"])

        Edit spec:
            write_text("specs/brief.md", "# Brief\\n\\nContents...")
            # run_python(code=<above>, deck_id="abc")

        Read deck metadata:
            deck = read_json("deck.json")
            print(deck.get("template"))

        List slide files:
            print(list_files("slides"))

        General computation (no deck_id):
            print(2 ** 100)

    Args:
        code: Python code to execute.
        deck_id: Deck ID to load workspace from. Optional.
        measure_slides: List of slide slugs to measure after execution. Requires deck_id.
        purpose: Brief user-facing description of what this code does,
            written in the user's language (e.g. 'Analyzing slide structure',
            'Adding 3 comparison slides'). Shown in the UI.

    Returns:
        JSON string: {"output", "measure"?, "errors"?, "warnings"?}
    """
    if measure_slides and not deck_id:
        return json.dumps({"error": "measure_slides requires deck_id"})

    result: dict = {}

    # Writes persist by default. If the user only has read access, run the
    # sandbox without write-back instead of failing (read-only analysis).
    persist_writes = True
    if deck_id:
        try:
            _check_deck_access(deck_id, action="edit_slide")
        except ValueError:
            _check_deck_access(deck_id, action="read")
            persist_writes = False
            result["readOnly"] = (
                "You have read-only access to this deck: file writes were "
                "not persisted."
            )

    output, outline_warnings, lint_diagnostics, changed_paths = sandbox_mod.execute_in_sandbox(
        code=code,
        storage=_storage,
        region=_region,
        deck_id=deck_id,
        persist_writes=persist_writes,
    )

    result["output"] = output

    if outline_warnings:
        result.setdefault("warnings", {})["outline"] = (
            "outline.md format violation. "
            "Read workflow `create-new-1-outline` for the correct format."
        )

    if lint_diagnostics:
        errs = result.setdefault("errors", {})
        errs["lintDiagnostics"] = lint_diagnostics

    # Post-processing: rebuild the PPTX artifact whenever build-relevant files
    # changed (the artifact follows the deck automatically); measure_slides
    # (and ONLY measure_slides) triggers the expensive verification pass.
    deck_changed = any(_build_relevant(p) for p in changed_paths)
    plan = _post_processing_plan(deck_changed, measure_slides)
    if deck_id and plan["build"]:
        import shutil
        import traceback

        try:
            from tools.generate import _prepare_workspace

            user_id = _get_user_id()
            _prepare_epoch = int(time.time())
            tmpdir, slides, build_kwargs = _prepare_workspace(deck_id, user_id, _storage)
            pptx_path, invalid_layouts = _build_pptx(tmpdir, slides, build_kwargs)
            invalid_slug_set = {e["slug"] for e in invalid_layouts if e.get("slug")}

            # Build slug → page number mapping
            slug_to_page: dict[str, int] = {}
            for i, s in enumerate(slides):
                sid = s.get("id", "")
                if sid:
                    slug_to_page[sid] = i + 1
            page_numbers = [slug_to_page[slug] for slug in (measure_slides or []) if slug in slug_to_page]
            page_to_slug = {v: k for k, v in slug_to_page.items()}

            if plan["verify"]:
                # Measure
                try:
                    if page_numbers:
                        measure_result = _run_measure(tmpdir, pptx_path, page_numbers, page_to_slug=page_to_slug)
                        result["measure"] = measure_result
                    else:
                        result["measure"] = json.dumps({"error": "No matching slides found for given slugs"})
                except Exception as e:
                    result["measure"] = json.dumps({"error": str(e)})

                # Layout bias (filter to measured slides; bias uses 1-based)
                try:
                    from sdpm.engine.preview import check_layout_imbalance_data
                    layout_bias = [b for b in check_layout_imbalance_data(pptx_path, slide_defs=slides) if b.get("slide") in set(page_numbers)]
                    if layout_bias:
                        result["warnings"] = {"layoutBias": layout_bias}
                except Exception as e:
                    logger.warning("Layout bias check failed: %s", e)

                # Invalid-layout errors scoped to measured slugs only. Each
                # composer owns a subset of slides, so leaking another group's
                # mistake would be noise (they cannot fix it anyway).
                measured_set = set(measure_slides or [])
                my_invalids = [e for e in invalid_layouts if e.get("slug") in measured_set]
                if my_invalids:
                    errs = result.setdefault("errors", {})
                    for e in my_invalids:
                        errs[e["slug"]] = {
                            "invalidLayout": e["attempted"],
                            "available": e["available"],
                        }

            if plan["artifact"]:
                # Refresh the download artifact — the deck's PPTX follows deck
                # changes automatically (same upload/record shape as
                # generate_pptx; WebP previews and KB sync stay with
                # generate_pptx, the explicit finalize/handoff step).
                # A failure here means the download artifact is STALE — that
                # must be visible to the caller, not just logged.
                _pptx_key = None
                try:
                    import uuid as _uuid
                    from datetime import datetime as _dt, timezone as _tz
                    _pptx_key = f"pptx/{deck_id}/{_uuid.uuid4()}.pptx"
                    _storage.upload_file(
                        key=_pptx_key,
                        data=Path(pptx_path).read_bytes(),
                        content_type=(
                            "application/vnd.openxmlformats-officedocument"
                            ".presentationml.presentation"
                        ),
                    )
                    _old = _storage.update_deck(
                        deck_id=deck_id, user_id=user_id,
                        updates={
                            "pptxS3Key": _pptx_key,
                            "updatedAt": _dt.now(_tz.utc).isoformat(),
                            "slideCount": len(slides),
                        },
                    )
                    # The record now points at the new artifact — delete the
                    # superseded one so auto-refresh doesn't accumulate
                    # orphaned PPTX objects (best effort; lifecycle rules
                    # are the backstop).
                    _old_key = (_old or {}).get("pptxS3Key")
                    if _old_key and _old_key != _pptx_key:
                        try:
                            _storage._s3.delete_object(
                                Bucket=_storage.pptx_bucket, Key=_old_key,
                            )
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning("PPTX artifact refresh failed: %s", e)
                    result["pptx_error"] = (
                        f"PPTX artifact refresh failed — the downloadable "
                        f"PPTX is stale. Run generate_pptx to refresh it. "
                        f"({e})"
                    )
                    if _pptx_key:
                        # The record update may have failed after the upload
                        # succeeded — delete the orphaned object (best effort).
                        try:
                            _storage._s3.delete_object(
                                Bucket=_storage.pptx_bucket, Key=_pptx_key,
                            )
                        except Exception:
                            pass

            if plan["verify"]:
                # Compose: SVG → optimized JSON for WebUI animation
                # Only generates compose for measure_slides slugs (parallel-safe).
                # Uses _prepare_epoch (snapshot time) so the composer with the
                # newest slides/ snapshot wins on defs via epoch comparison.
                try:
                    from tools.compose import extract_optimized_defs, split_slide_components
                    import hashlib as _hashlib
                    svg_path = tmpdir / "measure.svg"
                    if not svg_path.exists():
                        _export_svg(tmpdir, pptx_path)
                    if svg_path.exists():
                        import json as _json
                        import re as _re
                        compose_prefix = f"decks/{deck_id}/compose/"

                        # List existing compose keys (for prev data + cleanup)
                        old_keys = _storage.list_files(prefix=compose_prefix, bucket=_storage.pptx_bucket)

                        def _latest_key(prefix: str) -> str | None:
                            best_ep, best_k = -1, None
                            for k in old_keys:
                                if not k.startswith(prefix):
                                    continue
                                m = _re.search(r"_(\d+)\.json$", k)
                                ep = int(m.group(1)) if m else 0
                                if ep > best_ep:
                                    best_ep, best_k = ep, k
                            return best_k

                        # Component-level diff helpers
                        def _mk(c: dict) -> str:
                            b = c.get("bbox")
                            return f"{c['class']}|{b['x']},{b['y']},{b['w']},{b['h']}" if b else f"{c['class']}|none"

                        def _fp(c: dict) -> str:
                            return f"{c['class']}|{c.get('text', '')}"

                        # Determine which slugs to generate compose for
                        # Always include slugs that have no existing compose (migration + first build)
                        # Verify-gated: measure_slides is always set here
                        compose_slugs = set(measure_slides)
                        for s in slug_to_page:
                            if not _latest_key(f"{compose_prefix}{s}_"):
                                compose_slugs.add(s)

                        # Upload defs (prepare epoch — newest snapshot wins)
                        defs_data = extract_optimized_defs(svg_path)
                        _storage.upload_file(
                            key=f"{compose_prefix}defs_{_prepare_epoch}.json",
                            data=_json.dumps(defs_data, ensure_ascii=False).encode(),
                            content_type="application/json",
                        )
                        # Cleanup old defs (only delete defs older than our epoch)
                        # Also remove legacy slide_{N}_*.json files
                        for k in old_keys:
                            if "/defs_" in k:
                                m = _re.search(r"_(\d+)\.json$", k)
                                if m and int(m.group(1)) < _prepare_epoch:
                                    try:
                                        _storage._s3.delete_object(Bucket=_storage.pptx_bucket, Key=k)
                                    except Exception:
                                        pass
                            elif _re.search(r"/slide_\d+_\d+\.json$", k):
                                try:
                                    _storage._s3.delete_object(Bucket=_storage.pptx_bucket, Key=k)
                                except Exception:
                                    pass

                        # Generate compose for each measured slug
                        for slug in compose_slugs:
                            if slug in invalid_slug_set:
                                # Do not surface a fallback-rendered slide as a
                                # live-preview artifact. The composer for this
                                # slug will see the error and fix the layout.
                                continue
                            pn = slug_to_page.get(slug)
                            if not pn:
                                continue
                            try:
                                comp_data = split_slide_components(svg_path, pn)

                                # sourceHash from slide JSON (content-based diff)
                                src_hash = _hashlib.md5(
                                    _json.dumps(slides[pn - 1], sort_keys=True, ensure_ascii=False).encode(),
                                    usedforsecurity=False,
                                ).hexdigest() if pn <= len(slides) else ""
                                comp_data["sourceHash"] = src_hash

                                # Diff against previous compose for same slug
                                prev_key = _latest_key(f"{compose_prefix}{slug}_")
                                prev_comps = None
                                prev_hash = None
                                if prev_key:
                                    try:
                                        raw = _storage.download_file_from_pptx_bucket(prev_key)
                                        prev_data = _json.loads(raw)
                                        prev_comps = prev_data.get("components")
                                        prev_hash = prev_data.get("sourceHash")
                                    except Exception:
                                        pass

                                # If sourceHash unchanged, all components are unchanged
                                if prev_comps is not None and prev_hash == src_hash and src_hash:
                                    for c in comp_data["components"]:
                                        c["changed"] = False
                                elif prev_comps is not None:
                                    prev_map = {_mk(c): _fp(c) for c in prev_comps}
                                    for c in comp_data["components"]:
                                        k = _mk(c)
                                        c["changed"] = k not in prev_map or prev_map[k] != _fp(c)
                                else:
                                    for c in comp_data["components"]:
                                        c["changed"] = True

                                _storage.upload_file(
                                    key=f"{compose_prefix}{slug}_{_prepare_epoch}.json",
                                    data=_json.dumps(comp_data, ensure_ascii=False).encode(),
                                    content_type="application/json",
                                )

                                # Cleanup old compose for this slug only
                                for k in old_keys:
                                    if k.startswith(f"{compose_prefix}{slug}_") and not k.endswith(f"{slug}_{_prepare_epoch}.json"):
                                        try:
                                            _storage._s3.delete_object(Bucket=_storage.pptx_bucket, Key=k)
                                        except Exception:
                                            pass
                            except Exception:
                                logger.error("compose failed for slug %s", slug, exc_info=True)
                except Exception:
                    logger.error("compose failed", exc_info=True)

                # Preview: sync WebP generation so composer can immediately view
                # via get_preview(slugs=[...]) — lowers the barrier from a
                # 2-step (generate_pptx → get_preview) to 1-step feedback loop.
                if measure_slides:
                    try:
                        from tools.generate import generate_previews
                        preview_dir = tmpdir / "preview_out"
                        preview_dir.mkdir(exist_ok=True)
                        webp_files = generate_previews(pptx_path, preview_dir)
                        uploaded = []
                        for slug in measure_slides:
                            page = slug_to_page.get(slug)
                            if page and page <= len(webp_files):
                                _storage.upload_file(
                                    key=f"previews/{deck_id}/{slug}_{_prepare_epoch}.webp",
                                    data=webp_files[page - 1].read_bytes(),
                                    content_type="image/webp",
                                )
                                uploaded.append(slug)
                        if uploaded:
                            result["previewHint"] = (
                                f"Preview images generated for {', '.join(uploaded)}. "
                                f"Call get_preview(deck_id=\"{deck_id}\", slugs=[...]) to view."
                            )
                    except Exception:
                        logger.warning("preview generation failed", exc_info=True)

                # tmpdir cleanup (WebP generation only in generate_pptx)
                shutil.rmtree(tmpdir, ignore_errors=True)
            else:
                shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception as e:
            msg = str(e)
            # "No slides found" is expected during early phases (outline/brief
            # editing before any slide JSON exists). Silently skip measure.
            if "No slides found" in msg or "has no slides" in msg:
                pass
            else:
                logger.exception("run_python post-processing failed: deck=%s", deck_id)
                if plan["verify"]:
                    result["measure"] = json.dumps({"error": msg, "traceback": traceback.format_exc()})
                else:
                    result["pptx_error"] = (
                        f"PPTX build failed — the downloadable PPTX may be "
                        f"stale: {msg}"
                    )

    return json.dumps(result, ensure_ascii=False)


# --- Layout tools (bound from the shared contract) ---

mcp.tool()(contract.grid)
mcp.tool()(contract.arch_diagram)


# --- Style Execution (Code Interpreter) ---


@mcp.tool()
def run_style_python(purpose: str, code: str, style_name: str | None = None,
                     ref_styles: list[str] | None = None) -> str:
    """Execute Python code in a secure sandbox for style creation/editing.

    If style_name is provided, the style HTML is loaded as style.html.
    The code can read/write it via normal file I/O (open, read, write).
    Writes always persist — if style.html changed, it is written back to the
    user's style storage automatically. There is no "unsaved" state.

    If ref_styles are provided, they are downloaded and available as ref/{name}.html.
    Use list_styles to discover available style names.

    Import statements are allowed — PIL, colorsys, numpy, etc. are available
    for color computation, palette extraction, and contrast calculation.

    Workspace layout:
        style.html          — target style (read/write; persisted when changed)
        ref/{name}.html     — reference styles (read-only)

    Examples:
        Read reference:    run_style_python(code="html = open('ref/corporate-executive.html').read(); print(html[:200])",
                                           ref_styles=["corporate-executive"])
        Create new:        run_style_python(code="open('style.html','w').write('<html>...')",
                                           style_name="style-20260506-1430")
        Edit existing:     run_style_python(code="html = open('style.html').read(); html = html.replace('old','new'); open('style.html','w').write(html)",
                                           style_name="style-20260506-1430")
        Compute colors:    run_style_python(code="from colorsys import rgb_to_hls; print(rgb_to_hls(0.2, 0.4, 0.6))")

    Args:
        purpose: Brief user-facing description of what this code does,
            written in the user's language. Shown in the UI.
        code: Python code to execute.
        style_name: Style name to load as style.html. Optional.
        ref_styles: Style names to load as ref/{name}.html. Optional.

    Returns:
        JSON string: {"output", "saved"?}
    """
    user_id = _get_user_id()

    client = boto3.client("bedrock-agentcore", region_name=_region)
    session = client.start_code_interpreter_session(
        codeInterpreterIdentifier="aws.codeinterpreter.v1",
        name=f"style-{user_id[:8]}",
        sessionTimeoutSeconds=300,
    )
    session_id = session["sessionId"]

    try:
        file_contents: list[dict[str, str]] = []

        # Load target style (baseline for change detection)
        baseline_style: str | None = None
        if style_name:
            html = _load_style_html(user_id, style_name)
            if html:
                baseline_style = html
                file_contents.append({"path": "style.html", "text": html})

        # Load reference styles
        if ref_styles:
            for ref_name in ref_styles:
                ref_html = _load_style_html(user_id, ref_name)
                if ref_html:
                    file_contents.append({"path": f"ref/{ref_name}.html", "text": ref_html})

        # Ensure directories exist
        setup_code = "import os\nos.makedirs('ref', exist_ok=True)\n"
        client.invoke_code_interpreter(
            codeInterpreterIdentifier="aws.codeinterpreter.v1",
            sessionId=session_id, name="executeCode",
            arguments={"language": "python", "code": setup_code},
        )

        # Write files into sandbox
        if file_contents:
            client.invoke_code_interpreter(
                codeInterpreterIdentifier="aws.codeinterpreter.v1",
                sessionId=session_id, name="writeFiles",
                arguments={"content": file_contents},
            )

        # Execute user code
        response = client.invoke_code_interpreter(
            codeInterpreterIdentifier="aws.codeinterpreter.v1",
            sessionId=session_id, name="executeCode",
            arguments={"language": "python", "code": code},
        )
        output = sandbox_mod._collect_stream(response)

        result: dict = {"output": output}

        # Persist style.html when it changed (always — no "unsaved" state)
        if style_name:
            read_code = "import sys\ntry:\n    print(open('style.html').read())\nexcept FileNotFoundError:\n    print('__NOT_FOUND__')\n"
            read_resp = client.invoke_code_interpreter(
                codeInterpreterIdentifier="aws.codeinterpreter.v1",
                sessionId=session_id, name="executeCode",
                arguments={"language": "python", "code": read_code},
            )
            style_html = sandbox_mod._collect_stream(read_resp)
            if (
                style_html
                and style_html.strip() != "__NOT_FOUND__"
                # print() appends a newline — compare newline-insensitively
                and style_html.rstrip("\n") != (baseline_style or "").rstrip("\n")
            ):
                key = f"user-styles/{user_id}/{style_name}.html"
                _storage.upload_file(key=key, data=style_html.encode("utf-8"), content_type="text/html")
                result["saved"] = {"filename": f"{style_name}.html", "key": key}
        else:
            # No style_name → nothing can persist. If the code wrote
            # style.html anyway, that would be silent data loss — surface it.
            exists_resp = client.invoke_code_interpreter(
                codeInterpreterIdentifier="aws.codeinterpreter.v1",
                sessionId=session_id, name="executeCode",
                arguments={"language": "python",
                           "code": "import os\nprint(os.path.exists('style.html'))\n"},
            )
            if sandbox_mod._collect_stream(exists_resp).strip() == "True":
                result["warning"] = (
                    "style.html was written but no style_name was given — "
                    "it was NOT persisted. Re-run with style_name=<name>."
                )

        return json.dumps(result, ensure_ascii=False)

    finally:
        client.stop_code_interpreter_session(
            codeInterpreterIdentifier="aws.codeinterpreter.v1",
            sessionId=session_id,
        )


def _load_style_html(user_id: str, name: str) -> str | None:
    """Load style HTML from S3 (user styles first, then builtin)."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        return None
    # Try user style
    user_key = f"user-styles/{user_id}/{name}.html"
    try:
        return _storage.download_file_from_pptx_bucket(key=user_key).decode("utf-8")
    except Exception:
        pass
    # Try builtin
    builtin_key = f"references/examples/styles/{name}.html"
    try:
        return _storage.download_file(key=builtin_key).decode("utf-8")
    except Exception:
        pass
    return None


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
