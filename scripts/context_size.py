# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Measure the text sdpm puts in front of a model, per item and per session bundle.

    uv run python scripts/context_size.py                      # Markdown table to stdout
    uv run python scripts/context_size.py --json sizes.json    # also write the numbers
    uv run python scripts/context_size.py --root ../base --json base.json
    uv run python scripts/context_size.py --base base.json     # add +/- columns vs base.json

Items are read the way clients get them: each server's instructions, tools/list (name,
description, inputSchema) and prompts/list plus each rendered prompt from the real server
objects, the start_* payloads from the real tool functions, the agent system prompts and
the text the agent inserts into a conversation from agent/, the client wiring text
(Kiro agent and ACP agent descriptions), and every role document, guide, bundled style
and agent prompt file. A bundle is what one session of a role holds before its first
real step (for example, Local MCP orchestrator = instructions + all tool definitions +
the start_presentation payload). A "+ guides it names" bundle adds every guide the
role's own texts name (an upper bound of what it reads on demand). Contributor-facing
files (AGENTS.md, steering) are reported in a table of their own. Per-call tool results
and per-deck data are not counted; the report lists them under "Not measured".

chars and UTF-8 bytes are exact. tokens use tiktoken's o200k_base as a stable proxy;
Claude's tokenizer is not public, so treat them as approximate. Without tiktoken the
tokens column is empty. Each surface is read in its own subprocess under a temporary
HOME, so the numbers do not depend on the caller's config. No network, except
tiktoken's one-time, hash-checked download of its encoding file.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
DEFAULT_ROOT = SCRIPT.parents[1]

# Files that reach a model as they are (role documents, guides, bundled styles read via
# list_styles / apply_style, agent prompt parts, the Local Web UI's ACP agent prompts).
FILE_GLOBS = (
    "sdpm/references/workflows/*.md", "sdpm/references/guides/*.md", "sdpm/references/examples/styles/*.html",
    "agent/prompts/**/*.md", "servers/local/.kiro/acp-agents/prompts/*.md",
)
GUIDES_DIR = "sdpm/references/guides"
# ACP agent definitions: their description is what a spawning model sees.
ACP_AGENTS_GLOB = "servers/local/.kiro/acp-agents/*.json"
# Files a contributor's coding agent reads in this repo; not part of any product session.
DEV_GLOBS = ("AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md", ".kiro/steering/*.md")

# What the report does not count, so nobody reads the tables as complete.
NOT_MEASURED = (
    "Per-call tool results: run_python output, lint and measure_slides results, check_specs, errors and hints, "
    "and the compose reports (`<compose_result>`, `<composer_note>`, message_composer errors) on the Cloud agent "
    "and the Local Web UI (web-ui/src/lib/local/conversation/compose-report.ts, compose-run.ts).",
    "Deck data: brief, outline, art direction, slides, deck.json, attachments, and user styles and templates "
    "beyond the bundled ones.",
    "Guides that a guide names (the '+ guides it names' bundles go one level deep), and the client's own "
    "system prompt and built-in tools.",
)

# What each role's entry tool returns that does not depend on a deck: (tool, args, picks).
ROLES: dict[str, tuple[str, dict, tuple[str, ...]]] = {
    "orchestrator": ("start_presentation", {}, ("static.workflow", "listing", "templates")),
    "composer-pptx": ("start_composing", {"mode": "pptx"}, ("static.workflow", "listing")),
    "composer-html": ("start_composing", {"mode": "html"}, ("static.workflow", "listing")),
    "style": ("start_style", {}, ("static.workflow", "listing", "styles", "base.html")),
    "translate": ("start_translation", {"language": "ja"}, ("static.workflow", "listing")),
}


def mandatory_id(role: str) -> str:
    """Id of the guides a role must read, fetched from read_guides by the names its entry
    tool returned in ``must_read``. Keyed by role rather than by those names, so the id is
    the same whatever the collection currently holds."""
    return payload_id("read_guides", {"for": role}, "guides_text")

