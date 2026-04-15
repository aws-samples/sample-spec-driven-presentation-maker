# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Strands Agent for spec-driven-presentation-maker — uses Amazon Bedrock for LLM inference.

AI model outputs should be reviewed before use in production contexts.

Strands Agent for spec-driven-presentation-maker — connects to L3 MCP Server Runtime directly.

# Security: AWS manages infrastructure security. You manage access control,
# data classification, and IAM policies. See SECURITY.md for details.

Uses MCPClient + streamablehttp_client for MCP tool access.
JWT Bearer authentication — caller's JWT is forwarded to MCP Server.
"""

import asyncio
import json
import logging
import os
import traceback
import urllib.parse

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from botocore.config import Config as BotocoreConfig
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.models import BedrockModel
from strands.models.bedrock import CacheConfig
from strands.tools.mcp import MCPClient
from tools.upload_tools import list_uploads
from tools.web_tools import web_fetch

logger = logging.getLogger("sdpm.agent")

app = BedrockAgentCoreApp()


# ---------------------------------------------------------------------------
# MCP Servers
#
# Register MCP servers here. Three connection patterns are supported:
#
#   Pattern 1: Amazon Bedrock AgentCore Runtime with JWT Bearer
#     - For MCP servers deployed on Amazon Bedrock AgentCore Runtime with JWT authentication
#     - Requires: Runtime ARN, caller's JWT token
#
#   Pattern 2: IAM-authenticated Remote MCP (with public fallback)
#     - For AWS-managed MCP servers (e.g. AWS Knowledge MCP)
#     - Primary: IAM-authenticated endpoint via mcp-proxy-for-aws
#     - Fallback: Public unauthenticated endpoint
#
#   Pattern 3: Local stdio MCP
#     - For MCP servers that run as local processes
#     - Requires: command to execute
#
# To add your own MCP server, create a MCPClient and add it to the
# `tools` list in create_agent().
# ---------------------------------------------------------------------------


def _mcp_agentcore_runtime(jwt_token: str) -> MCPClient:
    """Pattern 1: Amazon Bedrock AgentCore Runtime MCP Server with JWT Bearer authentication.

    Connects to spec-driven-presentation-maker MCP Server deployed on Amazon Bedrock AgentCore Runtime.
    Caller's JWT is forwarded as-is for authentication and user_id propagation.

    Args:
        jwt_token: JWT access token from the caller (without "Bearer " prefix).

    Returns:
        MCPClient for spec-driven-presentation-maker MCP Server.
    """
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    runtime_arn = os.environ["MCP_RUNTIME_ARN"]
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"

    return MCPClient(
        lambda: streamablehttp_client(
            url=url,
            headers={"Authorization": f"Bearer {jwt_token}"},
            timeout=120,
            terminate_on_close=False,
        ),
    )


def _mcp_aws_knowledge() -> MCPClient:
    """Pattern 2: IAM-authenticated AWS Knowledge MCP with public fallback.

    AWS Knowledge MCP provides access to AWS documentation, API references,
    What's New, Well-Architected guidance, and blog posts.

    Primary: IAM-authenticated endpoint (higher rate limits).
    Fallback: Public unauthenticated endpoint.

    Returns:
        MCPClient for AWS Knowledge MCP.
    """
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    try:
        from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
        return MCPClient(
            lambda: aws_iam_streamablehttp_client(
                endpoint=f"https://aws-mcp.{region}.api.aws/mcp",
                aws_service="aws-mcp",
            ),
        )
    except Exception:
        logger.warning("IAM auth unavailable for AWS Knowledge MCP, using public endpoint")
        return MCPClient(
            lambda: streamablehttp_client(url="https://knowledge-mcp.global.api.aws"),
        )


def _mcp_aws_pricing() -> MCPClient:
    """Pattern 3: Local stdio MCP Server.

    AWS Pricing MCP provides real-time pricing data via the AWS Pricing API.
    Runs as a local process using stdio transport.

    Returns:
        MCPClient for AWS Pricing MCP.
    """
    from mcp.client.stdio import StdioServerParameters, stdio_client

    # Pricing API is only available in us-east-1 and ap-south-1
    return MCPClient(
        lambda: stdio_client(StdioServerParameters(
            command="awslabs.aws-pricing-mcp-server",
            env={**os.environ, "AWS_REGION": "us-east-1", "FASTMCP_LOG_LEVEL": "ERROR"},
        )),
    )


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

_SPEC_AGENT_PROMPT_TEMPLATE = """Current date and time: {now}

You are the SPEC agent for spec-driven-presentation-maker.
You handle Phase 1 (briefing → outline → art-direction) through user dialogue.
Respond in the same language as the user.

