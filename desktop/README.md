# SDPM Desktop (Tauri)

Local desktop version of Spec-Driven Presentation Maker, powered by kiro-cli ACP.

## Prerequisites

| Dependency | Version | Install (macOS) |
|---|---|---|
| [Node.js](https://nodejs.org) | 20+ | `brew install node` |
| [Rust](https://rustup.rs) | stable | `brew install rust` |
| [uv](https://docs.astral.sh/uv) | latest | `brew install uv` |
| [kiro-cli](https://kiro.dev) | 1.25+ | See [kiro.dev/cli](https://kiro.dev/cli) |
| [LibreOffice](https://www.libreoffice.org) | 25.8.6+ | Auto-installed on first launch, or `brew install --cask libreoffice` |

**Windows/Linux**: Same tooling (use platform package managers). LibreOffice install script exists (`desktop/scripts/install-libreoffice.{sh,ps1}`) but is primarily tested on macOS.

## Setup

```bash
git clone <repo-url> sdpm
cd sdpm
uv sync --directory mcp-local
cd desktop && npm install
```

## Run

```bash
npm run tauri dev        # dev mode (hot reload)
npm run tauri build      # production build (DMG/app bundle)
```

## Configure ACP Agent

On first launch, open the user menu (top-right) → **ACP Agents**.
Default: **Kiro CLI** (uses `kiro-cli acp --agent sdpm-spec`).

To use another ACP-compatible agent (Claude Code, opencode, Gemini CLI, etc.):
1. Click **Add Agent**
2. Fill in: Display Name, Agent ID, Path, Arguments, Environment variables
3. Set Subagent Tool (e.g. `Task` for Claude, `task` for opencode)
4. Save & Restart

See the adapter definitions in `desktop/src/services/acpAgentAdapter.ts` for per-agent defaults.

## How It Works

- **Frontend**: Shared Next.js web UI (`web-ui/`), loaded as Tauri WebView
- **Desktop services**: `desktop/src/services/` — local file-based deck storage, ACP agent process management
- **ACP agent**: `kiro-cli acp --agent sdpm-spec` spawned via Tauri shell plugin
- **MCP server**: `mcp-local/server_acp.py` — extends standalone `server.py` with ACP-specific tools (run_python, compose pipeline, etc.)
- **Deck storage**: `~/Documents/SDPM-Presentations/<deckId>/`

## Architecture

```
+---------------------------+
|   Tauri WebView (Next.js) |
+---------------------------+
             |
             v (IPC)
+---------------------------+
|   Tauri Rust backend      |
|   - spawn kiro-cli        |
|   - file system access    |
+---------------------------+
             |
             v (ACP: JSON-RPC over stdio)
+---------------------------+
|   kiro-cli acp            |
|   - Spec & Composer agents|
+---------------------------+
             |
             v (MCP)
+---------------------------+
|   mcp-local/server_acp.py |
|   - run_python, compose   |
|   - sdpm.api (engine)     |
+---------------------------+
```

## Troubleshooting

### "LibreOffice not found" or old version
Run `bash desktop/scripts/install-libreoffice.sh` manually, or re-launch the app to trigger auto-install.

### `kiro-cli: command not found` on launch
Install kiro-cli and ensure it's on `$PATH` when Tauri runs. In development, `npm run tauri dev` inherits your shell's PATH.

### Agent responses fail with "Sorry, something went wrong"
Check browser DevTools console for `[acp stderr]` messages. Common causes:
- `kiro-cli` version below 1.25 (no ACP support)
- `.kiro/agents/sdpm-spec.json` corrupted (delete and restart)

### Animation plays when reopening existing deck
Should not happen after `v0.x`. Check that `hadSlidesOnMount` logic in `SlideCarousel.tsx` is intact.

## Distribution

**Current**: users must build from source (`npm run tauri build`). macOS signing not configured — unsigned DMG would require users to run `xattr -d com.apple.quarantine <app>` after download.

See [main project README](../README.md) for the hosted Web version.
