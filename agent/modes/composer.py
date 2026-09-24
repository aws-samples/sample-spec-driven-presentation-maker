# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Composer agent: compose_slides tool with parallel execution, prefetch, and post-build."""

import json
import logging
import os
import queue
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from strands import Agent, tool as strands_tool
from strands.hooks.events import AfterInvocationEvent, AfterToolCallEvent, BeforeToolCallEvent
from strands.types.tools import ToolContext

from composition import resolve_parts
from cost_logger import log_slides_composed, log_usage
from message_hooks import LiftToolResultImages
from modes import MODES  # imported lazily in compose_slides if needed
from resilience import call_tool_with_retry

logger = logging.getLogger("sdpm.agent")


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


def _start_composing(mcp_client, deck_id: str, assigned_slugs: list[str]) -> dict:
    """Call the composer's entry tool and return its ``deck`` part.

    The same call an interactive composer makes first; here it is made on the
    composer's behalf and replayed into its history as a tool result, so the
    composer starts with its inputs already in hand (see sdpm.entry).
    """
    result = call_tool_with_retry(
        mcp_client,
        tool_use_id=f"prefetch-{uuid.uuid4().hex[:8]}",
        name="start_composing",
        arguments={"deck_id": deck_id, "assigned_slugs": assigned_slugs},
    )
    if result.get("status") == "error":
        raise RuntimeError(f"start_composing failed for deck {deck_id}: {result.get('content')}")
    for item in result.get("content", []):
        if isinstance(item, dict) and "text" in item:
            payload = json.loads(item["text"])
            if not payload.get("specs_ok", payload.get("deck", {}).get("specs_ok")):
                raise RuntimeError(
                    f"specs rejected for deck {deck_id}: {'; '.join(payload.get('errors') or [])}"
                )
            return payload["deck"]
    raise RuntimeError(f"start_composing returned no payload for deck {deck_id}")


def _replay_start_composing(deck_id: str, assigned_slugs: list[str], deck: dict) -> list[dict]:
    """assistant toolUse + user toolResult pair for a start_composing call already made."""
    tool_use_id = f"prefill-{uuid.uuid4().hex[:8]}"
    return [
        {
            "role": "assistant",
            "content": [
                {"text": "I'll start by loading my assignment."},
                {"toolUse": {
                    "toolUseId": tool_use_id,
                    "name": "start_composing",
                    "input": {"deck_id": deck_id, "assigned_slugs": assigned_slugs},
                }},
            ],
        },
        {
            "role": "user",
            "content": [{"toolResult": {
                "toolUseId": tool_use_id,
                "content": [{"text": json.dumps({"deck": deck}, ensure_ascii=False)}],
                "status": "success",
            }}],
        },
    ]


