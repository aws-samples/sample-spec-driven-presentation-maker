# Distribution Options (Local Desktop App)

## Current state
Users must build from source. Requires Rust, Node.js, uv, kiro-cli, LibreOffice 25.8.6+.

## Evaluation of distribution paths

### Option A: Apple Developer Program + notarization ($99/year)
- **Pros**: Proper macOS UX. Users download DMG, drag to /Applications, launch. No warnings.
- **Cons**: $99/year. CI setup (certificate, notarization credentials in secrets).
- **Windows**: SmartScreen still warns without EV certificate ($200-400/year). Standard cert OK.
- **Recommended if**: project goes public / user base > ~10.

### Option B: Unsigned DMG via GitHub Releases
- **Pros**: Free. CI builds + uploads DMG on tag push.
- **Cons**: Users must run `xattr -d com.apple.quarantine /Applications/SDPM.app` after download. macOS 15+ makes this progressively harder (multiple prompts). Non-trivial for non-technical users.
- **Recommended if**: audience is developers only.

### Option C: Build-from-source (current)
- **Pros**: Zero signing concerns. All prerequisites are dev tools anyway.
- **Cons**: Non-developers cannot use it.
- **Recommended if**: targeting developers exclusively (current state).

### Option D: Homebrew cask (still unsigned)
- Same signing situation as Option B; `brew install --cask sdpm` just wraps the DMG download. Not a net improvement.

### Option E: Python CLI + browser UI (deferred)
- Distribute via `uv tool install sdpm-app`. Serves static web-ui on localhost.
- **Pros**: No macOS signing. `uvx` / `pipx` one-command install.
- **Cons**: Loses Tauri native feel. Requires rewriting service layer (deckService → FastAPI). Investigated in `feat/local-desktop-app`, reverted — see git history `6ff3da34` → `eb2d2c31`.
- **Recommended if**: committed to zero-signing distribution at the cost of architecture rework.

## Decision (as of 2026-04)

**Short term**: Option C (current). Document setup clearly in `desktop/README.md`.

**Mid term**: Option A when ready to publish. Track in separate task. Estimated effort: 2-3 days (CI pipeline, cert management, first successful notarized build).

**Don't pursue**: Options D, E unless strategic pivot.

## Signing quick reference (for future Option A)

```
desktop/src-tauri/tauri.conf.json
  - bundle.macOS.signingIdentity: "Developer ID Application: ..."
  - bundle.macOS.entitlements: path/to/entitlements.plist

GitHub Actions secrets:
  - APPLE_CERTIFICATE (base64)
  - APPLE_CERTIFICATE_PASSWORD
  - APPLE_ID / APPLE_PASSWORD (app-specific)
  - APPLE_TEAM_ID
```

See [Tauri macOS signing docs](https://tauri.app/distribute/sign/macos/) for full setup.
