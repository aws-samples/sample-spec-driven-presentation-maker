# Design: Local Desktop App

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Tauri Shell                                     │
│  ┌───────────────────────────────────────────┐  │
│  │  React UI (shared components)              │  │
│  │  ┌─────────────────┐ ┌─────────────────┐  │  │
│  │  │ web-ui/src/      │ │ desktop/src/     │  │  │
│  │  │ components/      │ │ services/        │  │  │
│  │  │ hooks/           │ │   acpAgent.ts    │  │  │
│  │  │ (unchanged)      │ │   localDeck.ts   │  │  │
│  │  │                  │ │   localUpload.ts │  │  │
│  │  └─────────────────┘ └─────────────────┘  │  │
│  │           │                    │           │  │
│  │     aws-exports.json     local-config.json │  │
│  └───────────────────────────────────────────┘  │
│                       │                          │
│              Tauri Shell Plugin                   │
│              (spawn + stdin_write)                │
└───────────────┬─────────────────────────────────┘
                │ JSON-RPC stdin/stdout
                ▼
        kiro-cli acp --agent sdpm-spec
                │
        ┌───────┴───────┐
        │ Built-in tools │
        │ fs_read/write  │
        │ execute_bash   │
        │ use_subagent   │
        └───────┬───────┘
                │ postToolUse hook
                ▼
        skill/sdpm/ (Engine)
        LibreOffice (preview/measure/compose)
```

## Directory Structure (new files only)

```
sample-spec-driven-presentation-maker/
├─ desktop/                          # NEW: Desktop app (Tauri)
│  ├─ src-tauri/                     # Rust backend
│  │  ├─ src/
│  │  │  └─ lib.rs                   # Tauri setup + ACP process management
│  │  ├─ capabilities/
│  │  │  └─ default.json             # shell:allow-spawn, shell:allow-stdin-write
│  │  ├─ Cargo.toml
│  │  └─ tauri.conf.json
│  ├─ src/                           # Frontend (imports from web-ui)
│  │  ├─ services/
│  │  │  ├─ acpAgentService.ts       # ACP JSON-RPC ↔ UI callback adapter
│  │  │  ├─ acpParser.ts             # ACP notifications → strandsParser format
│  │  │  ├─ localDeckService.ts      # Local filesystem deck operations
│  │  │  └─ localUploadService.ts    # Local file copy
│  │  ├─ lib/
│  │  │  └─ serviceProvider.tsx      # Context provider switching AWS/local services
│  │  └─ app/
│  │     └─ layout.tsx               # Desktop layout (no AuthProvider)
│  ├─ scripts/
│  │  ├─ auto-build.py               # postToolUse hook script
│  │  └─ install-libreoffice.sh      # LibreOffice installer
│  ├─ package.json
│  └─ vite.config.ts
├─ prompts/                          # NEW: Shared agent prompts
│  ├─ spec-agent.md                  # Extracted from agent/basic_agent.py
│  └─ composer-agent.md              # Extracted from agent/basic_agent.py
├─ .kiro/
│  └─ agents/
│     ├─ sdpm-spec.json              # NEW: SPEC agent config for kiro-cli
│     └─ sdpm-composer.json          # NEW: Composer agent config for kiro-cli
├─ agent/basic_agent.py              # MODIFIED: read prompts from prompts/ (same behavior)
├─ web-ui/                           # UNCHANGED (Web version)
└─ mcp-server/                       # UNCHANGED (Web version)
```

## Key Design Decisions

### D1: Service Layer Abstraction
Desktop services implement the same function signatures as Web services. The UI components import from a service provider that resolves the correct implementation based on build target.

```typescript
// desktop/src/lib/serviceProvider.tsx
// Provides: invokeAgent, listDecks, getDeck, uploadFile, etc.
// Components import from this instead of directly from services
```

Web version is unaffected — it continues importing from `web-ui/src/services/` directly.

### D2: ACP ↔ UI Event Mapping
`acpParser.ts` converts ACP session notifications to the same format that `strandsParser.js` produces:

| ACP Notification          | → strandsParser equivalent        |
|---------------------------|-----------------------------------|
| `AgentMessageChunk`       | `contentBlockDelta.delta.text`    |
| `ToolCall` (started)      | `toolStart`                       |
| `ToolCall` (with input)   | `toolUse`                         |
| `ToolCall` (completed)    | `toolResult`                      |
| `ToolCallUpdate`          | `toolStream`                      |
| `TurnEnd`                 | (end of stream)                   |

This means ChatPanel.tsx callbacks (`onStreamUpdate`, `onToolUse`) work unchanged.

### D3: Local Storage Layout
```
~/Documents/SDPM-Presentations/
├─ decks.json                        # Deck index (list, favorites)
├─ {deckId}/
│  ├─ deck.json                      # Deck metadata
│  ├─ slides/
│  │  ├─ title.json
│  │  └─ feature-a.json
│  ├─ specs/
│  │  ├─ brief.md
│  │  ├─ outline.md
│  │  └─ art-direction.html
│  ├─ preview/
│  │  ├─ title.png
│  │  └─ feature-a.png
│  ├─ compose/
│  │  ├─ defs.json
│  │  └─ title.json
│  ├─ output.pptx
│  └─ chat-history.json
```

### D4: Auto-build Hook
```json
// .kiro/agents/sdpm-spec.json (excerpt)
{
  "hooks": {
    "postToolUse": [{
      "matcher": "fs_write",
      "command": "python3 desktop/scripts/auto-build.py",
      "description": "Auto-build PPTX after slide edit"
    }]
  }
}
```

`auto-build.py` receives `tool_input` via stdin, checks if the written path matches `*/slides/*.json`, and if so runs Engine build + measure + compose.

### D5: Prompt Extraction
```python
# agent/basic_agent.py (modified — behavior unchanged)
_SPEC_AGENT_PROMPT_TEMPLATE = Path("prompts/spec-agent.md").read_text()
_COMPOSER_PROMPT_TEMPLATE = Path("prompts/composer-agent.md").read_text()
```

```json
// .kiro/agents/sdpm-spec.json
{ "prompt": "file://prompts/spec-agent.md" }
```

### D6: Tauri + LibreOffice Bundling
- macOS: Tauri DMG + bundled LibreOffice.app (or Homebrew install prompt)
- Windows: Tauri NSIS installer + bundled LibreOffice portable (or Chocolatey install prompt)
- Linux: AppImage + system package check on first launch
