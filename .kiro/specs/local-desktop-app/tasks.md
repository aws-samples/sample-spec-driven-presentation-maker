# Tasks: Local Desktop App

## Phase 1: Foundation

### Task 1: Prompt Extraction
Extract agent prompts to shared files. Web version reads from same files (behavior unchanged).
- [ ] Create `prompts/spec-agent.md` from `_SPEC_AGENT_PROMPT_TEMPLATE` in `agent/basic_agent.py`
- [ ] Create `prompts/composer-agent.md` from `_COMPOSER_PROMPT_TEMPLATE` in `agent/basic_agent.py`
- [ ] Modify `agent/basic_agent.py` to read from `prompts/` (fallback to inline for backward compat)
- [ ] Verify Web version agent behavior is unchanged

### Task 2: Kiro-cli Custom Agent Configs
Create agent configurations for kiro-cli ACP.
- [ ] Create `.kiro/agents/sdpm-spec.json` (prompt, tools, subagent settings, hooks)
- [ ] Create `.kiro/agents/sdpm-composer.json` (prompt, tools, no user interaction)
- [ ] Create `desktop/scripts/auto-build.py` (postToolUse hook: detect slide edit → build + measure + compose)
- [ ] Test: `kiro-cli acp --agent sdpm-spec` starts and responds to prompts

## Phase 2: Tauri App Shell

### Task 3: Tauri Project Setup
Initialize Tauri project with React frontend.
- [ ] Create `desktop/` with Tauri + Vite + React
- [ ] Configure shell plugin permissions (spawn, stdin-write)
- [ ] Import shared components from `web-ui/src/components/`
- [ ] Create desktop layout (no AuthProvider)
- [ ] Verify: `npm run dev` opens Tauri window with UI shell

### Task 4: ACP Bridge Service
Implement kiro-cli ACP communication from Tauri frontend.
- [ ] Create `desktop/src/services/acpAgentService.ts` (spawn kiro-cli, JSON-RPC over stdin/stdout)
- [ ] Create `desktop/src/services/acpParser.ts` (ACP notifications → strandsParser format)
- [ ] Implement: `session/new`, `session/prompt`, `session/cancel`
- [ ] Implement: streaming via `session/notification` → `onStreamUpdate` / `onToolUse` callbacks
- [ ] Test: send message, receive streaming text + tool events in UI

## Phase 3: Local Services

### Task 5: Local Deck Service
Implement deck CRUD on local filesystem.
- [ ] Create `desktop/src/services/localDeckService.ts`
- [ ] Implement: `listDecks()` → read `~/Documents/SDPM-Presentations/decks.json`
- [ ] Implement: `getDeck(deckId)` → read deck directory, generate preview URLs as `file://` or data URIs
- [ ] Implement: `patchDeck()`, `deleteDeck()`, `toggleFavorite()`
- [ ] Implement: deck polling (watch filesystem for changes)
- [ ] Test: create deck via agent, see it appear in deck list

### Task 6: Local Upload Service
Implement file import for local app.
- [ ] Create `desktop/src/services/localUploadService.ts`
- [ ] Implement: copy file to deck workspace, extract text (PDF/PPTX)
- [ ] Test: attach PDF in chat, agent reads content

### Task 7: Service Provider
Wire up local services to UI components.
- [ ] Create `desktop/src/lib/serviceProvider.tsx`
- [ ] Components resolve services from provider (local implementations)
- [ ] Verify: full chat → generate → preview → download flow works

## Phase 4: Packaging & Distribution

### Task 8: LibreOffice Dependency
Handle LibreOffice installation.
- [ ] Create `desktop/scripts/install-libreoffice.sh` (macOS/Linux)
- [ ] Create `desktop/scripts/install-libreoffice.ps1` (Windows)
- [ ] Add first-launch check in Tauri app (detect LibreOffice, prompt install if missing)
- [ ] Test: fresh machine → app prompts → LibreOffice installed → preview works

### Task 9: Tauri Build & Distribution
Package as native desktop app.
- [ ] Configure Tauri bundler for macOS (.dmg)
- [ ] Configure Tauri bundler for Windows (.exe / NSIS)
- [ ] Configure Tauri bundler for Linux (AppImage)
- [ ] Add GitHub Actions workflow for cross-platform builds
- [ ] Test: install from package, full workflow works

## Notes
- Tasks 1-2 can be done independently (no Tauri dependency)
- Task 3-4 are the critical path (ACP bridge is the core integration)
- Task 5-7 can be parallelized after Task 4
- Task 8-9 are independent of other tasks