# MCP surfaces in order of how much they are used: (surface, server file, extra sys.path dirs).
SERVERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "local": ("servers/local/server.py", ("servers/local",)),
    "acp": ("servers/local/server_acp.py", ("servers/local",)),
    "remote": ("servers/remote/server.py", ("servers/remote",)),
}
SURFACE_TITLES = {"local": "Local MCP", "acp": "Local Web UI (ACP)", "agent": "Agent (AWS)", "remote": "Remote MCP"}

# Placeholders the remote server reads at import; nothing is called with them.
_REMOTE_ENV = {
    "DECKS_TABLE": "context-size", "PPTX_BUCKET": "context-size", "RESOURCE_BUCKET": "context-size",
    "AWS_DEFAULT_REGION": "us-east-1",
}


# ---------------------------------------------------------------------------
# Collection (runs in a subprocess per surface)
# ---------------------------------------------------------------------------


def _as_text(value: Any) -> str:
    """Strings verbatim, anything else as compact JSON (what a tool result carries)."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _walk(payload: dict, path: str) -> Any:
    node: Any = payload
    for key in path.split("."):
        node = node[key]
    return node


def tool_text(name: str, description: str | None, input_schema: dict) -> str:
    """One tool definition as a client hands it to a model: name, description and input schema."""
    return json.dumps(
        {"name": name, "description": description or "", "inputSchema": input_schema},
        ensure_ascii=False, separators=(",", ":"),
    )


def payload_id(tool: str, args: dict, pick: str) -> str:
    """Stable id of one picked value of an entry tool's result."""
    shown = ",".join(f"{k}={v}" for k, v in sorted(args.items()) if k != "language")
    return f"payload/{tool}({shown}).{pick}"


def _use_root(root: Path, extra: tuple[str, ...]) -> None:
    sys.path[:0] = [str(root / d) for d in extra] + [str(root / "sdpm"), str(root)]


def _check_root(module: Any, root: Path) -> None:
    """Fail when an import resolved outside root (an installed copy would measure the wrong tree)."""
    if not Path(module.__file__).resolve().is_relative_to(root):
        raise SystemExit(f"{module.__name__} imported from {module.__file__}, not from {root}")


def _call_entry(tool: str, args: dict, deck_dir: str) -> dict:
    from sdpm import tools

    if tool == "start_translation":
        args = {**args, "deck_id": deck_dir}
    return getattr(tools, tool)(**args)


def _nested_resolved(args: dict, deck_dir: str) -> dict:
    """``args`` with a nested Source resolved, the way agent.composition resolves it.

    An agent part may call one tool with what another returned (``read_guides`` with the
    names an entry tool called mandatory), so measuring that part means making both calls.
    """
    out: dict = {}
    for key, value in args.items():
        if type(value).__name__ != "Source":
            out[key] = value
            continue
        inner = _call_entry(value.value, value.args, deck_dir)
        out[key] = _walk(inner, value.pick) if value.pick else inner
    return out


def _shown_args(args: dict) -> dict:
    """``args`` for an id: a nested Source as the tool and pick it stands for."""
    return {
        key: (f"<{value.value}.{value.pick}>" if type(value).__name__ == "Source" else value)
        for key, value in args.items()
    }


