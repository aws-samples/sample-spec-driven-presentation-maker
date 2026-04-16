# Notes: Local Desktop App

## Key Discoveries

### ACP is the right integration point
- Headless mode is one-shot only → unsuitable for multi-turn chat
- ACP provides: multi-turn sessions, streaming, tool progress, cancel
- kiro-cli 2.0 TUI itself uses ACP internally
- JSON-RPC over stdin/stdout, well-documented protocol

### Tauri Shell plugin supports full ACP communication
- `Command.create()` + `spawn()` for process management
- `stdout.on('data')` for real-time JSON-RPC notifications
- `stdin_write` for sending requests
- Permissions: `shell:allow-spawn`, `shell:allow-stdin-write`

### ACP event format maps cleanly to existing UI
- `AgentMessageChunk` → `contentBlockDelta.delta.text`
- `ToolCall` → `toolStart` / `toolUse` / `toolResult`
- `ToolCallUpdate` → `toolStream`
- ChatPanel.tsx callbacks work unchanged with adapter layer

### kiro-cli subagent has 4-parallel limit
- Web version uses ThreadPoolExecutor with max 10
- Local version limited to 4 via use_subagent
- Acceptable trade-off for local use

### Auto-build via postToolUse hook
- Web version: auto-build logic inside mcp-server's run_python tool
- Local version: kiro-cli postToolUse hook on fs_write
- Hook receives tool_input (file path) via stdin JSON
- Script checks if path matches */slides/*.json, runs Engine build

### main branch prompt is pre-separation
- main has a single `_SYSTEM_PROMPT_TEMPLATE` (no SPEC/Composer split)
- `feat/agent-separation-spec-composer` branch has the detailed prompts
- Extract what's on main now; when separation branch merges, update `prompts/`
- Web version wraps prompt with `{now}` and `{mcp_instructions}` placeholders
- kiro-cli handles timestamp and MCP instructions itself, so prompt file should be the core content only
- `agent/basic_agent.py` adds the wrapper; `.kiro/agents/` references the file directly

### auto-build.py needs Engine API alignment
- Web version's `run_python` calls `generate.generate_pptx()` and `preview.measure()` with S3 storage
- Local version's `auto-build.py` calls `sdpm.api.generate()` and `sdpm.api.measure()` directly
- Engine API (`skill/sdpm/api.py`) works with local file paths — no S3 dependency
- But `generate()` expects a `json_path` pointing to the old `presentation.json` or new `deck.json`
- Need to verify Engine API accepts the local deck directory structure
- compose (SVG split) is NOT in Engine API — it's in `mcp-server/tools/compose.py`
- For local version, compose may need to be extracted to a standalone script or skipped initially

### Vite alias for shared components
- `@` → `../web-ui/src/` allows importing shared components without copying
- `@desktop` → `./src/` for desktop-specific code
- This means `web-ui/src/components/` is used directly — zero duplication
- Caveat: web-ui dependencies (react-oidc-context, etc.) will be in desktop's node_modules too
- May need to conditionally exclude auth-related imports

### kiro-cli agent config: file:// paths are relative to cwd
- `.kiro/agents/sdpm-spec.json` uses `file://prompts/system-prompt.md`
- This resolves relative to the project root (where kiro-cli is launched)
- Works for dev mode; for Tauri packaged app, need to ensure cwd is set correctly

## Risks

### ToolCallUpdate granularity (unverified)
- compose_slides sends custom progress data (group, slugs, tool name, success/error)
- ACP ToolCallUpdate may not transparently pass all custom fields
- Mitigation: test early in Task 4, simplify ToolCard display if needed

### kiro-cli subscription requirement
- ACP requires Pro+ subscription
- Not documented in README per user request
- May limit OSS adoption

### LibreOffice bundling size
- LibreOffice is ~500MB+
- Bundling increases installer size significantly
- Alternative: prompt user to install separately on first launch