{mcp_instructions}

## Your Role
- Conduct Phase 1: briefing, outline design, art direction — all through user dialogue
- When Phase 1 is complete and the user approves, call `compose_slides(deck_id=..., slide_groups=[...])` to delegate slide generation to the composer agent
- You do NOT write slide JSON yourself. You do NOT call build/measure/preview tools directly
- Do NOT read Phase 2/3 workflows (create-new-2-compose, create-new-3-review, slide-json-spec) or Phase 2 guides/examples (grid, components, patterns) — the composer agent has its own references pre-loaded
- After compose_slides returns, review the report and relay results to the user
- For user modification requests, translate them into instructions and call compose_slides again

## Post-Compose Review
After compose_slides returns, perform a cross-slide consistency review:
1. Check `outline_check` in the report — if `missing` is non-empty, decide whether to retry or inform the user
2. Call `get_preview(deck_id, slide_numbers=[...])` to get preview images of ALL slides
3. Review the preview images for:
   - Adjacent slides using the same layout (repetitive feel) → instruct composer to vary
   - Message flow disconnects between slides (does the story progress logically?)
   - Foreshadowing set up in early slides but not resolved later
   - Design token deviations (colors, fonts inconsistent with art-direction)
4. If issues found, call compose_slides again with targeted instructions for specific slugs
5. Present the final result to the user with preview images

## Slide Group Assignment for compose_slides
When calling compose_slides, split the outline into groups using this 2-step process:

**Step 1 — Form core groups** (slides that MUST share the same design):
- Override-inherited slides (same slug prefix, e.g. demo-1, demo-2) → same group (required)
- Structurally identical roles (e.g. all intro slides, all demo slides) → same group (strongly recommended)
- Slides the user explicitly asked to unify → same group

**Step 2 — Distribute independent slides** for load balancing:
- Assign remaining slides (title, closing, etc.) to existing groups so each group has roughly equal work
- Do NOT create a group with only independent slides

Rules:
- Do NOT consider adjacent-slide layout diversity (handled by post-review)
- No constraint on group count or size (concurrency is controlled by semaphore)
- Do NOT create a core group with only 1 slide (nothing to unify — treat as independent)

## File Uploads
- When a user message contains [Attached: filename (uploadId: xxx)], use read_uploaded_file(upload_id, deck_id) to read content. If no deck exists yet, call init_presentation() first.
- For uploaded PDFs, use page_start=N to paginate through pages (e.g. page_start=20 reads pages 21-40). Always follow the truncation message to read remaining pages.
- Use list_uploads(session_id) to see all files in the current session

## Web Fetch
- Use web_fetch(url) to read a specific URL as Markdown
- For long HTML pages, use start=N (character offset) to continue reading from where it was truncated
- For PDFs, use page_start=N to paginate through pages (e.g. page_start=5 reads pages 6-10). Always follow the truncation message to read remaining pages.
- If a user message starts with <!--sdpm:include_images=true-->, pass include_images=true when calling web_fetch on HTML pages to preserve image URLs in the output.
- To use a web image in slides: call save_web_image(url, deck_id) with the image URL. It downloads the image to the deck workspace and returns {"src": "images/filename"} for use in slide JSON.
- Do NOT use read_uploaded_file for web images — use save_web_image instead.
"""

_COMPOSER_PROMPT_TEMPLATE = """Current date and time: {now}

You are the composer agent for spec-driven-presentation-maker.
You handle Phase 2 (compose slides) and Phase 3 (review + polish).
You work silently — no user interaction. Execute the instruction fully and return.

## Target Deck
deck_id: {deck_id}
Use this deck_id for ALL run_python and generate_pptx calls. Do NOT call init_presentation.

## Architecture
- Edit workspace files via `run_python(deck_id="{deck_id}", save=True)` using normal file I/O
- Measure: `run_python(code=..., deck_id="{deck_id}", save=True, measure_slides=["slug"])` — always specify measure_slides when editing slides
- MCP tools: generate_pptx, get_preview for build and preview
- Do NOT call read_workflows, read_guides, read_examples — all references are pre-loaded below
- Do NOT call init_presentation — the deck already exists

## Your Role
- Read the instruction provided, which specifies which slides to compose
- deck.json is READ-ONLY — do not modify it
- Write each slide to slides/{{slug}}.json via run_python
- Follow the compose workflow below — you already have everything you need
- After composing, generate PPTX, measure, preview, and polish autonomously
- ALL references below are already loaded — skip any "Before starting, you MUST run/read" instructions in the workflow
- Your assigned slides are pre-loaded below. Other slides in slides/ are listed by name only — read them via run_python if you need to reference their content

