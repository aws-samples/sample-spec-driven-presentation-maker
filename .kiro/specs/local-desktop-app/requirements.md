# Requirements: Local Desktop App

## Overview
Create a local desktop version of SDPM (spec-driven-presentation-maker) that runs entirely on the user's machine, powered by kiro-cli ACP. Published as OSS alongside the existing Web version.

## Design Principles
- **No breaking changes to Web version**: Existing files must not be modified in ways that affect Web version behavior
- **No dual maintenance**: Shared logic lives in one place; local-specific code is isolated in `desktop/`
- **Additive only**: Changes to existing code are limited to interface extraction and conditional branching

## Functional Requirements

### FR-1: Chat-based Presentation Creation
- Multi-turn dialogue with SPEC agent via kiro-cli ACP
- Streaming text responses and tool progress display
- Same UX as Web version (ChatPanel, ToolCard, McpStatusBar)

### FR-2: Composer Sub-agent Execution
- Parallel slide generation via kiro-cli `use_subagent` (up to 4 concurrent)
- Fallback to sequential execution (1 agent) if subagent is unavailable
- Progress display per group in ToolCard

### FR-3: Deck Management
- List, create, delete, favorite decks
- Storage: `~/Documents/SDPM-Presentations/{deckId}/`
- Deck metadata stored as local JSON files

### FR-4: Slide Preview & Animation
- PNG preview generation via LibreOffice
- SVG compose animation (AnimatedSlidePreview)
- Auto-build on slide edit via kiro-cli `postToolUse` hook

### FR-5: PPTX Download
- Generate and open/save PPTX from local file system

### FR-6: File Upload
- Import PDF/PPTX/images into deck workspace
- Local file copy (no S3 presigned URLs)

### FR-7: Outline & Art Direction Display
- SpecStepNav with outline, art-direction HTML preview
- Style selection with cover HTML preview

### FR-8: Tauri Desktop Packaging
- Build as `.dmg` (macOS) and `.exe` (Windows)
- Bundle or auto-install LibreOffice dependency

## Non-Functional Requirements

### NFR-1: Web Version Isolation
- Web version build (`npm run build`) must produce identical output with or without desktop code present
- No changes to `web-ui/src/services/*.ts` existing implementations
- No changes to `web-ui/src/components/` that alter Web behavior

### NFR-2: Prompt Single Source of Truth
- Agent prompts extracted to `prompts/` directory
- `agent/basic_agent.py` reads from `prompts/` (behavior unchanged)
- `.kiro/agents/*.json` references same files via `file://`

### NFR-3: Developer Experience
- `git clone` → `npm install` → `npm run dev` + `kiro-cli acp` for development
- Tauri build for distribution

## Excluded (Multi-user Features)
- Deck sharing
- Public decks
- Collaborator management
- User search
- Cognito authentication
