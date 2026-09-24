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
import threading
import re
import sys
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Annotated

# Add sdpm/ (skill root) to sys.path so the engine is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "sdpm"))

import boto3  # noqa: E402
from pydantic import Field  # noqa: E402
from boto_config import LONG_CALL, SHORT_API  # noqa: E402
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
# Cloud clients already carry transport-specific wiring, so this entry stays
# shorter than the interactive local instructions.
_INSTRUCTIONS = """spec-driven-presentation-maker: AI-powered PowerPoint generation from JSON.

The agent edits deck files through `run_python`; MCP tools handle workflows,
initialization, generation, previews, and references.
To create or edit slides, call `start_presentation()` first; a composer calls
`start_composing(deck_id, assigned_slugs)` first.
"""

mcp = FastMCP(
    "spec-driven-presentation-maker",
    host="0.0.0.0",
    stateless_http=True,
    instructions=_INSTRUCTIONS,
)


def _run_in_background(target, *, name: str) -> None:
    """Start ``target`` on a daemon thread. Tests patch this to run inline."""
    threading.Thread(target=target, name=name, daemon=True).start()


# Background work that get_preview may need to wait for. Keyed by deck so a
# composer asking for previews right after run_python (same session, same
# process) blocks until its previews are on S3 instead of seeing a stale or
# missing image. Entries are removed when the task finishes.
_pending_previews: dict[str, set[threading.Event]] = {}
_pending_lock = threading.Lock()


def _register_pending_preview(deck_id: str) -> threading.Event:
    ev = threading.Event()
    with _pending_lock:
        _pending_previews.setdefault(deck_id, set()).add(ev)
    return ev


def _clear_pending_preview(deck_id: str, ev: threading.Event) -> None:
    ev.set()
    with _pending_lock:
        evs = _pending_previews.get(deck_id)
        if evs:
            evs.discard(ev)
            if not evs:
                _pending_previews.pop(deck_id, None)


def _wait_for_pending_previews(deck_id: str, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        with _pending_lock:
            evs = list(_pending_previews.get(deck_id, ()))
        if not evs:
            return
        for ev in evs:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning("get_preview: background previews for %s still running after %.0fs", deck_id, timeout)
                return
            ev.wait(remaining)


def offloaded_tool(fn):
    """Register ``fn`` as an MCP tool that runs in a worker thread.

    FastMCP calls synchronous tool functions directly on the event loop, so a
    tool that spends a minute in LibreOffice stalls every other request on
    this server — including AgentCore's ``/ping`` health check, which then
    marks the session unhealthy and terminates it mid-run. Offloading keeps
    the loop free. ``asyncio.to_thread`` copies the current contextvars, so
    the per-request headers (user id) remain visible inside the tool.

    The original function is returned unchanged so it stays callable (and
    testable) as a plain function.
    """
    import asyncio
    import functools
    import inspect

    async def _runner(**kwargs):
        return await asyncio.to_thread(functools.partial(fn, **kwargs))

    _runner.__name__ = fn.__name__
    _runner.__qualname__ = fn.__qualname__
    _runner.__doc__ = fn.__doc__
    _runner.__signature__ = inspect.signature(fn)  # FastMCP reads the schema from this
    _runner.__annotations__ = dict(getattr(fn, "__annotations__", {}))
    mcp.tool()(_runner)
    return fn

# --- HTTP Request ContextVar (for extracting user_id from Runtime header) ---
_current_request_headers: ContextVar[dict] = ContextVar("_current_request_headers", default={})


# --- LibreOffice warm-up per MCP session ---
#
# AgentCore Runtime platform V2 restores every microVM from a snapshot, and the
# restored root filesystem is lazily fetched: the first read of each file is
# slow (measured 2026-09-20: reading LibreOffice's 166 MB of .so took 2-16 s,
# the first `soffice --version` 13.5 s, the first conversion 20 s more — about
# 60 s in total; the second run 3 s). Warming before the snapshot does not help
# because the page cache is not restored. So the warm-up runs after restore:
# each MCP session maps to one microVM, and the session's `initialize` request
# (the only POST /mcp without an Mcp-Session-Id header) is the earliest moment
# we know the microVM is in use. One background conversion of a blank template
# touches exactly the files a real conversion needs, well before the composer
# reaches its first run_python.

_warmup_lock = threading.Lock()
_warmup_running = False
_warmup_last_done = 0.0
_WARMUP_MIN_INTERVAL_S = 300.0


def _soffice_warm_up() -> None:
    global _warmup_running, _warmup_last_done
    import shutil
    import subprocess
    import tempfile

    try:
        if not shutil.which("soffice"):
            return
        from sdpm.config import TEMPLATES_DIR

        sample = TEMPLATES_DIR / "blank-light.pptx"
        if not sample.exists():
            return
        t0 = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["HOME"] = tmp
            r = subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir", tmp, str(sample)],
                capture_output=True, timeout=180, env=env, check=False,
            )
        logger.info("soffice warm-up took %.1fs rc=%s", time.monotonic() - t0, r.returncode)
        _warmup_last_done = time.time()
    except Exception as e:  # noqa: BLE001 - best effort, never affects requests
        logger.warning("soffice warm-up failed: %s", e)
    finally:
        with _warmup_lock:
            _warmup_running = False