def make_compose_slides(mcp_servers: list, model, composer_mcp_factory=None, extra_tools=None, model_id: str = "", user_id: str = "", session_id: str = ""):
    """Create compose_slides tool with closed-over MCP servers and model.

    Args:
        mcp_servers: List of MCPClient instances exposed as composer tools.
        model: BedrockModel instance.
        composer_mcp_factory: Optional callable returning a fresh MCPClient for
            prefetch/per-group isolation. Accepts the Mcp-Session-Id to use, so
            each group gets its own microVM while keeping that id stable across
            composes. If None, falls back to mcp_servers[0]
            (legacy shared-client behavior).
        extra_tools: Optional list of additional tools (e.g. web_fetch) to give composers.
        user_id: Cognito user ID, propagated to composer trace attributes and
            usage logs for per-user measurement.
        session_id: Runtime session ID, propagated alongside user_id.
    """
    _extra_tools = extra_tools or []
    mcp_client = mcp_servers[0] if mcp_servers else None
    max_concurrency = int(os.environ.get("COMPOSER_MAX_CONCURRENCY", "10"))

    @strands_tool(
        name="compose_slides",
        context=True,
        description=(
            "Dispatch composer agents for the groups given — one independent composer "
            "per group, writing slides/<slug>.json. Runs only what you pass: the layout "
            "pass and the content pass are separate calls. "
            f"Up to {max_concurrency} groups run concurrently. "
            "Use this once outline.md is finalized.\n\n"
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
                                        "  • Layout pass (first call, one group, all slugs): 'Layout pass.'\n"
                                        "  • Content: 'Compose these slides following specs/'\n"
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

        Loads the canonical composer workflow, then injects deck-specific context.
        Runs groups in parallel. Async generator: yields progress dicts, then returns final result str.
        """
        # LLM sometimes passes slide_groups as a JSON string instead of a list
        if isinstance(slide_groups, str):
            slide_groups = json.loads(slide_groups)
        parent_tool_use_id = tool_context.tool_use["toolUseId"]

        # Validate the deck specification once before launching composers.
        spec_warnings: list[str] = []
        outline_slugs: list[str] = []
        if mcp_client:
            assigned_slugs = [slug for group in slide_groups for slug in group["slugs"]]
            check_result = call_tool_with_retry(
                mcp_client,
                tool_use_id=f"precheck-{uuid.uuid4().hex[:8]}",
                name="check_specs",
                arguments={"deck_id": deck_id, "assigned_slugs": assigned_slugs},
            )
            spec_result: dict = {
                "ok": False,
                "errors": ["check_specs returned no validation result"],
                "warnings": [],
                "slugs": [],
            }
            for item in check_result.get("content", []):
                if isinstance(item, dict) and "text" in item:
                    try:
                        parsed = json.loads(item["text"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(parsed, dict):
                        spec_result = parsed
                        break

            spec_warnings = list(spec_result.get("warnings") or [])
            outline_slugs = list(spec_result.get("slugs") or [])
            if not spec_result.get("ok"):
                yield json.dumps({
                    "status": "error",
                    "errors": list(spec_result.get("errors") or []),
                    "warnings": spec_warnings,
                    "instruction": (
                        "Cannot compose: fix the listed spec problems, then call "
                        "compose_slides again."
                    ),
                })
                return

        generated = []
        errors = []
        summaries = {}
        total = sum(len(g["slugs"]) for g in slide_groups)
        done_count = 0

        try:
            # Prefetch static composer parts (role prompt + refs) via composition
            yield {"status": "prefetching", "message": "Loading references..."}
            composer_cfg = MODES["composer"]
            composer_system, composer_history = resolve_parts(
                composer_cfg.parts, mcp_client=mcp_client, context={}
            )
            static_prompt = composer_system

            # Determine if the composer model supports prompt caching
            from model_profiles import MODEL_PROFILES
            _profile = MODEL_PROFILES.get(model_id)
            _cache_enabled = (_profile.cache_strategy == "auto") if _profile else True

            progress_q: queue.Queue = queue.Queue()

            def run_group(gi: int, group: dict) -> dict:
                """Run a single composer group in a thread."""
                slugs_label = ", ".join(group["slugs"])
                # Early exit: cancelled before we even started
                if _is_compose_stopped(parent_tool_use_id):
                    return {"slugs": [], "response": "skipped (cancelled)"}
                progress_q.put_nowait({"group": gi + 1, "total_groups": len(slide_groups), "slugs": slugs_label, "status": "starting"})

                # The composer's history opens like an interactive composer's session:
                # the spawn instruction, then its own start_composing call with the
                # deck payload as the result. The run continues from there.
                deck_part = _start_composing(mcp_client, deck_id, group["slugs"]) if mcp_client else {}
                opening: list[dict] = [{
                    "role": "user",
                    "content": [{"text": (
                        f"deck_id: {deck_id}\n"
                        f"assigned_slugs: {', '.join(group['slugs'])}\n"
                        f"task_instruction: {group['instruction']}"
                    )}],
                }]
                if deck_part:
                    opening.extend(_replay_start_composing(deck_id, group["slugs"], deck_part))

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
                #
                # The group index is part of the Mcp-Session-Id so that AgentCore
                # still hands each group its own microVM (sharing one id across
                # groups would route them all to the same microVM and defeat the
                # isolation above, while they run in parallel). Keeping the id
                # stable per group means a repeat compose in the same user session
                # reuses that group's microVM instead of starting a new one.
                _group_session_id = f"{session_id}-g{gi + 1}" if session_id else ""
                _group_mcp = composer_mcp_factory(_group_session_id) if composer_mcp_factory else None
                _group_tools = list(mcp_servers)
                if _group_mcp is not None:
                    _group_tools[0] = _group_mcp  # replace Presentation Maker MCP
                _group_tools.extend(_extra_tools)

                composer = Agent(
                    system_prompt=[
                        {"text": static_prompt},
                        *([ {"cachePoint": {"type": "default"}} ] if _cache_enabled else []),
                    ],
                    messages=[*composer_history, *opening],
                    tools=_group_tools,
                    model=model,
                    callback_handler=_on_event,
                    hooks=[LiftToolResultImages()],
                    trace_attributes={
                        "user.id": user_id,
                        "session.id": session_id,
                        "deck.id": deck_id,
                        "group.index": gi,
                        "group.slugs": ",".join(group["slugs"]),
                        "model.id": model_id,
                        "purpose": "compose",
                    },
                )
                composer.hooks.add_callback(AfterInvocationEvent, log_usage)

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
                            response = composer(None)  # continue from the opening history
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
                                errors.append({
                                    "group_index": gi + 1,
                                    "slugs": group["slugs"],
                                    "instruction": group.get("instruction", ""),
                                    "error": str(e),
                                })
                                yield {"group": gi + 1, "slugs": slugs_label, "status": "error", "error": str(e)}

                        if futures:
                            time.sleep(0.2)

            while not progress_q.empty():
                try:
                    yield progress_q.get_nowait()
                except queue.Empty:
                    break

        except Exception as e:
            # Infrastructure failure (prefetch etc.) — record each unfinished
            # group separately so they stay individually retryable.
            phase = "prefetch" if not generated else "compose"
            for gi, g in enumerate(slide_groups):
                remaining = [s for s in g["slugs"] if s not in generated]
                if remaining:
                    errors.append({
                        "group_index": gi + 1,
                        "slugs": remaining,
                        "instruction": g.get("instruction", ""),
                        "error": str(e),
                        "phase": phase,
                    })

        # Post-compose: build PPTX + assemble report
        yield {"status": "building", "message": "Building final PPTX..."}
        cancelled = _is_compose_stopped(parent_tool_use_id)
        partial = bool(errors) and bool(generated)
        report = {
            "status": "cancelled" if cancelled else ("partial" if partial else ("failed" if errors else "completed")),
            "generated_slides": generated,
            "failed_groups": errors,
            "partial": partial,
            "summaries": summaries,
        }
        if spec_warnings:
            report["spec_warnings"] = spec_warnings
        log_slides_composed(
            user_id=user_id, session_id=session_id, deck_id=deck_id,
            generated=len(generated), total=total, status=report["status"],
        )
        if cancelled:
            report["notice"] = (
                "Stopped by user cancellation. Do NOT retry automatically — "
                "ask the user how to proceed (resume, adjust scope, or abandon)."
            )
        elif errors:
            failed_slugs = sorted({s for e in errors for s in e["slugs"]})
            report["notice"] = (
                f"{len(generated)}/{total} slides were generated; groups covering "
                f"{failed_slugs} failed. Successfully generated slides do NOT need "
                "regeneration. Tell the user which slides failed and why, and offer "
                "to retry — on retry, call compose_slides again with ONLY the failed "
                "groups (reuse each group's slugs and instruction from failed_groups)."
            )

        if generated and mcp_client:
            # Generate PPTX
            try:
                build_result = call_tool_with_retry(
                    mcp_client,
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

            # Compare generated slides with the already-validated outline slugs.
            missing = [slug for slug in outline_slugs if slug not in generated]
            extra = [slug for slug in generated if slug not in outline_slugs]
            report["outline_check"] = {
                "expected": outline_slugs,
                "missing": missing,
                "extra": extra,
            }

        yield json.dumps(report)

    return compose_slides
