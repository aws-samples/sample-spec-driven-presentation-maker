# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Composer agent: compose_slides tool with parallel execution, prefetch, and post-build."""

import json
import os
import queue
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from strands import Agent, tool as strands_tool
from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent
from strands.types.tools import ToolContext

from prompts import build_system_prompt, load_prompt


# Soft-stop signal: the webui cancel button sends InvokeAgentRuntimeCommand
# to `touch /tmp/compose_stops/{parent_tool_use_id}` inside this microVM.
# The BeforeToolCallEvent hook polls for that file and, on hit, feeds the
# STOP_PROMPT to the LLM as the cancelled tool's result so the composer
# winds down with a plain-text partial summary.
_STOP_SIGNAL_DIR = "/tmp/compose_stops"
# NOTE: Do NOT include markers like "[SYSTEM INTERRUPT]" or phrases such as
# "the user has requested" here. Claude's anti-prompt-injection heuristic
# flags those as hijack attempts coming from tool output and ignores them —
# the composer then keeps calling tools. A plain, tool-layer-style message
# is honoured on the first hit and the agent wraps up naturally.
STOP_PROMPT = (
    "Operation cancelled by the user. Do not retry. "
    "Stop invoking tools and respond with a brief plain-text summary of "
    "what was completed, what was in progress, and any context useful for resuming later."
)

# Time budget per slide — when exceeded, nudge the composer to wrap up polishing
# and finish any unwritten slides. Injected into tool results (non-disruptive).
_SECONDS_PER_SLIDE = int(os.environ.get("COMPOSER_SECONDS_PER_SLIDE", "90"))
BUDGET_PROMPT = (
    "Time budget reached. If any assigned slides are still unwritten, "
    "finish them with a rough-but-coherent draft. "
    "Do NOT polish slides that are already written — stop measuring and refining. "
    "Do NOT call generate_pptx or get_preview — they are slow polish tools. "
    "If a tool just failed, do NOT retry the same call — accept a rough draft "
    "for that slide and move on. "
    "Once all slides exist, respond with a brief summary noting what is done "
    "and what could use another pass."
)

# Stop a composer that is stuck in a failure loop. After this many consecutive
# tool errors, the next tool call is cancelled and the LLM is told to stop and
# summarize instead of retrying further.
ERROR_LIMIT = 5
ERROR_LIMIT_PROMPT = (
    "Tool calls have failed 5 times in a row. "
    "Further attempts are unlikely to succeed — stop calling tools. "
    "Respond with a plain-text summary: which slides were completed, "
    "which failed, and the last error you saw."
)


def _is_compose_stopped(parent_tool_use_id: str) -> bool:
    try:
        return os.path.exists(os.path.join(_STOP_SIGNAL_DIR, parent_tool_use_id))
    except Exception:
        return False

# References to prefetch for composer
_PREFETCH_SYSTEM = [
    ("read_workflows", {"names": ["create-new-2-compose"]}, "create-new-2-compose"),
    ("read_workflows", {"names": ["slide-json-spec"]}, "slide-json-spec"),
]
_PREFETCH_REFS = [
    ("read_guides", {"names": ["grid"]}, "grid"),
    ("read_examples", {"names": ["components/all"]}, "components/all"),
    ("read_examples", {"names": ["patterns"]}, "patterns"),
]


# Canonical implementation lives in factory.py — import for backward compat
from factory import prefetch_sections as _prefetch_sections  # noqa: E402


def _prefetch_deck_specs(mcp_client, deck_id: str, assigned_slugs: list[str]) -> list[str]:
    """Prefetch deck-specific specs and assigned slide contents."""
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
                output = json.loads(item["text"])
                if isinstance(output, dict) and "output" in output:
                    output = json.loads(output["output"])
                if not isinstance(output, dict) or not output:
                    raise RuntimeError(f"Specs empty for deck {deck_id} — workspace may not exist")
                for filename, content in output.items():
                    sections.append(f"## {filename}\n\n{content}")
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Failed to parse specs for deck {deck_id}: {e}") from e
    return sections


