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

### globals.css cannot be @import-ed from desktop
- globals.css has its own `@import "tailwindcss"` which creates a separate Tailwind context
- Desktop's `@source` directives were in a different context → utility classes not generated
- Fix: copy globals.css content into desktop/src/app.css (minus the @import "tailwindcss" line)
- This is CSS config duplication, not component duplication — acceptable trade-off
- When globals.css changes, desktop/src/app.css needs manual sync
- TODO: consider a build script to auto-generate app.css from globals.css

### Vite alias resolution order matters
- More specific paths must come BEFORE less specific ones
- `@/services/deckService` must be before `@` (catch-all)
- `react-oidc-context` catches all direct imports from the library
- `@/hooks/useAuth` catches AppShell's custom hook wrapper
- `@/lib/auth` catches createCognitoAuthConfig import in useAuth.ts
- Tested: Vite resolves aliases in declaration order, first match wins

### Two separate auth shims needed
- `authShim.ts` → replaces `react-oidc-context` (useAuth, useAutoSignin, AuthProvider)
- `useAuthShim.ts` → replaces `@/hooks/useAuth` (custom wrapper used by AppShell)
- Different return shapes: react-oidc-context returns signinRedirect/signoutRedirect,
  custom hook returns signIn/signOut/token

### DecksPage imports useAuth() — needs adapter
- web-ui/src/app/(authenticated)/decks/page.tsx uses `useAuth()` from react-oidc-context
- Desktop version has no auth — need either:
  (a) Create a useAuth() shim that returns { isAuthenticated: true, user: { id_token: "local" } }
  (b) Or refactor DecksPage to accept auth via props/context
- Option (a) is simpler and doesn't touch web-ui code
- Create desktop/src/lib/authShim.ts that provides the same hook interface

### Shared components import paths
- Components use `@/services/deckService` etc. directly
- Desktop's Vite alias maps `@` to `web-ui/src/`
- This means components will import the AWS service implementations
- Need to either: use module aliasing in Vite to redirect service imports,
  or use the ServiceProvider pattern where components get services from context
- The ServiceProvider approach requires components to be refactored to use context
- The Vite alias approach is zero-change to web-ui but fragile
- Decision: start with Vite alias overrides for service modules, revisit if needed

### Tauri FS plugin needed alongside Shell plugin
- localDeckService.ts uses @tauri-apps/plugin-fs (readDir, readTextFile, etc.)
- Need to add tauri-plugin-fs to Cargo.toml and lib.rs
- Also need @tauri-apps/api for path utilities and convertFileSrc

### convertFileSrc for local file preview URLs
- Tauri's convertFileSrc() converts local paths to asset:// protocol URLs
- This lets <img src={previewUrl}> work with local PNG files
- Same pattern for compose SVG JSON and PPTX download links

### Chat history lives in kiro-cli sessions
- kiro-cli ACP persists sessions to ~/.kiro/sessions/cli/
- No need to duplicate chat history storage
- getChatHistory() returns empty — kiro-cli manages its own

### ACP AgentMessageChunk may be incremental or full
- ACP spec says `AgentMessageChunk` contains streaming content
- Unclear if it's incremental (delta) or accumulated (full text so far)
- Current implementation assumes incremental (appends to completion)
- If it's full text, need to change to replacement instead of append
- Test early in Task 4 verification

### ACP session/prompt is fire-and-forget
- `session/prompt` returns immediately (just acknowledgement)
- Actual response comes via `session/notification` stream
- TurnEnd notification signals completion
- This matches the SSE pattern in agentCoreService.js well

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

### LibreOffice bundling deferred
- Bundling LibreOffice (~500MB+) into the installer is impractical for initial release
- Current approach: startup check + install script (brew/apt/choco/winget)
- Tauri's Rust side logs a warning if LibreOffice is not found
- Future: could use Tauri's dialog plugin to show a proper UI prompt

### New Chat needs ACP session reset
- ChatPanel generates new sessionId on "New Chat" but ACP session stays the same
- Need to call session/new again when sessionId changes
- acpAgentService should track sessionId and recreate ACP session when it changes

### mcp-local と mcp-server のツール差分（ブロッカー）
デスクトップ版が Web 版と同じ挙動にならない根本原因。別ブランチ（main から）で対応すべき。

**必須（ブロッカー）:**
- `run_python` — スライド編集の核心。mcp-server から移植。ローカル版はサンドボックスなしで直接実行でよい
- `get_preview` — 引数が異なる（mcp-local: `slides_json_path`, mcp-server: `deck_id + slide_numbers`）。mcp-server の API に合わせる

**重要:**
- `save_web_image` — Web 画像をデッキに保存
- `apply_style` — スタイル適用
- `read_uploaded_file` — ファイルアップロード読み取り

**対応方針:**
1. `feat/mcp-local-parity` ブランチを main から切る
2. mcp-local に不足ツールを追加（mcp-server の実装を参考に、Storage を直接ファイル I/O に置換）
3. get_preview の引数を mcp-server に合わせる
4. マージ後、feat/local-desktop-app にマージ

### mcp-local と mcp-server のツール差分（ブロッカー）
デスクトップ版が Web 版と同じ挙動にならない根本原因。別ブランチ（main から）で対応すべき。

必須（ブロッカー）:
- `run_python` — スライド編集の核心。mcp-server から移植。ローカル版はサンドボックスなしで直接実行でよい
- `get_preview` — 引数不一致（local: slides_json_path, server: deck_id + slide_numbers）

重要:
- `save_web_image` — Web 画像をデッキに保存
- `apply_style` — スタイル適用
- `read_uploaded_file` — ファイルアップロード読み取り

対応方針:
1. `feat/mcp-local-parity` ブランチを main から切る
2. mcp-local に不足ツールを追加
3. get_preview の引数を mcp-server に合わせる
4. マージ後、feat/local-desktop-app にマージ

### ACP protocol field names differ from documentation
- Method: `session/update` (not `session/notification`)
- Type field: `update.sessionUpdate` (not `update.type`)
- Values: `agent_message_chunk` (not `AgentMessageChunk`), snake_case not PascalCase
- session/new requires `mcpServers: []` (array, not object, not optional)
- session/prompt requires `prompt: [{type:"text",text:"..."}]` (array of content blocks)
- Turn completion: response to session/prompt has `{stopReason:"end_turn"}` — no separate TurnEnd notification
- file:// in agent config resolves relative to .kiro/agents/, not project root

### GitHub Actions: Tauri action handles cross-platform builds
- tauri-apps/tauri-action@v0 handles signing, bundling, and artifact upload
- Triggered on `desktop-v*` tags or manual dispatch
- macOS builds both aarch64 and x86_64 targets

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