def collect_server(root: Path, surface: str) -> dict[str, Any]:
    """Instructions and tools/list of one MCP server, read from the server object."""
    path, extra = SERVERS[surface]
    _use_root(root, extra)
    if surface == "remote":
        for key, value in _REMOTE_ENV.items():
            os.environ.setdefault(key, value)
    spec = importlib.util.spec_from_file_location(f"context_size_{surface}", root / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import sdpm

    _check_root(sdpm, root)
    items: dict[str, str] = {}
    if module.mcp.instructions:
        items[f"mcp/{surface}/instructions"] = module.mcp.instructions
    for tool in asyncio.run(module.mcp.list_tools()):
        items[f"mcp/{surface}/tool/{tool.name}"] = tool_text(tool.name, tool.description, tool.input_schema)
    items.update(asyncio.run(_prompt_items(module.mcp, surface)))
    return {"items": items}


async def _prompt_items(mcp: Any, surface: str) -> dict[str, str]:
    """Each prompt as prompts/list lists it, and its body as get_prompt renders it.

    Required arguments get a placeholder (``<deck_id>``); optional ones are left out, so the
    body is the prompt's own text.
    """
    items: dict[str, str] = {}
    for prompt in await mcp.list_prompts():
        items[f"mcp/{surface}/prompt/{prompt.name}"] = prompt.model_dump_json(exclude_none=True)
        args = {a.name: f"<{a.name}>" for a in prompt.arguments or [] if a.required}
        rendered = await mcp.get_prompt(prompt.name, args)
        body = "\n\n".join(m.content.text for m in rendered.messages if getattr(m.content, "text", None))
        items[f"mcp/{surface}/prompt/{prompt.name}/body"] = body
    return items


def collect_payloads(root: Path) -> dict[str, Any]:
    """The deck-independent part of every start_* result, from the contract functions."""
    _use_root(root, ())
    import sdpm

    _check_root(sdpm, root)
    items: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as deck_dir:
        Path(deck_dir, "deck.json").write_text("{}", encoding="utf-8")
        for role, (tool, args, picks) in ROLES.items():
            result = _call_entry(tool, args, deck_dir)
            for pick in picks:
                try:
                    items[payload_id(tool, args, pick)] = _as_text(_walk(result, pick))
                except KeyError:
                    continue  # an older checkout (a base commit) may not return this key yet
            # The role's prompt also holds the guides it must read; the names come from here.
            must_read = result.get("must_read") if isinstance(result, dict) else None
            if must_read:
                read = _call_entry("read_guides", {"names": must_read}, deck_dir)
                items[mandatory_id(role)] = _as_text(read["guides_text"])
    return {"items": items}


def collect_agent(root: Path) -> dict[str, Any]:
    """Per agent mode: system prompt parts, the MCP tools it allows, and its own tools."""
    _use_root(root, ("agent",))
    import composition
    import message_hooks
    from compose_messaging import COMPOSER_MESSAGE_PREFIX, ComposeMessaging, make_message_composer, make_report_tool
    from modes import MODES
    from modes.composer import _replay_start_composing, make_compose_slides
    from tools.hearing_tool import hearing
    from tools.web_tools import web_fetch

    _check_root(composition, root)
    own = {"web_fetch": web_fetch, "hearing": hearing}
    composer_tools = {"compose_slides": make_compose_slides([], None), "message_composer": make_message_composer(None)}
    # Text the agent puts into a model's conversation by itself (not a tool result).
    replay_texts = [b["text"] for m in _replay_start_composing("", [], {}) if m["role"] == "assistant"
                    for b in m["content"] if "text" in b]
    report_tool = make_report_tool(ComposeMessaging(), "", 1, []).tool_spec
    items: dict[str, str] = {
        "agent/inject/composer_message_prefix": COMPOSER_MESSAGE_PREFIX,
        "agent/inject/composer_opening": "\n".join(replay_texts),
        "agent/inject/tool_image_placeholder": message_hooks._PLACEHOLDER,
        "agent/tool/report_to_orchestrator": tool_text(
            report_tool["name"], report_tool.get("description"),
            report_tool["inputSchema"].get("json", report_tool["inputSchema"])),
    }
    modes: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as deck_dir:
        for mode, cfg in MODES.items():
            parts: list[str] = []
            for part in cfg.parts:
                source = part.source
                if source.type == "file":
                    item = f"agent/prompts/{source.value}.md"
                    items[item] = composition._read_file(source.value)
                elif source.type == "mcp":
                    args = {"mode": "pptx", **source.args} if source.value == "start_composing" else source.args
                    item = payload_id(source.value, _shown_args(args), source.pick)
                    result = _call_entry(source.value, _nested_resolved(args, deck_dir), deck_dir)
                    items[item] = composition.pick_from_text(json.dumps(result, ensure_ascii=False), source.pick)
                else:
                    continue  # callable parts are per-turn values (none today)
                parts.append(item)
            tools = dict(own, **(composer_tools if cfg.use_composer else {}))
            for name, tool in tools.items():
                spec = tool.tool_spec
                schema = spec["inputSchema"].get("json", spec["inputSchema"])
                items[f"agent/tool/{name}"] = tool_text(spec["name"], spec.get("description"), schema)
            modes[mode] = {
                "parts": parts,
                "own_tools": [f"agent/tool/{n}" for n in tools],
                "mcp_tools": cfg.allowed_tools,
            }
    return {"items": items, "modes": modes}


def collect_client(root: Path) -> dict[str, Any]:
    """Client wiring text a model sees: the Kiro agent's description (Kiro CLI shows it as
    the sub-agent tool's description). The rest of the generated config is a command line."""
    _use_root(root, ("servers/local",))
    import client_config

    _check_root(client_config, root)
    definition = client_config.kiro_agent_definition(client_config.Target(uv="uv", checkout="/sdpm"))
    return {"items": {"client/kiro/agent-description": definition["description"]}}


def _collect(root: Path, surface: str) -> dict[str, Any]:
    if surface in SERVERS:
        return collect_server(root, surface)
    if surface == "payloads":
        return collect_payloads(root)
    if surface == "client":
        return collect_client(root)
    return collect_agent(root)


SURFACES = (*SERVERS, "payloads", "agent", "client")


# ---------------------------------------------------------------------------
# Assembly and measurement (parent process)
# ---------------------------------------------------------------------------


def _run_collect(root: Path, surface: str, home: str) -> dict[str, Any]:
    env = {**os.environ, "HOME": home, "USERPROFILE": home, "SDPM_DISABLE_INSTRUCTIONS": ""}
    for key in ("SDPM_DECK_ROOT", "SDPM_OUTPUT_DIR"):
        env.pop(key, None)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--collect", surface],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=home,
    )
    if proc.returncode != 0:
        raise SystemExit(f"collecting {surface} from {root} failed:\n{proc.stderr.strip()}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _read_globs(root: Path, patterns: tuple[str, ...]) -> dict[str, str]:
    files: dict[str, str] = {}
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            files[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return files


def read_files(root: Path) -> dict[str, str]:
    """Every role document, guide, bundled style and agent prompt file, keyed by its repo
    path, and each ACP agent's description (``<file>#description``)."""
    files = _read_globs(root, FILE_GLOBS)
    for path in sorted(root.glob(ACP_AGENTS_GLOB)):
        description = json.loads(path.read_text(encoding="utf-8")).get("description")
        if description:
            files[f"{path.relative_to(root).as_posix()}#description"] = description
    return files


def read_dev_files(root: Path) -> dict[str, str]:
    """The files a contributor's coding agent reads (AGENTS.md, steering), by repo path."""
    return _read_globs(root, DEV_GLOBS)


_GUIDE_CUE = re.compile(r"\bguides?\b|read_guides")
_QUOTED_NAME = re.compile(r"[`\"]([a-z0-9-]+)[`\"]")


def named_guides(texts: list[str], guides: set[str]) -> list[str]:
    """Guide names the texts point at, in order of first mention.

    A name counts where its paragraph speaks of guides (``guide`` or ``read_guides``), so a
    region or pattern that happens to share a guide's name (``table``) does not. A paragraph
    that ends with ``:`` is read together with the list after it.
    """
    found: list[str] = []
    for text in texts:
        paragraphs = re.split(r"\n\s*\n", text)
        for i, para in enumerate(paragraphs):
            if i and paragraphs[i - 1].rstrip().endswith(":"):
                para = paragraphs[i - 1] + "\n" + para
            if not _GUIDE_CUE.search(para):
                continue
            for name in _QUOTED_NAME.findall(para):
                if name in guides and name not in found:
                    found.append(name)
    return found


def assemble(files: dict[str, str], collected: dict[str, dict]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Merge collected items into one id → text map and build the session bundles.

    Identical texts share the first id seen, files first: a role document served as is
    keeps its repo path, and one spec returned by two entry tools is listed once.
    """
    by_text = {text: path for path, text in files.items()}
    items = dict(files)
    alias: dict[str, str] = {}
    for result in collected.values():
        for item, text in result["items"].items():
            target = by_text.setdefault(text, item)
            alias[item] = target
            items[target] = text

    def ids(names: list[str]) -> list[str]:
        return [alias.get(n, n) for n in names if alias.get(n, n) in items]

    bundles: dict[str, list[str]] = {}
    for surface in ("local", "acp", "agent", "remote"):
        if surface == "agent":
            for mode, spec in collected["agent"]["modes"].items():
                allowed = spec["mcp_tools"]
                remote = [i for i in collected["remote"]["items"] if i.startswith("mcp/remote/tool/")]
                mcp = [i for i in remote if allowed is None or i.rsplit("/", 1)[-1] in allowed]
                bundles[f"{SURFACE_TITLES['agent']} / {mode}"] = ids(spec["parts"] + spec["own_tools"] + mcp)
            continue
        base = [i for i in collected[surface]["items"] if "/prompt/" not in i]  # prompts are user-invoked
        bundles[f"{SURFACE_TITLES[surface]} / tools only"] = ids(base)
        for role, (tool, args, picks) in ROLES.items():
            role_items = [payload_id(tool, args, p) for p in picks] + [mandatory_id(role)]
            bundles[f"{SURFACE_TITLES[surface]} / {role}"] = ids(base + role_items)
    # A typical session of a role on the most used surface: its start bundle plus every guide
    # the role's own texts name. Other surfaces add the same guides to their own start bundle.
    guides = {Path(i).stem for i in items if i.startswith(f"{GUIDES_DIR}/")}
    for role, (tool, args, picks) in ROLES.items():
        start = bundles[f"{SURFACE_TITLES['local']} / {role}"]
        # The role document and the spec it comes with; catalogues and a style's HTML are data.
        own_ids = [payload_id(tool, args, p) for p in picks if p.startswith("static.")] + [mandatory_id(role)]
        own = [items[i] for i in ids(own_ids)]
        extra = [f"{GUIDES_DIR}/{n}.md" for n in named_guides(own, guides)]
        bundles[f"{SURFACE_TITLES['local']} / {role} + guides it names"] = start + [g for g in extra if g not in start]
    return items, bundles


def _encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("o200k_base")
    except Exception as exc:  # missing package or encoding file: report sizes without tokens
        print(f"context_size: tokens not counted ({exc})", file=sys.stderr)
        return None


def _sizes(items: dict[str, str], encoder) -> dict[str, dict]:
    sized = {}
    for item, text in sorted(items.items()):
        tokens = len(encoder.encode(text, disallowed_special=())) if encoder else None
        sized[item] = {"chars": len(text), "bytes": len(text.encode("utf-8")), "tokens": tokens}
    return sized


def _total(sized: dict[str, dict], members: list[str]) -> dict[str, Any]:
    row: dict[str, Any] = {"items": members}
    for unit in ("chars", "bytes", "tokens"):
        values = [sized[m][unit] for m in members]
        row[unit] = None if None in values else sum(values)
    return row


def measure(
    items: dict[str, str], bundles: dict[str, list[str]], encoder=None, developer: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Sizes per item and per bundle (a bundle is the sum of its items), and the
    developer-facing files with their total, kept apart from the product items."""
    sized = _sizes(items, encoder)
    dev = _sizes(developer or {}, encoder)
    return {
        "tokenizer": "o200k_base" if encoder else None,
        "items": sized,
        "bundles": {name: _total(sized, members) for name, members in bundles.items()},
        "developer": {"items": dev, "total": _total(dev, list(dev))},
    }


def _num(value: int | None) -> str:
    return "n/a" if value is None else f"{value:,}"


def _delta(now: int | None, before: int | None) -> str:
    if now is None:
        return "removed"
    if before is None:
        return "new"
    diff = now - before
    if diff == 0:
        return "0"
    return f"{diff:+,} ({diff / before:+.1%})" if before else f"{diff:+,}"


def markdown(report: dict[str, Any], base: dict[str, Any] | None = None, top: int = 15) -> str:
    """The report as Markdown tables; with base, a +/- column and the items that changed."""
    unit = "tokens" if report["tokenizer"] and (base is None or base["tokenizer"]) else "chars"
    lines = ["## Context size", ""]
    lines.append(
        f"Tokens: tiktoken `{report['tokenizer']}`, an approximation (Claude's tokenizer is not public)."
        if report["tokenizer"] else "Tokens not counted (tiktoken unavailable)."
    )
    lines.append("")

    def table(title: str, rows: dict[str, dict], names: list[str], base_rows: dict[str, dict]) -> None:
        head = f"| {title} | chars | bytes | tokens |" + (f" Δ {unit} |" if base else "")
        lines.extend([head, "|---|---:|---:|---:|" + ("---:|" if base else "")])
        for name in names:
            row = rows.get(name, {"chars": None, "bytes": None, "tokens": None})
            cells = f"| `{name}` | {_num(row['chars'])} | {_num(row['bytes'])} | {_num(row['tokens'])} |"
            if base:
                cells += f" {_delta(row[unit], base_rows.get(name, {}).get(unit))} |"
            lines.append(cells)
        lines.append("")

    base_bundles = base["bundles"] if base else {}
    base_items = base["items"] if base else {}
    table("Bundle (one session; at start unless '+ guides')", report["bundles"], list(report["bundles"]), base_bundles)
    largest = sorted(report["items"], key=lambda i: report["items"][i]["chars"], reverse=True)[:top]
    table(f"Largest {top} items", report["items"], largest, base_items)
    if base:
        changed = [
            i for i in sorted(set(report["items"]) | set(base_items))
            if report["items"].get(i, {}).get("chars") != base_items.get(i, {}).get("chars")
        ]
        if changed:
            table("Changed items", report["items"], changed, base_items)
        else:
            lines.extend(["No item changed size.", ""])

    dev = report.get("developer", {"items": {}, "total": {}})
    if dev["items"]:
        base_dev = (base or {}).get("developer", {"items": {}, "total": {}})
        lines.extend(["### Developer-facing (contributors' coding agents, not product sessions)", ""])
        rows = {**dev["items"], "total": dev["total"]}
        table("File", rows, [*dev["items"], "total"], {**base_dev["items"], "total": base_dev["total"]})

    lines.extend(["### Not measured", ""])
    lines.extend(f"- {line}" for line in NOT_MEASURED)
    lines.append("")
    return "\n".join(lines)


def report_for(root: Path) -> dict[str, Any]:
    """Collect every surface of the checkout at root and measure it."""
    with tempfile.TemporaryDirectory() as home:
        collected = {s: _run_collect(root, s, home) for s in SURFACES}
    items, bundles = assemble(read_files(root), collected)
    return measure(items, bundles, _encoder(), read_dev_files(root))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Checkout to measure (default: this one).")
    parser.add_argument("--json", type=Path, help="Write the numbers to this file.")
    parser.add_argument("--base", type=Path, help="A --json file of the base commit, for +/- columns.")
    parser.add_argument("--top", type=int, default=15, help="How many of the largest items to list.")
    parser.add_argument("--collect", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.collect:
        print(json.dumps(_collect(root, args.collect), ensure_ascii=False))
        return
    report = report_for(root)
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    base = json.loads(args.base.read_text(encoding="utf-8")) if args.base else None
    print(markdown(report, base, args.top))


if __name__ == "__main__":
    main()