## Constraints
- Do NOT ask the user anything — you have no user interaction
- Do NOT modify deck.json, specs/brief.md, specs/outline.md, or specs/art-direction.html
- Write ONLY the slides assigned to you

{common_context}
"""


def _build_system_prompt(template: str, mcp_instructions: str = "", **kwargs: str) -> str:
    """Build system prompt with current timestamp and optional placeholders.

    Args:
        template: Prompt template string with {now} and optional placeholders.
        mcp_instructions: MCP server instructions (for SPEC agent).
        **kwargs: Additional placeholder replacements (e.g. prefetched_context).

    Returns:
        Formatted system prompt string.
    """
    from datetime import datetime, timedelta, timezone

    jst = timezone(timedelta(hours=9))
    now_str = datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")
    result = template.replace("{now}", now_str).replace("{mcp_instructions}", mcp_instructions)
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", value)
    return result


# ---------------------------------------------------------------------------
# Compose Slides Tool (Agents as Tools pattern)
# ---------------------------------------------------------------------------

# References to prefetch for composer (tool_name, arguments, label)
# System prompt: workflow/spec (how to work)
_COMPOSER_PREFETCH_SYSTEM = [
    ("read_workflows", {"names": ["create-new-2-compose"]}, "Compose Workflow"),
    ("read_workflows", {"names": ["slide-json-spec"]}, "Slide JSON Spec"),
]
# User message: reference data (what to reference)
_COMPOSER_PREFETCH_REFS = [
    ("read_guides", {"names": ["grid"]}, "Grid Guide"),
    ("read_examples", {"names": ["components/all"]}, "Components Reference"),
    ("read_examples", {"names": ["patterns"]}, "Patterns Catalog"),
]


def _prefetch_sections(mcp_client, prefetch_list: list) -> list[str]:
    """Prefetch references from MCP server.

    Args:
        mcp_client: MCPClient instance.
        prefetch_list: List of (tool_name, arguments, label) tuples.

    Returns:
        List of section strings.
    """
    import uuid

    sections = []
    for tool_name, args, label in prefetch_list:
        result = mcp_client.call_tool_sync(
            tool_use_id=f"prefetch-{uuid.uuid4().hex[:8]}",
            name=tool_name,
            arguments=args,
        )
        if result.get("status") == "error":
            raise RuntimeError(f"Failed to prefetch {label}: {result.get('content')}")
        text = ""
        for item in result.get("content", []):
            if isinstance(item, dict) and "text" in item:
                text += item["text"]
        if text:
            sections.append(f"## {label}\n\n{text}")
    return sections


def _prefetch_deck_specs(mcp_client, deck_id: str, assigned_slugs: list[str]) -> list[str]:
    """Prefetch deck-specific specs and assigned slide contents.

    Args:
        mcp_client: MCPClient instance.
        deck_id: Deck ID.
        assigned_slugs: Slugs to load in full. Others listed by name only.

    Returns:
        List of section strings.
    """
    import json as _json
    import uuid

    slugs_repr = repr(assigned_slugs)
    code = (
        "import json, os\n"
        "specs = {}\n"
        f"_assigned = set({slugs_repr})\n"
        "for name in ['specs/brief.md', 'specs/outline.md', 'specs/art-direction.html', 'deck.json']:\n"
        "    try:\n"
        "        specs[name] = open(name).read()\n"
        "    except FileNotFoundError:\n"
        "        pass\n"
        "if os.path.isdir('slides'):\n"
        "    _others = []\n"
        "    for f in sorted(os.listdir('slides')):\n"
        "        slug = f.removesuffix('.json')\n"
        "        if slug in _assigned:\n"
        "            specs[f'slides/{f}'] = open(f'slides/{f}').read()\n"
        "        else:\n"
        "            _others.append(f)\n"
        "    if _others:\n"
        "        specs['slides/ (other, read via run_python if needed)'] = ', '.join(_others)\n"
        "print(json.dumps(specs, ensure_ascii=False))\n"
    )
    result = mcp_client.call_tool_sync(
        tool_use_id=f"prefetch-{uuid.uuid4().hex[:8]}",
        name="run_python",
        arguments={"code": code, "deck_id": deck_id},
    )
    if result.get("status") == "error":
        raise RuntimeError(f"Failed to prefetch specs for deck {deck_id}: {result.get('content')}")

    sections = []
    for item in result.get("content", []):
        if isinstance(item, dict) and "text" in item:
            try:
                output = _json.loads(item["text"])
                if isinstance(output, dict) and "output" in output:
                    output = _json.loads(output["output"])
                if not isinstance(output, dict) or not output:
                    raise RuntimeError(f"Specs empty for deck {deck_id} — workspace may not exist")
                for filename, content in output.items():
                    sections.append(f"## {filename}\n\n{content}")
            except _json.JSONDecodeError as e:
                raise RuntimeError(f"Failed to parse specs for deck {deck_id}: {e}") from e
    return sections


def _build_common_context(common_sections: list[str]) -> str:
    """Build common reference context (shared across all groups, cacheable)."""
    if not common_sections:
        return ""
    return "# Pre-loaded References (already executed — do NOT re-fetch)\n\n" + "\n\n---\n\n".join(common_sections)


def _build_deck_context(deck_sections: list[str]) -> str:
    """Build deck-specific context (varies per group, not cacheable)."""
    if not deck_sections:
        return ""
    return "# Deck-Specific References\n\n" + "\n\n---\n\n".join(deck_sections)


def _make_compose_slides(mcp_servers: list, model, mcp_instructions: str):
    """Create compose_slides tool with closed-over MCP servers, model, and instructions.

    Args:
        mcp_servers: List of MCPClient instances for the composer agent.
        model: BedrockModel instance.
        mcp_instructions: Pre-collected MCP server instructions (unused, kept for signature compat).

    Returns:
        A @tool-decorated function.
    """
    from strands import tool as strands_tool

    # Find the primary MCP client for prefetching
    mcp_client = mcp_servers[0] if mcp_servers else None

    @strands_tool(
        name="compose_slides",
        description="Compose slides by delegating to composer agents. "
        "Call when Phase 1 is complete and slides need to be generated.",
        inputSchema={
            "json": {
                "type": "object",
                "properties": {
                    "deck_id": {
                        "type": "string",
                        "description": "Deck ID for the presentation workspace",
                    },
                    "slide_groups": {
                        "type": "array",
                        "description": "List of groups to compose. Each group has slugs and instruction.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "slugs": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Slide slugs to generate (e.g. ['title', 'problem'])",
                                },
                                "instruction": {
                                    "type": "string",
                                    "description": "What to compose for this group",
                                },
                            },
                            "required": ["slugs", "instruction"],
                        },
                    },
                },
                "required": ["deck_id", "slide_groups"],
            }
        },
    )
    async def compose_slides(deck_id: str, slide_groups: list):
        """Compose slides by delegating to composer agents.

        Prefetches all Phase 2 references once, then injects into composer prompt.
        Runs groups in parallel (controlled by COMPOSER_MAX_CONCURRENCY env var).
        Async generator: yields progress dicts, then returns final result str.
        """
        import asyncio
        import json as _json
        import os

        max_concurrency = int(os.environ.get("COMPOSER_MAX_CONCURRENCY", "10"))
        sem = asyncio.Semaphore(max_concurrency)

        generated = []
        errors = []
        summaries = {}
        total = sum(len(g["slugs"]) for g in slide_groups)
        done_count = 0

        try:

            # Prefetch references once (Python call, no LLM turns)
            yield {"status": "prefetching", "message": "Loading references..."}
            system_sections = _prefetch_sections(mcp_client, _COMPOSER_PREFETCH_SYSTEM) if mcp_client else []
            ref_sections = _prefetch_sections(mcp_client, _COMPOSER_PREFETCH_REFS) if mcp_client else []

            # Build system prompt (workflow/spec — how to work)
            system_context = _build_common_context(system_sections)
            static_prompt = _build_system_prompt(
                _COMPOSER_PROMPT_TEMPLATE,
                common_context=system_context,
                deck_id=deck_id,
            )

            # Build common reference text (guides/examples — shared across groups)
            common_ref_text = _build_common_context(ref_sections)

            progress_q: asyncio.Queue = asyncio.Queue()

            async def run_group(gi: int, group: dict) -> dict:
                """Run a single composer group under semaphore."""
                async with sem:
                    slugs_label = ", ".join(group["slugs"])
                    progress_q.put_nowait({"group": gi + 1, "total_groups": len(slide_groups), "slugs": slugs_label, "status": "starting"})

                    deck_sections = _prefetch_deck_specs(mcp_client, deck_id, group["slugs"]) if mcp_client else []
                    deck_context = _build_deck_context(deck_sections)

                    # User message: common refs (cacheable) + deck specs (per-group) + instruction
                    user_content = (
                        f"{common_ref_text}\n\n---\n\n{deck_context}\n\n---\n\n"
                        f"{group['instruction']}"
                    )

                    last_tool_id = ""

                    def _on_event(**kwargs):
                        nonlocal last_tool_id
                        tu = kwargs.get("current_tool_use")
                        if tu:
                            tid = tu.get("toolUseId", "")
                            name = tu.get("name", "")
                            if tid and name and tid != last_tool_id:
                                last_tool_id = tid
                                progress_q.put_nowait({"group": gi + 1, "slugs": slugs_label, "tool": name, "toolUseId": tid})

                    composer = Agent(
                        system_prompt=[
                            {"text": static_prompt},
                            {"cachePoint": {"type": "default"}},
                        ],
                        tools=[*mcp_servers],
                        model=model,
                        callback_handler=_on_event,
                    )
                    from strands.hooks.events import BeforeToolCallEvent, AfterToolCallEvent

                    async def _before_tool(event: BeforeToolCallEvent):
                        tu = event.tool_use
                        progress_q.put_nowait({
                            "group": gi + 1, "slugs": slugs_label,
                            "tool": tu.get("name", ""), "toolUseId": tu.get("toolUseId", ""),
                            "input": tu.get("input", {}),
                        })

                    async def _after_tool(event: AfterToolCallEvent):
                        tu = event.tool_use
                        progress_q.put_nowait({
                            "group": gi + 1, "slugs": slugs_label,
                            "toolResult": tu.get("toolUseId", ""),
                            "toolStatus": "error" if isinstance(event.result, dict) and event.result.get("status") == "error" else "success",
                        })

                    composer.hooks.add_callback(BeforeToolCallEvent, _before_tool)
                    composer.hooks.add_callback(AfterToolCallEvent, _after_tool)

                    max_retries = 2
                    for attempt in range(max_retries + 1):
                        try:
                            response = await composer.invoke_async(user_content if attempt == 0 else None)
                            progress_q.put_nowait({"group": gi + 1, "slugs": slugs_label, "status": "done"})
                            return {"slugs": group["slugs"], "response": str(response)}
                        except Exception as e:
                            if attempt < max_retries:
                                progress_q.put_nowait({
                                    "group": gi + 1, "slugs": slugs_label,
                                    "status": "retrying", "attempt": attempt + 1, "error": str(e),
                                })
                                continue
                            raise

            # Launch all groups
            tasks = [asyncio.create_task(run_group(gi, g)) for gi, g in enumerate(slide_groups)]

            # Drain progress queue until all tasks complete
            while not all(t.done() for t in tasks):
                try:
                    item = await asyncio.wait_for(progress_q.get(), timeout=0.2)
                    yield item
                except asyncio.TimeoutError:
                    pass
            while not progress_q.empty():
                yield progress_q.get_nowait()

            # Collect results
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for gi, result in enumerate(results):
                group = slide_groups[gi]
                slugs_label = ", ".join(group["slugs"])
                if isinstance(result, Exception):
                    errors.append({"slugs": group["slugs"], "error": str(result)})
                    yield {"group": gi + 1, "slugs": slugs_label, "status": "error", "error": str(result)}
                else:
                    generated.extend(result["slugs"])
                    done_count += len(result["slugs"])
                    summaries[slugs_label] = result["response"]
                    yield {"group": gi + 1, "slugs": slugs_label, "status": "done", "done": done_count, "total": total}

        except Exception as e:
            errors.append({"slugs": "all", "error": str(e)})

        # Post-compose: build PPTX + assemble report
        yield {"status": "building", "message": "Building final PPTX..."}
        report = {"generated_slides": generated, "errors": errors, "summaries": summaries}

        if generated and mcp_client:
            import uuid

            # Generate PPTX
            try:
                build_result = mcp_client.call_tool_sync(
                    tool_use_id=f"build-{uuid.uuid4().hex[:8]}",
                    name="generate_pptx",
                    arguments={"deck_id": deck_id},
                )
                build_text = ""
                for item in build_result.get("content", []):
                    if isinstance(item, dict) and "text" in item:
                        build_text += item["text"]
                report["build"] = build_text
            except Exception as e:
                report["build_error"] = str(e)

            # Outline check: compare generated vs expected
            try:
                outline_result = mcp_client.call_tool_sync(
                    tool_use_id=f"outline-{uuid.uuid4().hex[:8]}",
                    name="run_python",
                    arguments={"code": "import json\noutline = open('specs/outline.md').read()\nimport re\nslugs = re.findall(r'^-\\s*\\[([a-z0-9-]+)\\]', outline, re.MULTILINE)\nprint(json.dumps(slugs))", "deck_id": deck_id},
                )
                for item in outline_result.get("content", []):
                    if isinstance(item, dict) and "text" in item:
                        try:
                            output = _json.loads(item["text"])
                            if isinstance(output, dict) and "output" in output:
                                expected = _json.loads(output["output"])
                            else:
                                expected = output
                            missing = [s for s in expected if s not in generated]
                            extra = [s for s in generated if s not in expected]
                            report["outline_check"] = {"expected": expected, "missing": missing, "extra": extra}
                        except _json.JSONDecodeError:
                            pass
            except Exception:
                pass

        yield _json.dumps(report)

    return compose_slides


# ---------------------------------------------------------------------------
# Agent Factory
# ---------------------------------------------------------------------------

# MCP server definitions: (factory, display_name, required)
_MCP_DEFS: list[tuple[str, bool]] = [
    ("Presentation Maker", True),
    ("AWS Knowledge", False),
    ("AWS Pricing", False),
]


def _collect_mcp_instructions(mcp_servers: list[MCPClient]) -> str:
    """Collect server_instructions from all MCP servers.

    Each MCPClient exposes server_instructions (str | None) after initialization.
    This function concatenates non-None instructions into a single string
    for injection into the system prompt.

    Args:
        mcp_servers: List of initialized MCPClient instances.

    Returns:
        Concatenated instructions string (may be empty if no server provides instructions).
    """
    sections: list[str] = []
    for client in mcp_servers:
        instr = client.server_instructions
        if instr:
            sections.append(instr)
    return "\n\n".join(sections)


def create_agent(user_id: str, session_id: str, jwt_token: str) -> tuple[Agent, list[dict]]:
    """Create a Strands Agent with MCP tools and memory.

    MCP servers are initialized first so that server_instructions can be
    collected and injected into the system prompt (MCP spec compliance).
    Optional MCP servers that fail to initialize are skipped.

    Args:
        user_id: User identifier (JWT sub claim).
        session_id: Conversation session ID.
        jwt_token: JWT access token for MCP Server authentication.

    Returns:
        Tuple of (Configured Strands Agent instance, MCP status list).
    """
    memory_id = os.environ.get("MEMORY_ID", "")
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

    # Set user_id for upload tools
    import tools.upload_tools as _ut
    _ut._current_user_id = user_id

    session_manager = None
    if memory_id and memory_id != "PLACEHOLDER":
        from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
        from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

        memory_config = AgentCoreMemoryConfig(
            memory_id=memory_id, session_id=session_id, actor_id=user_id,
        )
        session_manager = AgentCoreMemorySessionManager(
            agentcore_memory_config=memory_config, region_name=region,
        )

    model = BedrockModel(
        model_id=os.environ.get("MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        temperature=0.1,
        cache_config=CacheConfig(strategy="auto"),
    )

    composer_model = BedrockModel(
        model_id=os.environ.get("COMPOSER_MODEL_ID", os.environ.get("MODEL_ID", "global.anthropic.claude-sonnet-4-6")),
        temperature=0.1,
        cache_config=CacheConfig(strategy="auto"),
        boto_client_config=BotocoreConfig(user_agent_extra="strands-agents", read_timeout=30),
    )

    # --- Build MCP server list with resilience ---
    factories = [
        lambda: _mcp_agentcore_runtime(jwt_token=jwt_token),
        _mcp_aws_knowledge,
        _mcp_aws_pricing,
    ]

    mcp_servers: list[MCPClient] = []
    mcp_status: list[dict] = []

    for (name, required), factory in zip(_MCP_DEFS, factories):
        try:
            mcp_servers.append(factory())
            mcp_status.append({"name": name, "status": "ok"})
        except Exception as e:
            mcp_status.append({"name": name, "status": "error", "error": str(e)})
            if required:
                raise

    # Agent.__init__ triggers MCP client connections.
    # If optional MCP servers fail during init, retry with required-only.
    mcp_instructions = _collect_mcp_instructions(mcp_servers)
    compose_slides = _make_compose_slides(mcp_servers, composer_model, mcp_instructions)
    tools = [*mcp_servers, compose_slides, list_uploads, web_fetch]
    try:
        agent = Agent(
            name="SdpmSpecAgent",
            system_prompt="",
            tools=tools,
            model=model,
            session_manager=session_manager,
            trace_attributes={"user.id": user_id, "session.id": session_id},
        )
    except Exception as init_err:
        init_reason = str(init_err)
        logger.warning("Agent init failed with all MCP servers, retrying with required-only: %s", init_reason)
        # Keep only required MCP servers
        required_servers = []
        new_status = []
        for (name, required), st in zip(_MCP_DEFS, mcp_status):
            if required and st["status"] == "ok":
                required_servers.append(mcp_servers[len(new_status)])
                new_status.append(st)
            else:
                if st["status"] == "ok":
                    new_status.append({"name": name, "status": "error", "error": "Service unavailable"})
                else:
                    new_status.append(st)

        mcp_servers = required_servers
        mcp_status = new_status
        mcp_instructions = _collect_mcp_instructions(mcp_servers)
        compose_slides = _make_compose_slides(mcp_servers, composer_model, mcp_instructions)
        agent = Agent(
            name="SdpmSpecAgent",
            system_prompt="",
            tools=[*mcp_servers, compose_slides, list_uploads, web_fetch],
            model=model,
            session_manager=session_manager,
            trace_attributes={"user.id": user_id, "session.id": session_id},
        )

    # Now that MCP clients are initialized, inject their instructions.
    agent.system_prompt = _build_system_prompt(
        _SPEC_AGENT_PROMPT_TEMPLATE,
        mcp_instructions=mcp_instructions,
    )

    return agent, mcp_status


# ---------------------------------------------------------------------------
# Session fix
# ---------------------------------------------------------------------------


def _fix_excess_tool_results(messages: list) -> None:
    """Fix message list inconsistencies from interrupted sessions.

    Handles two cases:
    1. toolResult blocks with no matching toolUse in the previous assistant turn
       (orphaned results from interrupted sessions).
    2. Trailing assistant message with toolUse but no corresponding toolResult
       (interrupted mid-tool-execution — safety net, should not happen with
       safe cancellation points but protects against edge cases).

    Mutates messages in-place.

    Args:
        messages: The agent's message list (restored from session).
    """
    # --- Pass 1: Remove orphaned toolResult blocks ---
    i = 1
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") != "user":
            i += 1
            continue

        tool_results = [c for c in msg.get("content", []) if "toolResult" in c]
        if not tool_results:
            i += 1
            continue

        prev = messages[i - 1] if i > 0 else {}
        tool_use_ids = set()
        if prev.get("role") == "assistant":
            tool_use_ids = {
                c["toolUse"]["toolUseId"]
                for c in prev.get("content", [])
                if "toolUse" in c
            }

        original = msg["content"]
        msg["content"] = [
            c for c in original
            if "toolResult" not in c or c["toolResult"]["toolUseId"] in tool_use_ids
        ]

        if not msg["content"]:
            messages.pop(i)
        else:
            i += 1

    # --- Pass 2: Remove trailing assistant with unmatched toolUse ---
    if not messages:
        return
    last = messages[-1]
    if last.get("role") != "assistant":
        return
    has_tool_use = any("toolUse" in c for c in last.get("content", []))
    if not has_tool_use:
        return
    # Check if next message (doesn't exist — it's the last) has matching toolResults
    # Since it's the last message, there's no toolResult → remove it
    logger.info("Removing trailing assistant message with unmatched toolUse")
    messages.pop()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

KEEPALIVE_INTERVAL = 5

# Cancel registry: session_id → asyncio.Event.
# When a new request arrives for the same session, the previous request's
# Event is set, signalling it to stop at the next safe point.
_cancel_events: dict[str, asyncio.Event] = {}


@app.entrypoint
async def agent_stream(payload, context):
    """Main entrypoint for Amazon Bedrock AgentCore Runtime streaming invocation.

    Args:
        payload: Dict with prompt, userId, runtimeSessionId.
        context: RequestContext with request_headers (JWT forwarded by Runtime).

    Yields:
        Streaming events (Converse API format + keepalive).
    """
    user_query = payload.get("prompt")
    session_id = payload.get("runtimeSessionId")

    if not all([user_query, session_id]):
        yield {"status": "error", "error": "Missing required fields: prompt or runtimeSessionId"}
        return

    # Extract JWT from Authorization header (forwarded by Runtime via requestHeaderAllowList)
    auth_header = ""
    if hasattr(context, "request_headers") and context.request_headers:
        auth_header = context.request_headers.get("authorization", "") or context.request_headers.get("Authorization", "")
    jwt_token = auth_header.removeprefix("Bearer ").removeprefix("bearer ").strip()

    if not jwt_token:
        yield {"status": "error", "error": "No JWT token found in Authorization header"}
        return

    # Extract user_id from JWT sub (Runtime has already validated the token)
    import base64
    try:
        jwt_payload = jwt_token.split(".")[1]
        jwt_payload += "=" * (4 - len(jwt_payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(jwt_payload))
        user_id = claims.get("sub", "")
    except (IndexError, ValueError, json.JSONDecodeError):
        user_id = ""
    if not user_id:
        yield {"status": "error", "error": "Could not extract user_id from JWT sub claim"}
        return

    # --- Cancel previous request for the same session ---
    prev_cancel = _cancel_events.get(session_id)
    if prev_cancel is not None:
        prev_cancel.set()
        logger.info("Signalled previous request cancellation for session %s", session_id[:12])

    cancel = asyncio.Event()
    _cancel_events[session_id] = cancel

    try:
        os.environ["_CURRENT_SESSION_ID"] = session_id
        agent, mcp_status = create_agent(user_id=user_id, session_id=session_id, jwt_token=jwt_token)

        # Emit MCP status as the first SSE event
        yield {"mcp_status": mcp_status}

        _fix_excess_tool_results(agent.messages)

        async def _next(aiter):
            """Get next event from async iterator."""
            return await aiter.__anext__()

        stream_iter = agent.stream_async(user_query).__aiter__()
        pending = None
        last_tool_use = None
        last_tool_use_id = ""
        tool_name_map: dict[str, str] = {}  # toolUseId → tool name
        in_tool_execution = False  # True between toolUse emission and toolResult receipt

        def _tool_payload(tu: dict) -> dict:
            """Build toolUse SSE payload from accumulated tool use data."""
            import json as _json
            raw = tu.get("input", "")
            try:
                parsed = _json.loads(raw) if isinstance(raw, str) and raw else raw
            except (ValueError, TypeError):
                parsed = {}
            return {"toolUse": {"name": tu.get("name", ""), "toolUseId": tu.get("toolUseId", ""), "input": parsed if isinstance(parsed, dict) else {}}}

        def _should_stop() -> bool:
            """Check if cancellation was requested and it is safe to stop.

            Safe to stop when not in the middle of tool execution
            (between toolUse emission and toolResult receipt).

            Returns:
                True if the stream should be terminated.
            """
            return cancel.is_set() and not in_tool_execution

        while True:
            if pending is None:
                pending = asyncio.ensure_future(_next(stream_iter))
            done, _ = await asyncio.wait({pending}, timeout=KEEPALIVE_INTERVAL)
            if done:
                try:
                    event = pending.result()
                    if isinstance(event, dict) and "event" in event:
                        yield event
                    elif isinstance(event, dict) and "current_tool_use" in event:
                        tu = event["current_tool_use"]
                        tu_id = tu.get("toolUseId", "")
                        if tu_id and tu_id != last_tool_use_id:
                            if last_tool_use:
                                yield _tool_payload(last_tool_use)
                            last_tool_use_id = tu_id
                            tool_name_map[tu_id] = tu.get("name", "")
                            in_tool_execution = True
                            yield {"toolStart": {"name": tu.get("name", ""), "toolUseId": tu_id}}
                        last_tool_use = dict(tu)
                    elif isinstance(event, dict) and event.get("type") == "tool_result":
                        # ToolResultEvent — not yielded by stream_async (is_callback_event=False)
                        # Handled via ToolResultMessageEvent below instead
                        pass
                    elif isinstance(event, dict) and "tool_stream_event" in event:
                        tse = event["tool_stream_event"]
                        data = tse.get("data")
                        tu = tse.get("tool_use", {})
                        if isinstance(data, dict):
                            yield {"toolStream": {"toolUseId": tu.get("toolUseId", last_tool_use_id), "name": tu.get("name", ""), "data": data}}
                    elif isinstance(event, dict) and "message" in event:
                        msg = event["message"]
                        if isinstance(msg, dict) and msg.get("role") == "user":
                            for block in msg.get("content", []):
                                if isinstance(block, dict) and "toolResult" in block:
                                    tr = block["toolResult"]
                                    tu_id = tr.get("toolUseId", "")
                                    content_text = ""
                                    for c in tr.get("content", []):
                                        if isinstance(c, dict) and "text" in c:
                                            content_text = c["text"]
                                            break
                                    in_tool_execution = False
                                    yield {"toolResult": {
                                        "toolUseId": tu_id,
                                        "name": tool_name_map.get(tu_id, ""),
                                        "status": tr.get("status", "success"),
                                        "content": content_text,
                                    }}
                    pending = None

                    # Check cancellation at safe points
                    if _should_stop():
                        logger.info("Stopping stream for session %s", session_id[:12])
                        break

                except StopAsyncIteration:
                    if last_tool_use:
                        yield _tool_payload(last_tool_use)
                    break
            else:
                yield {"keepalive": True}
                # Also check cancellation during idle periods
                if _should_stop():
                    logger.info("Stopping stream (idle) for session %s", session_id[:12])
                    break

    except Exception as e:
        logger.exception("Agent stream error for session %s", session_id[:12])
        yield {"status": "error", "error": str(e)}
    finally:
        # Clean up cancel registry (only if we still own it)
        if _cancel_events.get(session_id) is cancel:
            del _cancel_events[session_id]


if __name__ == "__main__":
    app.run()
