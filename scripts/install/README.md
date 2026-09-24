# SDPM installers

This directory contains the source for the Web UI local-mode installers.

- `install.sh` / `install.ps1`: platform-specific setup flow
- `lib/tui.*`: progress, confirmation, and failure-log helpers
- `launcher.*`: installed `sdpm` command implementation
- `update.*` / `uninstall.*`: explicit maintenance entry points
- `dist/install.*`: generated, standalone files used by `curl | bash` and `irm | iex`

## Build

```bash
bash scripts/install/build.sh
bash scripts/install/build.sh --check
```

Always commit source and generated files together. CI rejects drift. The shell sources remain compatible with macOS's bash 3.2. Windows support is verified in CI only; it has not received manual Windows QA yet.

## Smoke tests

```bash
HOME="$(mktemp -d)" bash scripts/install/dist/install.sh \
  --deps-only --non-interactive --skip-libreoffice

pwsh -File scripts/install/dist/install.ps1 \
  -DepsOnly -NonInteractive -SkipLibreOffice
```

Set `SDPM_HOME` to a temporary directory for a full non-interactive test. Set `SDPM_SKIP_SHORTCUT=1` to avoid creating a desktop shortcut.

## Dependency policy

The dependency-only mode installs git, uv, LibreOffice (unless skipped), and poppler. A full install additionally installs Node.js and Kiro CLI, clones the public repository to `~/.sdpm/checkout`, synchronizes dependencies, and builds the Web UI with `NEXT_PUBLIC_MODE=local`.

Windows uses winget IDs `Git.Git`, `OpenJS.NodeJS.LTS`, `TheDocumentFoundation.LibreOffice`, and `oschwartz10612.Poppler`. uv and Kiro CLI use their official PowerShell installers because a stable winget route was not confirmed.

## Sources

- ⚠️ External link — [WinGet documentation](https://learn.microsoft.com/en-us/windows/package-manager/winget/) — accessed 2026-09-24
- ⚠️ External link — [Poppler Windows releases](https://github.com/oschwartz10612/poppler-windows/releases) — accessed 2026-09-24
- ⚠️ External link — [uv installation documentation](https://docs.astral.sh/uv/getting-started/installation/) — accessed 2026-09-24
- ⚠️ External link — [Kiro CLI setup](https://kiro.dev/docs/cli/setup/) — accessed 2026-09-24