def _maybe_start_soffice_warm_up() -> None:
    """Start a background warm-up unless one is running or recently finished."""
    global _warmup_running
    if os.environ.get("SDPM_SKIP_SOFFICE_WARMUP"):
        return
    with _warmup_lock:
        if _warmup_running or time.time() - _warmup_last_done < _WARMUP_MIN_INTERVAL_S:
            return
        _warmup_running = True
    threading.Thread(target=_soffice_warm_up, name="soffice-warmup", daemon=True).start()


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
            if scope.get("method") == "POST" and "mcp-session-id" not in headers:
                # A new MCP session is being initialized on this microVM.
                _maybe_start_soffice_warm_up()
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

# Clients are built lazily inside the first request (see AwsStorage) so the
# platform V2 snapshot taken after startup holds no boto3 connection state.
_storage = AwsStorage(
    table_factory=lambda: boto3.resource("dynamodb", region_name=_region, config=SHORT_API).Table(_table_name),
    s3_factory=lambda: boto3.client("s3", region_name=_region, config=SHORT_API),
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


# --- Role entry tools ---
#
# The payloads come from sdpm.entry (same code as the local server). What differs
# here is where things live: styles/templates are per user on S3, and a deck has
# to be materialised into a temporary directory before the core can read it.
# start_translation is not bound — the translate workflow runs scripts from a
# checkout and has no cloud path (same reasoning as diff_pptx).


_MATERIALIZE_FILES = {"deck.json", "specs/brief.md", "specs/outline.md", "specs/art-direction.html"}
_MATERIALIZE_SLIDE = re.compile(r"^slides/[A-Za-z0-9_-]+\.json$")


def _materialize_deck(deck_id: str, target: Path) -> None:
    """Download deck.json, the three spec files and slides/*.json into ``target``.

    Strict allowlist on the relative key (no attachments, no path segments other
    than the ones named here), so a malformed key can never escape ``target``.
    """
    prefix = f"decks/{deck_id}/"
    for key in _storage.list_files(prefix=prefix, bucket=_storage.pptx_bucket):
        rel = key.removeprefix(prefix)
        if rel not in _MATERIALIZE_FILES and not _MATERIALIZE_SLIDE.match(rel):
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_storage.download_file_from_pptx_bucket(key=key))


@offloaded_tool
def start_presentation() -> str:
    """Start here for anything about slides — a new deck, editing or importing a PPTX,
    restyling a deck. Call it before any other sdpm tool.

    Returns the orchestrator role document (how to run the work end to end) plus what
    it needs first: available styles and PPTX templates.
    """
    from sdpm.entry import start_presentation as _start

    user_id = _get_user_id()
    styles = reference.list_styles(storage=_storage, user_id=user_id).get("styles", [])
    templates = template_mod.list_templates(storage=_storage, user_id=user_id).get("templates", [])
    return json.dumps(_start(styles=styles, templates=templates, output_dir=""), ensure_ascii=False)


@offloaded_tool
def start_composing(
    deck_id: Annotated[str, Field(description="Deck ID, as given in your instruction.")] = "",
    assigned_slugs: Annotated[
        list[str] | None,
        Field(description="The slugs you own. Other slides belong to other composers running in parallel."),
    ] = None,
) -> str:
    """Composer entry. You are a composer when your instruction gives you a deck_id and
    assigned_slugs — call this first with those values.

    Validates the specs, then returns the composer role document, the slide JSON spec,
    and everything the deck gives you: deck.json, brief, outline, art direction, template
    analysis, which slides exist, and the JSON of your assigned slides (plus any
    override-group head they inherit from, marked read-only). specs_ok=false with
    errors means stop and report.
    """
    import tempfile

    from sdpm.entry import start_composing as _start

    if not deck_id or not deck_id.strip():
        return json.dumps(_start(), ensure_ascii=False)
    _check_deck_access(deck_id, action="generate_pptx")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _materialize_deck(deck_id, root)
        analysis: dict | None = None
        try:
            template = json.loads((root / "deck.json").read_text(encoding="utf-8")).get("template") or ""
            if template:
                analysis = template_mod.analyze_template(
                    template_name=template, storage=_storage, user_id=_get_user_id()
                )
        except Exception:  # analysis is an aid, never a blocker
            analysis = None
        payload = _start(root, assigned_slugs, deck_id=deck_id, template_analysis=analysis or {})
    return json.dumps(payload, ensure_ascii=False)