# Canonical implementation lives in factory.py — import for backward compat
from factory import build_common_context as _build_common_context  # noqa: E402


def _build_deck_context(sections: list[str]) -> str:
    """Build deck-specific context (varies per group, not cacheable)."""
    if not sections:
        return ""
    return "# Deck-Specific References\n\n" + "\n\n---\n\n".join(sections)


def make_compose_slides(mcp_servers: list, model, composer_mcp_factory=None):
    """Create compose_slides tool with closed-over MCP servers and model.

    Args:
        mcp_servers: List of MCPClient instances exposed as composer tools.
        model: BedrockModel instance.
        composer_mcp_factory: Optional callable returning a fresh MCPClient for
            prefetch/per-group isolation. If None, falls back to mcp_servers[0]
            (legacy shared-client behavior).

    Returns:
        A @tool-decorated async generator function.
    """
    mcp_client = mcp_servers[0] if mcp_servers else None
    max_concurrency = int(os.environ.get("COMPOSER_MAX_CONCURRENCY", "10"))

    @strands_tool(
        name="compose_slides",
        context=True,
        description=(
            "Delegate slide generation to parallel composer agents. Each group "
            "is handled by an independent composer that writes slides/<slug>.json. "
            f"Up to {max_concurrency} groups run concurrently. "
            "Use this once Phase 1 (dialogue) is complete and outline.md is finalized.\n\n"
            "The composer reads specs/ (brief, outline, art-direction) for all content "
            "and design decisions. The instruction only needs to specify which slides "
            "to compose. Add user requests or review feedback if applicable, but do NOT "
            "invent layout or design directives — the composer makes those decisions."
        ),
        inputSchema={
            "json": {
                "type": "object",
                "properties": {
                    "deck_id": {
                        "type": "string",
                        "description": "Deck ID for the presentation workspace (e.g. 'abc12345').",
                    },
                    "slide_groups": {
                        "type": "array",
                        "description": (
                            "Groups of slides to compose in parallel. Each group becomes "
                            "one composer agent."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "slugs": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": (
                                        "Slugs of slides this group's composer will write. "
                                        "Must match slugs declared in outline.md. "
                                        "Example: ['intro', 'agenda']."
                                    ),
                                    "minItems": 1,
                                },
                                "instruction": {
                                    "type": "string",
                                    "description": (
                                        "Instruction for the composer. Keep minimal:\n"
                                        "  • Initial generation: 'Compose these slides following specs/'\n"
                                        "  • User requests: pass through the user's words as-is\n"
                                        "  • Review fixes: describe the problem, not the solution "
                                        "(e.g. 'slides X and Y lack visual consistency' not 'use timeline layout')\n"
                                        "Do NOT add layout, design, or style directives on your own — "
                                        "the composer has design expertise and reads art-direction.html."
                                    ),
                                },
                            },
                            "required": ["slugs", "instruction"],
                        },
                        "minItems": 1,
                    },
                },
                "required": ["deck_id", "slide_groups"],
            }
        },
    )
    async def compose_slides(deck_id: str, slide_groups: list, tool_context: ToolContext):
        """Compose slides by delegating to composer agents.

        Prefetches all Phase 2 references once, then injects into composer prompt.
        Runs groups in parallel. Async generator: yields progress dicts, then returns final result str.
        """
        parent_tool_use_id = tool_context.tool_use["toolUseId"]

        generated = []
        errors = []
        summaries = {}
        total = sum(len(g["slugs"]) for g in slide_groups)
        done_count = 0

        try:
            # Prefetch references once
            yield {"status": "prefetching", "message": "Loading references..."}
            system_sections = _prefetch_sections(mcp_client, _PREFETCH_SYSTEM) if mcp_client else []
            ref_sections = _prefetch_sections(mcp_client, _PREFETCH_REFS) if mcp_client else []

            system_context = _build_common_context(system_sections + ref_sections)
            composer_template = load_prompt("composer")
            static_prompt = build_system_prompt(
                composer_template,
                common_context=system_context,
            )

            progress_q: queue.Queue = queue.Queue()

            # Prefetch template analysis once (shared across all groups)
            template_analysis = ""
            if mcp_client:
                try:
                    probe = mcp_client.call_tool_sync(
                        tool_use_id=f"prefetch-{uuid.uuid4().hex[:8]}",
                        name="run_python",
                        arguments={
                            "code": "import json; print(json.load(open('deck.json')).get('template',''))",
                            "deck_id": deck_id,
                        },
                    )
                    tmpl_name = ""
                    for item in probe.get("content", []):
                        if isinstance(item, dict) and "text" in item:
                            out = json.loads(item["text"])
                            tmpl_name = (out.get("output", "") if isinstance(out, dict) else str(out)).strip()
                    if tmpl_name:
                        tmpl_result = mcp_client.call_tool_sync(
                            tool_use_id=f"prefetch-{uuid.uuid4().hex[:8]}",
                            name="analyze_template",
                            arguments={"template": tmpl_name},
                        )
                        for item in tmpl_result.get("content", []):
                            if isinstance(item, dict) and "text" in item:
                                template_analysis = f"## Template Analysis: {tmpl_name}\n\n{item['text']}"
                except Exception:
                    pass

            def run_group(gi: int, group: dict) -> dict:
                """Run a single composer group in a thread."""
                slugs_label = ", ".join(group["slugs"])
                # Early exit: cancelled before we even started
                if _is_compose_stopped(parent_tool_use_id):
                    return {"slugs": [], "response": "skipped (cancelled)"}
                progress_q.put_nowait({"group": gi + 1, "total_groups": len(slide_groups), "slugs": slugs_label, "status": "starting"})

                deck_sections = _prefetch_deck_specs(mcp_client, deck_id, group["slugs"]) if mcp_client else []
                deck_context = _build_deck_context(deck_sections)

                slugs_list = ", ".join(f"slides/{s}.json" for s in group["slugs"])
                tmpl_section = (
                    f"{template_analysis}\n\n"
                    f"When choosing layouts and referring to the template, "
                    f"use the layout names and other information above as the source of truth.\n\n---\n\n"
                ) if template_analysis else ""
                user_content = (
                    f"{deck_context}\n\n---\n\n"
                    f"{tmpl_section}"
                    f"## Target Deck\n"
                    f"deck_id: {deck_id}\n"
                    f"Use this deck_id for ALL run_python and generate_pptx calls.\n\n"
                    f"## Your Assigned Slides\n"
                    f"You may ONLY write to: {slugs_list}\n"
                    f"Do NOT write to any other slides/*.json — other composers own them.\n\n"
                    f"{group['instruction']}"
                )

                # Time budget: slug_count * seconds-per-slide. Periodic nudge (1st then every 3rd) to stop polishing.
                deadline = time.time() + len(group["slugs"]) * _SECONDS_PER_SLIDE
                budget_nudge_count = 0
                consecutive_errors = 0

                last_tool_id = ""
                last_input_by_tid: dict[str, dict] = {}

                def _on_event(**kwargs):
                    nonlocal last_tool_id
                    tu = kwargs.get("current_tool_use")
                    if tu:
                        tid = tu.get("toolUseId", "")
                        name = tu.get("name", "")
                        if not tid or not name:
                            return
                        if tid != last_tool_id:
                            last_tool_id = tid
                            progress_q.put_nowait({"group": gi + 1, "slugs": slugs_label, "tool": name, "toolUseId": tid})
                        # Early-emit input once it becomes JSON-parseable
                        raw = tu.get("input", "")
                        parsed: dict | None = None
                        if isinstance(raw, dict) and raw:
                            parsed = raw
                        elif isinstance(raw, str) and raw:
                            try:
                                p = json.loads(raw)
                                if isinstance(p, dict):
                                    parsed = p
                            except (ValueError, TypeError):
                                parsed = None
                        if parsed and parsed != last_input_by_tid.get(tid):
                            last_input_by_tid[tid] = parsed
                            progress_q.put_nowait({"group": gi + 1, "slugs": slugs_label, "tool": name, "toolUseId": tid, "input": parsed})

                # Per-group MCP isolation: create a fresh MCPClient scoped to this
                # group so a session death cannot cascade to other groups. Started
                # here and stopped in finally after the composer run completes.
                _group_mcp = composer_mcp_factory() if composer_mcp_factory else None
                _group_tools = list(mcp_servers)
                if _group_mcp is not None:
                    _group_tools[0] = _group_mcp  # replace Presentation Maker MCP

                composer = Agent(
                    system_prompt=[
                        {"text": static_prompt},
                        {"cachePoint": {"type": "default"}},
                    ],
                    tools=_group_tools,
                    model=model,
                    callback_handler=_on_event,
                )

                async def _before_tool(event: BeforeToolCallEvent):
                    # Soft-stop: if the user cancelled this compose_slides
                    # invocation, hand the LLM the STOP_PROMPT instead of
                    # executing the tool. The model is instructed to emit a
                    # plain-text partial summary and stop calling tools, so
                    # the composer loop terminates naturally.
                    if _is_compose_stopped(parent_tool_use_id):
                        event.cancel_tool = STOP_PROMPT
                        return
                    if consecutive_errors >= ERROR_LIMIT:
                        event.cancel_tool = ERROR_LIMIT_PROMPT
                        return
                    tu = event.tool_use
                    progress_q.put_nowait({
                        "group": gi + 1, "slugs": slugs_label,
                        "tool": tu.get("name", ""), "toolUseId": tu.get("toolUseId", ""),
                        "input": tu.get("input", {}),
                    })

                async def _after_tool(event: AfterToolCallEvent):
                    tu = event.tool_use
                    is_err = isinstance(event.result, dict) and event.result.get("status") == "error"
                    # Time-budget nudge: append BUDGET_PROMPT periodically to keep
                    # the composer reminded. Injected into both success and error
                    # tool results (same text for both — LLM selects the relevant
                    # guidance from context). 1st hit + every 3rd after.
                    nonlocal budget_nudge_count
                    if time.time() > deadline:
                        budget_nudge_count += 1
                        if budget_nudge_count == 1 or budget_nudge_count % 3 == 0:
                            if isinstance(event.result, dict):
                                content = list(event.result.get("content") or [])
                                content.append({"text": f"\n\n[Budget notice] {BUDGET_PROMPT}"})
                                event.result = {**event.result, "content": content}
                        if budget_nudge_count == 1:
                            progress_q.put_nowait({
                                "group": gi + 1, "slugs": slugs_label,
                                "status": "budget_reached",
                            })
                    # Consecutive tool-error tripwire: after ERROR_LIMIT failures
                    # in a row, the next _before_tool call will cancel the tool
                    # and hand the LLM ERROR_LIMIT_PROMPT. Success resets.
                    nonlocal consecutive_errors
                    if is_err:
                        consecutive_errors += 1
                        if consecutive_errors == ERROR_LIMIT:
                            progress_q.put_nowait({
                                "group": gi + 1, "slugs": slugs_label,
                                "status": "error_limit",
                            })
                    else:
                        consecutive_errors = 0
                    progress_q.put_nowait({
                        "group": gi + 1, "slugs": slugs_label,
                        "toolResult": tu.get("toolUseId", ""),
                        "toolStatus": "error" if is_err else "success",
                    })

                composer.hooks.add_callback(BeforeToolCallEvent, _before_tool)
                composer.hooks.add_callback(AfterToolCallEvent, _after_tool)

                # Hard-stop guard: cancels the composer agent if tool loop/cap
                # is detected (complements the soft ERROR_LIMIT_PROMPT nudge).
                from resilience import LoopGuard
                guard = LoopGuard(
                    max_tool_calls=int(os.environ.get("COMPOSER_MAX_TOOL_CALLS", "150")),
                )
                composer.hooks.add_callback(AfterToolCallEvent, guard.after_tool)

                max_retries = 2
                try:
                    for attempt in range(max_retries + 1):
                        try:
                            response = composer(user_content if attempt == 0 else None)
                            if guard.cancelled:
                                progress_q.put_nowait({
                                    "group": gi + 1, "slugs": slugs_label,
                                    "status": "guard_stopped", "reason": guard.cancel_reason,
                                })
                                return {"slugs": group["slugs"], "response": f"stopped: {guard.cancel_reason}"}
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
                finally:
                    # Release the per-group MCPClient's background thread.
                    if _group_mcp is not None:
                        try:
                            _group_mcp.stop(None, None, None)
                        except Exception:
                            logger.warning("group MCP stop failed", exc_info=True)

            # Launch all groups in thread pool (skip if already cancelled during prefetch)
            if _is_compose_stopped(parent_tool_use_id):
                pass  # fall through to report assembly with status: cancelled
            else:
                with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
                    futures = {pool.submit(run_group, gi, g): gi for gi, g in enumerate(slide_groups)}

                    while futures:
                        while not progress_q.empty():
                            try:
                                yield progress_q.get_nowait()
                            except queue.Empty:
                                break

                        done_futures = [f for f in futures if f.done()]
                        for f in done_futures:
                            gi = futures.pop(f)
                            group = slide_groups[gi]
                            slugs_label = ", ".join(group["slugs"])
                            try:
                                result = f.result()
                                generated.extend(result["slugs"])
                                done_count += len(result["slugs"])
                                summaries[slugs_label] = result["response"]
                                yield {"group": gi + 1, "slugs": slugs_label, "status": "done", "done": done_count, "total": total}
                            except Exception as e:
                                errors.append({"slugs": group["slugs"], "error": str(e)})
                                yield {"group": gi + 1, "slugs": slugs_label, "status": "error", "error": str(e)}

                        if futures:
                            time.sleep(0.2)

            while not progress_q.empty():
                try:
                    yield progress_q.get_nowait()
                except queue.Empty:
                    break

        except Exception as e:
            failed_slugs = [s for g in slide_groups for s in g["slugs"] if s not in generated]
            errors.append({
                "slugs": failed_slugs,
                "error": str(e),
                "phase": "prefetch" if not generated else "compose",
            })

        # Post-compose: build PPTX + assemble report
        yield {"status": "building", "message": "Building final PPTX..."}
        cancelled = _is_compose_stopped(parent_tool_use_id)
        report = {
            "status": "cancelled" if cancelled else "completed",
            "generated_slides": generated,
            "errors": errors,
            "summaries": summaries,
        }
        if cancelled:
            report["notice"] = (
                "Stopped by user cancellation. Do NOT retry automatically — "
                "ask the user how to proceed (resume, adjust scope, or abandon)."
            )

        if generated and mcp_client:
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

            # Outline check
            try:
                outline_result = mcp_client.call_tool_sync(
                    tool_use_id=f"outline-{uuid.uuid4().hex[:8]}",
                    name="run_python",
                    arguments={
                        "code": (
                            "import json, re\n"
                            "outline = open('specs/outline.md').read()\n"
                            "slugs = re.findall(r'^-\\s*\\[([a-z0-9-]+)\\]', outline, re.MULTILINE)\n"
                            "print(json.dumps(slugs))"
                        ),
                        "deck_id": deck_id,
                    },
                )
                for item in outline_result.get("content", []):
                    if isinstance(item, dict) and "text" in item:
                        try:
                            output = json.loads(item["text"])
                            if isinstance(output, dict) and "output" in output:
                                expected = json.loads(output["output"])
                            else:
                                expected = output
                            missing = [s for s in expected if s not in generated]
                            extra = [s for s in generated if s not in expected]
                            report["outline_check"] = {"expected": expected, "missing": missing, "extra": extra}
                        except json.JSONDecodeError:
                            pass
            except Exception:
                pass

        yield json.dumps(report)

    return compose_slides
