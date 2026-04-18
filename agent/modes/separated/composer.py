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

from prompts import build_system_prompt, load_prompt

# References to prefetch for composer
_PREFETCH_SYSTEM = [
    ("read_workflows", {"names": ["create-new-2-compose"]}, "Compose Workflow"),
    ("read_workflows", {"names": ["slide-json-spec"]}, "Slide JSON Spec"),
]
_PREFETCH_REFS = [
    ("read_guides", {"names": ["grid"]}, "Grid Guide"),
    ("read_examples", {"names": ["components/all"]}, "Components Reference"),
    ("read_examples", {"names": ["patterns"]}, "Patterns Catalog"),
]


def _prefetch_sections(mcp_client, prefetch_list: list) -> list[str]:
    """Prefetch references from MCP server."""
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


def _build_common_context(sections: list[str]) -> str:
    """Build common reference context (shared across all groups, cacheable)."""
    if not sections:
        return ""
    return "# Pre-loaded References (already executed — do NOT re-fetch)\n\n" + "\n\n---\n\n".join(sections)


def _build_deck_context(sections: list[str]) -> str:
    """Build deck-specific context (varies per group, not cacheable)."""
    if not sections:
        return ""
    return "# Deck-Specific References\n\n" + "\n\n---\n\n".join(sections)


def make_compose_slides(mcp_servers: list, model):
    """Create compose_slides tool with closed-over MCP servers and model.

    Args:
        mcp_servers: List of MCPClient instances for the composer agent.
        model: BedrockModel instance.

    Returns:
        A @tool-decorated async generator function.
    """
    mcp_client = mcp_servers[0] if mcp_servers else None

    @strands_tool(
        name="compose_slides",
        description=(
            "Delegate slide generation to parallel composer agents. Each group "
            "is handled by an independent composer that writes slides/<slug>.json. "
            "Use this once Phase 1 (dialogue) is complete and outline.md is finalized.\n\n"
            "Group slides that share visual/narrative context (e.g., same chapter, "
            "same data source) so one composer can design them cohesively. Split "
            "groups to unlock parallelism — each group runs concurrently "
            "(up to COMPOSER_MAX_CONCURRENCY, default 10).\n\n"
            "The `instruction` is the composer's sole guidance: be concrete. "
            "Include narrative intent, tone, required data/facts, layout hints, "
            "and any figure/icon references. Do not omit content expecting the "
            "composer to infer it — it cannot see the full conversation."
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
                            "one composer agent. Keep related slides together (shared "
                            "narrative, data, or visual style). Typical group size: 1–4 slides."
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
                                        "Detailed composition brief for this group's composer. Include:\n"
                                        "  • Narrative purpose — why these slides exist in the deck\n"
                                        "  • Concrete content — facts, numbers, quotes, examples to include\n"
                                        "  • Tone/style — formal, casual, technical, persuasive\n"
                                        "  • Layout hints — hero stat, comparison table, timeline, code block, etc.\n"
                                        "  • Visual assets — icons, images, charts the composer should search for\n"
                                        "  • Cross-slide continuity — how this group connects to adjacent slides\n"
                                        "Avoid vague directives like 'make it nice'. The composer cannot see "
                                        "the original conversation; the instruction must stand alone."
                                    ),
                                    "minLength": 40,
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
    async def compose_slides(deck_id: str, slide_groups: list):
        """Compose slides by delegating to composer agents.

        Prefetches all Phase 2 references once, then injects into composer prompt.
        Runs groups in parallel. Async generator: yields progress dicts, then returns final result str.
        """
        max_concurrency = int(os.environ.get("COMPOSER_MAX_CONCURRENCY", "10"))

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

            system_context = _build_common_context(system_sections)
            composer_template = load_prompt("composer")
            static_prompt = build_system_prompt(
                composer_template,
                common_context=system_context,
                deck_id=deck_id,
            )

            common_ref_text = _build_common_context(ref_sections)

            progress_q: queue.Queue = queue.Queue()

            def run_group(gi: int, group: dict) -> dict:
                """Run a single composer group in a thread."""
                slugs_label = ", ".join(group["slugs"])
                progress_q.put_nowait({"group": gi + 1, "total_groups": len(slide_groups), "slugs": slugs_label, "status": "starting"})

                deck_sections = _prefetch_deck_specs(mcp_client, deck_id, group["slugs"]) if mcp_client else []
                deck_context = _build_deck_context(deck_sections)

                slugs_list = ", ".join(f"slides/{s}.json" for s in group["slugs"])
                user_content = (
                    f"{common_ref_text}\n\n---\n\n{deck_context}\n\n---\n\n"
                    f"## Your Assigned Slides\n"
                    f"You may ONLY write to: {slugs_list}\n"
                    f"Do NOT write to any other slides/*.json — other composers own them.\n\n"
                    f"{group['instruction']}"
                )

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

                composer = Agent(
                    system_prompt=[
                        {"text": static_prompt},
                        {"cachePoint": {"type": "default"}},
                    ],
                    tools=[*mcp_servers],
                    model=model,
                    callback_handler=_on_event,
                )

                async def _before_tool(event: BeforeToolCallEvent):
                    tu = event.tool_use
                    progress_q.put_nowait({
                        "group": gi + 1, "slugs": slugs_label,
                        "tool": tu.get("name", ""), "toolUseId": tu.get("toolUseId", ""),
                        "input": tu.get("input", {}),
                    })

                async def _after_tool(event: AfterToolCallEvent):
                    tu = event.tool_use
                    is_err = isinstance(event.result, dict) and event.result.get("status") == "error"
                    progress_q.put_nowait({
                        "group": gi + 1, "slugs": slugs_label,
                        "toolResult": tu.get("toolUseId", ""),
                        "toolStatus": "error" if is_err else "success",
                    })

                composer.hooks.add_callback(BeforeToolCallEvent, _before_tool)
                composer.hooks.add_callback(AfterToolCallEvent, _after_tool)

                max_retries = 2
                for attempt in range(max_retries + 1):
                    try:
                        response = composer(user_content if attempt == 0 else None)
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

            # Launch all groups in thread pool
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
        report = {"generated_slides": generated, "errors": errors, "summaries": summaries}

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