@offloaded_tool
def start_style(
    base: Annotated[str, Field(description="Existing style to use as the skeleton; a bundled default when omitted.")] = "",
) -> str:
    """Call first when asked to create or edit a reusable style guide. (To restyle one
    deck, that is apply_style inside the start_presentation workflow.)

    Returns the style role document, the style catalogue, and one style's HTML to imitate.
    """
    from sdpm.entry import start_style as _start

    user_id = _get_user_id()
    styles = reference.list_styles(storage=_storage, user_id=user_id, include_all=True).get("styles", [])
    base_html: str | None = None
    if base:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", base):
            raise ValueError("Invalid style name")
        try:
            base_html = _storage.download_file_from_pptx_bucket(key=f"user-styles/{user_id}/{base}.html").decode("utf-8")
        except Exception:
            base_html = None  # fall through to the bundled lookup inside sdpm.entry
    return json.dumps(_start(base, styles=styles, base_html=base_html), ensure_ascii=False)


# --- Workflow Tools ---


@offloaded_tool
def init_deck_workspace(
    name: Annotated[str, Field(description='Presentation name, e.g. "lambda-overview".')],
) -> str:
    """Create an empty deck workspace (deck.json, specs/). A step inside the orchestrator
    workflow — after the brief is agreed, before apply_style — not where a request
    starts; start_presentation is. Returns the deckId and the workspace file list.
    """
    return json.dumps(
        init_mod.init_deck_workspace(
            name=name.strip(),
            user_id=_get_user_id(),
            storage=_storage,
        ),
        ensure_ascii=False,
    )


@offloaded_tool
def check_specs(
    deck_id: Annotated[str, Field(description='Deck ID.')],
    assigned_slugs: Annotated[list[str] | None, Field(description='Slugs about to be dispatched; each must exist in the outline.')] = None,
) -> str:
    """Validate deck.json and specs/outline.md before dispatching composers; ok=false means
    do not dispatch. Checks deck metadata, outline format and fields, TBD markers and the
    assigned slugs. Composers run the same check inside start_composing.
    """
    _check_deck_access(deck_id, action="generate_pptx")

    errors: list[str] = []
    try:
        deck_json = _storage.get_deck_json(deck_id)
    except Exception:
        errors.append("deck.json is missing")
        deck_json = {}

    outline_key = f"decks/{deck_id}/specs/outline.md"
    try:
        outline_text = _storage.download_file_from_pptx_bucket(key=outline_key).decode("utf-8")
    except Exception:
        errors.append("specs/outline.md is missing")
        outline_text = ""

    if errors:
        return json.dumps({"ok": False, "errors": errors, "warnings": [], "slugs": []})

    from sdpm.engine.schema import validate_specs

    return json.dumps(
        validate_specs(deck_json, outline_text, assigned_slugs),
        ensure_ascii=False,
    )


@offloaded_tool
def analyze_template(
    template: Annotated[str, Field(description='Template name, or a deck-owned template: attachments/imports/{importKey}/deck/template.pptx from import_attachment (needs deck_id).')],
    deck_id: Annotated[str, Field(description='Deck ID; required for a deck-owned template.')] = "",
) -> str:
    """Layouts, theme colors, fonts and slide size of a PPTX template. slide_size.ptPerPx
    belongs in deck.json slideSize (arch_diagram reads it).
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


@offloaded_tool
def read_attachment(
    source: Annotated[str, Field(description='S3 key from the [Attached:...] marker (uploads/{userId}/{uuid}/{name}), or an https:// URL.')],
    offset: Annotated[int, Field(description='UTF-8 byte offset into the text to start from.')] = 0,
    limit: Annotated[int, Field(description='Max bytes returned, 512–10240.')] = 10240,
) -> str:
    """Read a user-supplied file or URL as paged, line-numbered text — PDF, DOCX, XLSX, PPTX,
    text, CSV, HTML, JSON — or the image itself. Pure read, nothing is stored; works before
    a deck exists. Formats and paging: read_guides(["attachments"]).
    """
    from tools.attachment import read_attachment as _read

    return _read(
        source=source,
        user_id=_get_user_id(),
        storage=_storage,
        offset=offset,
        limit=limit,
    )


@offloaded_tool
def import_attachment(
    source: Annotated[str, Field(description='S3 key from the [Attached:...] marker (uploads/{userId}/{uuid}/{name}), or an https:// URL.')],
    deck_id: Annotated[str, Field(description='Deck ID.')],
    filename: Annotated[str, Field(description="Filename override; defaults to the source's name.")] = "",
) -> str:
    """Import a file or URL into the deck's attachments/ so slides can use it: images
    (converted to PNG), PDF/DOCX/XLSX (text + images), PPTX (full deck structure), URLs.
    Idempotent per source. On IMPORT_INCOMPLETE call again with the same arguments.
    Bundle layout: read_guides(["attachments"]).
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


