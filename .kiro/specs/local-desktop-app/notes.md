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
