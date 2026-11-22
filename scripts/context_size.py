# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Measure the text sdpm puts in front of a model, per item and per session bundle.

    uv run python scripts/context_size.py                      # Markdown table to stdout
    uv run python scripts/context_size.py --json sizes.json    # also write the numbers
    uv run python scripts/context_size.py --root ../base --json base.json
    uv run python scripts/context_size.py --base base.json     # add +/- columns vs base.json

Items are read the way clients get them: each server's instructions and tools/list
(name, description, inputSchema) from the real server objects, the start_* payloads from
the real tool functions, the agent system prompts from agent/modes, and every role
document, guide and agent prompt file. A bundle is what one session of a role holds
before its first real step (for example, Local MCP orchestrator = instructions + all
tool definitions + the start_presentation payload). Per-deck data (brief, outline,
slides) and per-user data beyond the bundled defaults are not counted.

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
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
DEFAULT_ROOT = SCRIPT.parents[1]

# Files that reach a model as they are (role documents, guides, agent prompt parts).
FILE_GLOBS = ("sdpm/references/workflows/*.md", "sdpm/references/guides/*.md", "agent/prompts/**/*.md")

# What each role's entry tool returns that does not depend on a deck: (tool, args, picks).
ROLES: dict[str, tuple[str, dict, tuple[str, ...]]] = {
    "orchestrator": ("start_presentation", {}, ("static.workflow", "static.deck_spec", "templates")),
    "composer-pptx": ("start_composing", {"mode": "pptx"}, ("static.workflow", "static.slide_spec")),
    "composer-html": ("start_composing", {"mode": "html"}, ("static.workflow", "static.slide_spec")),
    "style": ("start_style", {}, ("static.workflow", "styles", "base.html")),
    "translate": ("start_translation", {"language": "ja"}, ("static.workflow", "static.slide_spec")),
}

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
    return {"items": items}


def collect_payloads(root: Path) -> dict[str, Any]:
    """The deck-independent part of every start_* result, from the contract functions."""
    _use_root(root, ())
    import sdpm

    _check_root(sdpm, root)
    items: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as deck_dir:
        Path(deck_dir, "deck.json").write_text("{}", encoding="utf-8")
        for tool, args, picks in ROLES.values():
            result = _call_entry(tool, args, deck_dir)
            for pick in picks:
                try:
                    items[payload_id(tool, args, pick)] = _as_text(_walk(result, pick))
                except KeyError:
                    continue  # an older checkout (a base commit) may not return this key yet
    return {"items": items}


def collect_agent(root: Path) -> dict[str, Any]:
    """Per agent mode: system prompt parts, the MCP tools it allows, and its own tools."""
    _use_root(root, ("agent",))
    import composition
    from compose_messaging import make_message_composer
    from modes import MODES
    from modes.composer import make_compose_slides
    from tools.hearing_tool import hearing
    from tools.web_tools import web_fetch

    _check_root(composition, root)
    own = {"web_fetch": web_fetch, "hearing": hearing}
    composer_tools = {"compose_slides": make_compose_slides([], None), "message_composer": make_message_composer(None)}
    items: dict[str, str] = {}
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
                    item = payload_id(source.value, args, source.pick)
                    result = _call_entry(source.value, args, deck_dir)
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


def _collect(root: Path, surface: str) -> dict[str, Any]:
    if surface in SERVERS:
        return collect_server(root, surface)
    if surface == "payloads":
        return collect_payloads(root)
    return collect_agent(root)


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


def read_files(root: Path) -> dict[str, str]:
    """Every role document, guide and agent prompt file, keyed by its repo path."""
    files: dict[str, str] = {}
    for pattern in FILE_GLOBS:
        for path in sorted(root.glob(pattern)):
            files[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return files


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
        base = list(collected[surface]["items"])
        bundles[f"{SURFACE_TITLES[surface]} / tools only"] = ids(base)
        for role, (tool, args, picks) in ROLES.items():
            bundles[f"{SURFACE_TITLES[surface]} / {role}"] = ids(base + [payload_id(tool, args, p) for p in picks])
    return items, bundles


def _encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("o200k_base")
    except Exception as exc:  # missing package or encoding file: report sizes without tokens
        print(f"context_size: tokens not counted ({exc})", file=sys.stderr)
        return None


def measure(items: dict[str, str], bundles: dict[str, list[str]], encoder=None) -> dict[str, Any]:
    """Sizes per item and per bundle (a bundle is the sum of its items)."""
    sized = {}
    for item, text in sorted(items.items()):
        tokens = len(encoder.encode(text, disallowed_special=())) if encoder else None
        sized[item] = {"chars": len(text), "bytes": len(text.encode("utf-8")), "tokens": tokens}
    totals = {}
    for name, members in bundles.items():
        row: dict[str, Any] = {"items": members}
        for unit in ("chars", "bytes", "tokens"):
            values = [sized[m][unit] for m in members]
            row[unit] = None if None in values else sum(values)
        totals[name] = row
    return {"tokenizer": "o200k_base" if encoder else None, "items": sized, "bundles": totals}


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
    table("Bundle (one session at start)", report["bundles"], list(report["bundles"]), base_bundles)
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
    return "\n".join(lines)


def report_for(root: Path) -> dict[str, Any]:
    """Collect every surface of the checkout at root and measure it."""
    with tempfile.TemporaryDirectory() as home:
        collected = {s: _run_collect(root, s, home) for s in (*SERVERS, "payloads", "agent")}
    items, bundles = assemble(read_files(root), collected)
    return measure(items, bundles, _encoder())


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