@offloaded_tool
def generate_pptx(deck_id: Annotated[str, Field(description='Deck ID.')]) -> str:
    """Finalize the deck: full PPTX build, the WebP preview set, knowledge-base sync, and a
    whole-deck warnings report. run_python already rebuilds the PPTX after edits; this is
    the explicit hand-off step.
    """
    _check_deck_access(deck_id, action="generate_pptx")
    import traceback

    try:
        result = generate.generate_pptx(
            deck_id=deck_id, user_id=_get_user_id(), storage=_storage,
            kb_sync=_get_kb_sync(),
        )
        logger.info("generate_pptx completed: deck=%s slides=%s", deck_id, result.get("slideCount"))
        return json.dumps(result)
    except Exception as e:
        logger.exception("generate_pptx failed: deck=%s", deck_id)
        return json.dumps({"error": str(e), "traceback": traceback.format_exc()})


@offloaded_tool
def get_preview(
    deck_id: Annotated[str, Field(description='Deck ID.')],
    slugs: Annotated[list[str], Field(description='Slides to preview; at least one.')],
    quality: Annotated[str, Field(description='low (800px, ~480 tokens/slide) to review many slides; high (1280px, ~1229 tokens/slide) for detail.')] = "high",
) -> list:
    """Look at slides: returns PNG images of the given slugs for visual review. Available
    once the deck has been built (run_python with measure_slides, or generate_pptx).
    """
    _check_deck_access(deck_id, action="preview")
    if not slugs:
        return [{"type": "text", "text": "Error: slugs must not be empty"}]
    _wait_for_pending_previews(deck_id)
    if quality not in ("low", "high"):
        quality = "high"
    try:
        return preview.get_preview(
            deck_id=deck_id,
            slugs=slugs,
            storage=_storage,
            quality=quality,
        )
    except _storage._s3.exceptions.NoSuchKey:
        return [{"type": "text", "text": f'Preview not available yet. Run generate_pptx(deck_id="{deck_id}") first.'}]
    except Exception as e:
        if "NoSuchKey" in str(e):
            return [
                {"type": "text", "text": f'Preview not available yet. Run generate_pptx(deck_id="{deck_id}") first.'}
            ]
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
    t0 = time.monotonic()
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "svg", "--outdir", str(tmpdir), str(pptx_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    logger.info("soffice svg export took %.1fs (%s)", time.monotonic() - t0, pptx_path.name)
    return tmpdir / "measure.svg"


def _run_measure(
    tmpdir: Path, pptx_path: Path, slide_numbers: list[int], page_to_slug: dict[int, str] | None = None
) -> str:
    """PPTX → SVG → bbox measurement → report string."""
    from sdpm.engine.preview.measure import measure_from_svg, format_measure_report

    svg_path = _export_svg(tmpdir, pptx_path)
    if not svg_path.exists():
        return json.dumps({"error": "LibreOffice SVG export failed"})

    results = measure_from_svg(svg_path=svg_path, slide_indices=slide_numbers)
    return format_measure_report(results, page_to_slug=page_to_slug)


# --- Asset Tools ---


@offloaded_tool
def search_assets(
    query: Annotated[str, Field(description='Keywords, space-separated. Empty string lists the available sources instead.')] = "",
    source_filter: Annotated[str, Field(description='Only this source, e.g. aws or material.')] = "",
    limit: Annotated[int, Field(description='Max results per keyword.')] = 20,
    type_filter: Annotated[str, Field(description='Only this asset type, e.g. Architecture-Service.')] = "",
    theme_filter: Annotated[str, Field(description='dark or light.')] = "",
) -> str:
    """Search icons and images by keyword. With an empty query, lists the available sources
    (icon packs, image libraries) with counts, types and themes.
    """
    return json.dumps(
        assets.search_assets(
            query=query,
            storage=_storage,
            source_filter=source_filter,
            limit=limit,
            type_filter=type_filter,
            theme_filter=theme_filter,
        ),
    )


# --- Reference Tools ---


@offloaded_tool
def list_styles(
    include_all: Annotated[bool, Field(description='Include styles hidden by the pin filter.')] = False,
) -> str:
    """List design styles — pinned and user styles by default, everything with
    include_all. Names go to apply_style. start_presentation and start_style already
    return this list.
    """
    user_id = _get_user_id()
    return json.dumps(
        reference.list_styles(storage=_storage, user_id=user_id, include_all=include_all),
        ensure_ascii=False,
    )


@offloaded_tool
def apply_style(
    deck_id: Annotated[str, Field(description='Deck ID.')],
    style: Annotated[str, Field(description='Style name, e.g. "report".')],
    template: Annotated[str, Field(description='Template name, with or without .pptx.')] = "",
) -> str:
    """Apply a style (and optionally a template) to a deck: writes specs/art-direction.html
    and completes deck.json (template, defaultTextColor, fonts, slideSize). Returns what
    was written, which fields changed and where each value came from — fix anything
    wrong in deck.json with run_python.
    """
    _check_deck_access(deck_id, action="edit_slide")
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

    from sdpm.api import _changed_style_fields, merge_style_metadata, missing_deck_fields, style_field_sources

    deck_data = _storage.get_deck_json(deck_id)
    completed = dict(deck_data)
    if template:
        completed["template"] = template

    template_analysis = None
    selected_template = completed.get("template")
    if selected_template:
        template_analysis = json.loads(analyze_template(template=selected_template, deck_id=deck_id))
        if template_analysis.get("error"):
            raise ValueError(template_analysis["error"])
    merged = merge_style_metadata(
        html_bytes.decode("utf-8"),
        template_analysis,
        completed,
    )
    sources = style_field_sources(merged)
    if template:
        sources["template"] = "argument"
    updated = _changed_style_fields(deck_data, merged)

    dest_key = f"decks/{deck_id}/specs/art-direction.html"
    _storage.upload_file(key=dest_key, data=html_bytes, content_type="text/html")
    if updated:
        _storage.put_deck_json(deck_id, merged)
    return json.dumps(
        {
            "applied": style,
            "files": {
                "specs/art-direction.html": {"path": "specs/art-direction.html", "bytes": len(html_bytes)},
                "deck.json": {"path": "deck.json", "content": merged},
            },
            "updated": updated,
            "sources": sources,
            "missing": missing_deck_fields(merged),
        }
    )


# --- Reference tools (bound from the shared contract; bundled data baked into the image) ---

offloaded_tool(contract.read_guides)


# --- Utility Tools ---


@offloaded_tool
def list_templates() -> str:
    """List available PPTX templates (name, source, description).
    start_presentation already returns this list.
    """
    return json.dumps(
        template_mod.list_templates(storage=_storage, user_id=_get_user_id()),
    )


@offloaded_tool
def code_to_slide(
    deck_id: Annotated[str, Field(description='Deck ID.')],
    code: Annotated[str, Field(description='Source code text.')],
    name: Annotated[str, Field(description='Basename of the includes file, without .json.')],
    language: Annotated[str, Field(description='Language for syntax highlighting.')] = "python",
    theme: Annotated[str, Field(description='dark or light.')] = "dark",
    x: Annotated[int, Field(description='Left edge in px.')] = 0,
    y: Annotated[int, Field(description='Top edge in px.')] = 0,
    width: Annotated[int, Field(description='Width in px.')] = 800,
    height: Annotated[int, Field(description='Height in px.')] = 300,
) -> str:
    """Render source code as a syntax-highlighted block saved to includes/<name>.json in the
    deck. Reference it from a slide as {"type": "include", "src": "<returned include_path>"}.
    """
    _check_deck_access(deck_id, action="edit_slide")
    return json.dumps(
        code_block_mod.code_block_to_include(
            deck_id=deck_id,
            code=code,
            name=name,
            storage=_storage,
            language=language,
            theme=theme,
            x=x,
            y=y,
            width=width,
            height=height,
        ),
    )


# --- Code Execution (Code Interpreter) ---


def _build_relevant(p: str) -> bool:
    """True if a workspace path affects the built PPTX artifact."""
    return p in ("deck.json", "presentation.json", "specs/outline.md") or p.startswith(("slides/", "includes/"))


def _post_processing_plan(deck_changed: bool, measure_slides: list[str] | None) -> dict[str, bool]:
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


@offloaded_tool
def run_python(
    purpose: Annotated[str, Field(description="One line on what this code does, in the user's language (shown in the UI).")],
    code: Annotated[str, Field(description='Python code.')],
    deck_id: Annotated[str, Field(description='Deck ID.')],
    measure_slides: Annotated[list[str] | None, Field(description='Slugs to render, measure, lint and preview after the code ran — the ones you edited.')] = None,
) -> str:
    """Run Python inside the deck workspace — the way to read and write deck files
    (deck.json, specs/, slides/, includes/, attachments/). Helpers: read_json(path),
    write_json(path, data), read_text(path), write_text(path, text), list_files(subdir=".");
    plain open() also works. Writes persist (read-only decks: discarded, and the result
    says so); output.pptx rebuilds when deck.json, slides/, includes/ or specs/outline.md
    changed. measure_slides renders, measures text overflow, lints and previews those slugs.
    """
    if not deck_id:
        return json.dumps({
            "error": "deck_id is required: run_python runs inside a deck workspace "
                     "(create one with init_deck_workspace first)."
        })

    result: dict = {}

    # Writes persist by default. If the user only has read access, run the
    # sandbox without write-back instead of failing (read-only analysis).
    persist_writes = True
    try:
        _check_deck_access(deck_id, action="edit_slide")
    except ValueError:
        _check_deck_access(deck_id, action="read")
        persist_writes = False
        result["readOnly"] = "You have read-only access to this deck: file writes were not persisted."

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
            "outline.md format violation. Read workflow `orchestrator` for the outline format."
        )

    if lint_diagnostics:
        errs = result.setdefault("errors", {})
        errs["lintDiagnostics"] = lint_diagnostics

    # Post-processing: rebuild the PPTX artifact whenever build-relevant files
    # changed (the artifact follows the deck automatically); measure_slides
    # (and ONLY measure_slides) triggers the expensive verification pass.
    deck_changed = any(_build_relevant(p) for p in changed_paths)
    plan = _post_processing_plan(deck_changed, measure_slides)
    if plan["build"]:
        import shutil
        import traceback

        try:
            from tools.generate import _prepare_workspace

            user_id = _get_user_id()
            _prepare_epoch = int(time.time())
            _phase: dict[str, float] = {}
            _t = time.monotonic()
            tmpdir, slides, build_kwargs = _prepare_workspace(deck_id, user_id, _storage)
            _phase["prepare_s3"] = time.monotonic() - _t
            _t = time.monotonic()
            pptx_path, invalid_layouts = _build_pptx(tmpdir, slides, build_kwargs)
            _phase["build"] = time.monotonic() - _t
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
                        _t = time.monotonic()
                        measure_result = _run_measure(tmpdir, pptx_path, page_numbers, page_to_slug=page_to_slug)
                        _phase["measure"] = time.monotonic() - _t
                        result["measure"] = measure_result
                    else:
                        result["measure"] = json.dumps({"error": "No matching slides found for given slugs"})
                except Exception as e:
                    result["measure"] = json.dumps({"error": str(e)})

                # Layout bias (filter to measured slides; bias uses 1-based)
                try:
                    from sdpm.engine.preview import check_layout_imbalance_data

                    layout_bias = [
                        b
                        for b in check_layout_imbalance_data(pptx_path, slide_defs=slides)
                        if b.get("slide") in set(page_numbers)
                    ]
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

            _t = time.monotonic()
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
                        content_type=("application/vnd.openxmlformats-officedocument.presentationml.presentation"),
                    )
                    _old = _storage.update_deck(
                        deck_id=deck_id,
                        user_id=user_id,
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
                                Bucket=_storage.pptx_bucket,
                                Key=_old_key,
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
                                Bucket=_storage.pptx_bucket,
                                Key=_pptx_key,
                            )
                        except Exception:
                            pass

            _phase["artifact_s3"] = time.monotonic() - _t
            if plan["verify"]:
                # Everything the composer needs is in `result` now. The live
                # preview JSON (compose) and the measured slugs' WebP are for
                # the Web UI / the next get_preview, and take 5-10s; finish them
                # in the background so the tool returns after measure.
                # The task owns tmpdir and removes it when done.
                _bg_t0 = time.monotonic()
                _bg_slugs = list(measure_slides or [])
                _pending_event = _register_pending_preview(deck_id)

                def _finish_compose_and_previews() -> None:
                    try:
                        # Previews first: the composer's next get_preview waits on
                        # _pending_event, so the images must be on S3 as early as
                        # possible; compose (Web UI) follows.
                        if measure_slides:
                            try:
                                from tools.generate import generate_previews_for_pages

                                preview_dir = tmpdir / "preview_out"
                                preview_dir.mkdir(exist_ok=True)
                                wanted = {s: slug_to_page[s] for s in measure_slides if slug_to_page.get(s)}
                                webp_by_page = generate_previews_for_pages(pptx_path, preview_dir, list(wanted.values()))
                                uploaded = []
                                for slug, page in wanted.items():
                                    if page in webp_by_page:
                                        _storage.upload_file(
                                            key=f"previews/{deck_id}/{slug}_{_prepare_epoch}.webp",
                                            data=webp_by_page[page].read_bytes(),
                                            content_type="image/webp",
                                        )
                                        uploaded.append(slug)
                                logger.info("previews uploaded for %s: %s", deck_id, ", ".join(uploaded))
                            except Exception:
                                logger.warning("preview generation failed", exc_info=True)
                        _clear_pending_preview(deck_id, _pending_event)

                        # Only generates compose for measure_slides slugs (parallel-safe).
                        # Uses _prepare_epoch (snapshot time) so the composer with the
                        # newest slides/ snapshot wins on defs via epoch comparison.
                        try:
                            from tools.compose import extract_optimized_defs, load_svg, split_slide_components
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
                                svg_tree = load_svg(svg_path)
                                defs_data = extract_optimized_defs(svg_tree)
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
                                def _compose_one(slug: str) -> None:
                                    if slug in invalid_slug_set:
                                        # Do not surface a fallback-rendered slide as a
                                        # live-preview artifact. The composer for this
                                        # slug will see the error and fix the layout.
                                        return
                                    pn = slug_to_page.get(slug)
                                    if not pn:
                                        return
                                    try:
                                        comp_data = split_slide_components(svg_tree, pn)
                                        from sdpm.engine.schema import extract_regions

                                        slide = slides[pn - 1] if pn <= len(slides) else {}
                                        comp_data["regions"] = extract_regions(slide)

                                        # sourceHash from slide JSON (content-based diff)
                                        src_hash = (
                                            _hashlib.md5(
                                                _json.dumps(slides[pn - 1], sort_keys=True, ensure_ascii=False).encode(),
                                                usedforsecurity=False,
                                            ).hexdigest()
                                            if pn <= len(slides)
                                            else ""
                                        )
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
                                            _m = _re.search(r"_(\d+)\.json$", k)
                                            if k.startswith(f"{compose_prefix}{slug}_") and _m and int(_m.group(1)) < _prepare_epoch:
                                                try:
                                                    _storage._s3.delete_object(Bucket=_storage.pptx_bucket, Key=k)
                                                except Exception:
                                                    pass
                                    except Exception:
                                        logger.error("compose failed for slug %s", slug, exc_info=True)

                                # Each slug is independent (own S3 keys); the S3 round
                                # trips dominate, so run them side by side.
                                from concurrent.futures import ThreadPoolExecutor
                                with ThreadPoolExecutor(max_workers=8) as pool:
                                    list(pool.map(_compose_one, sorted(compose_slugs)))
                        except Exception:
                            logger.error("compose failed", exc_info=True)

                    finally:
                        _clear_pending_preview(deck_id, _pending_event)
                        shutil.rmtree(tmpdir, ignore_errors=True)
                        logger.info(
                            "run_python background compose/previews for deck %s took %.1fs",
                            deck_id, time.monotonic() - _bg_t0,
                        )

                if _bg_slugs:
                    result["previewHint"] = (
                        f"Preview images are being generated for {', '.join(_bg_slugs)} "
                        f"(ready within seconds). Call get_preview(deck_id=\"{deck_id}\", slugs=[...]) to view."
                    )
                _run_in_background(_finish_compose_and_previews, name=f"compose-{deck_id}")
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
                    result["pptx_error"] = f"PPTX build failed — the downloadable PPTX may be stale: {msg}"

    if "_phase" in locals():
        logger.info(
            "run_python post-processing for deck %s: %s",
            deck_id, " ".join(f"{k}={v:.1f}s" for k, v in _phase.items()),
        )
    return json.dumps(result, ensure_ascii=False)


# --- Layout tools (bound from the shared contract) ---

offloaded_tool(contract.grid)
offloaded_tool(contract.arch_diagram)


# --- Style Execution (Code Interpreter) ---


@offloaded_tool
def run_style_python(
    purpose: Annotated[str, Field(description="One line on what this code does, in the user's language (shown in the UI).")],
    code: Annotated[str, Field(description='Python code; imports allowed (PIL, colorsys, numpy installed).')],
    style_name: Annotated[str | None, Field(description='Style to load as style.html (read/write).')] = None,
    ref_styles: Annotated[list[str] | None, Field(description='Styles to load read-only as ref/{name}.html.')] = None,
) -> str:
    """Run Python in a style workspace: style.html is the style named by style_name, ref/ holds
    the ref_styles. Writes to style.html persist to the user's style store on every run.
    """
    user_id = _get_user_id()

    client = boto3.client("bedrock-agentcore", region_name=_region, config=SHORT_API)
    # User code may run for minutes and must not be retried — separate client.
    exec_client = boto3.client("bedrock-agentcore", region_name=_region, config=LONG_CALL)
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
            sessionId=session_id,
            name="executeCode",
            arguments={"language": "python", "code": setup_code},
        )

        # Write files into sandbox
        if file_contents:
            client.invoke_code_interpreter(
                codeInterpreterIdentifier="aws.codeinterpreter.v1",
                sessionId=session_id,
                name="writeFiles",
                arguments={"content": file_contents},
            )

        # Execute user code
        response = exec_client.invoke_code_interpreter(
            codeInterpreterIdentifier="aws.codeinterpreter.v1",
            sessionId=session_id,
            name="executeCode",
            arguments={"language": "python", "code": code},
        )
        output = sandbox_mod._collect_stream(response)

        result: dict = {"output": output}

        # Persist style.html when it changed (always — no "unsaved" state)
        if style_name:
            read_code = "import sys\ntry:\n    print(open('style.html').read())\nexcept FileNotFoundError:\n    print('__NOT_FOUND__')\n"
            read_resp = client.invoke_code_interpreter(
                codeInterpreterIdentifier="aws.codeinterpreter.v1",
                sessionId=session_id,
                name="executeCode",
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
                sessionId=session_id,
                name="executeCode",
                arguments={"language": "python", "code": "import os\nprint(os.path.exists('style.html'))\n"},
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
_kb_sync_resolved_at = 0.0
_KB_ID_TTL_S = 300

# The KB id is resolved on first use, not at import.
#
# Under AgentCore Runtime platformVersion V2 the process is snapshotted once its
# initialization completes, and every restored instance inherits that memory
# state. Anything read at import time is therefore frozen for the life of the
# snapshot — which is exactly wrong for an SSM parameter, since SSM exists so the
# value can change without a redeploy. Reading it at import pinned the runtime to
# a stale KB id until the next runtime update (on V1 the ~40-minute container
# recycling hid this by re-reading on its own).
#
# Registration of search_slides below is gated on configuration rather than on a
# successful read, so a transient SSM failure no longer removes the tool for the
# life of the process.
_kb_configured = bool((_kb_id or _kb_ssm_param) and _vector_bucket_name and _vector_index_name)


def _get_kb_sync():
    """Return a KBSync bound to the current KB id, or None if unavailable.

    Resolves the id from SSM on first use and refreshes it every
    ``_KB_ID_TTL_S`` seconds. Wall-clock time is used deliberately:
    ``time.monotonic()`` does not advance across a snapshot restore, so a
    duration measured against it can silently be wrong under V2.
    """
    global _kb_sync, _kb_sync_resolved_at
    if not _kb_configured:
        return None
    now = time.time()
    if _kb_sync is not None and (now - _kb_sync_resolved_at) < _KB_ID_TTL_S:
        return _kb_sync

    kb_id = _kb_id
    if not kb_id and _kb_ssm_param:
        try:
            kb_id = boto3.client("ssm", region_name=_region, config=SHORT_API).get_parameter(
                Name=_kb_ssm_param
            )["Parameter"]["Value"]
        except Exception as e:
            logger.warning("Could not resolve KB ID from SSM %s: %s", _kb_ssm_param, e)
            return _kb_sync  # keep serving the previous value if we had one
    if not kb_id:
        return None

    from tools.kb_sync import KBSync  # noqa: E402

    _kb_sync = KBSync(
        kb_id=kb_id,
        vector_bucket_name=_vector_bucket_name,
        vector_index_name=_vector_index_name,
        region=_region,
    )
    _kb_sync_resolved_at = now
    return _kb_sync


if _kb_configured:

    @offloaded_tool
    def search_slides(
        query: Annotated[str, Field(description="Natural-language query.")],
        scope: Annotated[str, Field(description="mine (your decks), public, or all.")] = "mine",
        deck_name: Annotated[str, Field(description="Partial match on deck name.")] = "",
        layout: Annotated[str, Field(description="Exact match on layout type.")] = "",
        days: Annotated[int, Field(description="Only slides from the last N days; 0 = all time.")] = 0,
    ) -> str:
        """Find existing slides by meaning across your (or public) decks — to reuse or
        reference earlier work.
        """
        kb = _get_kb_sync()
        if kb is None:
            return json.dumps({"error": "Knowledge base is not available"})
        results = kb.search(
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
