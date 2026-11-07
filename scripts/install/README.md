# SDPM installers

This directory contains the source for the SDPM installer and the `sdpm` launcher — the one
local installation (`~/.sdpm`) that serves every MCP client and the browser Web UI.

- `install.sh` / `install.ps1`: platform-specific setup flow
- `lib/tui.*`: progress, confirmation, and failure-log helpers
- `launcher.*`: installed `sdpm` command (`webui` / `mcp` / `register` / `update` / …). Client
  detection, configuration rendering and registration are not implemented here: both launchers
  delegate to `servers/local/client_config.py` so the two cannot drift. `sdpm update` ends with
  `client_config.py refresh`, which replaces the installed launcher with the checkout's
- `servers/local/checkout_update.py`: the pull of `sdpm update` and of the installer over an
  existing install. Both fetch `main` and run this file as of `FETCH_HEAD`, before anything is
  checked out: changes to tracked files go to a named git stash (never reset or cleaned), then
  `main` is fast-forwarded. Standard library only, so any Python runs it (`uv run --no-project`)
- The launchers, the installers and the client configuration pass `--frozen` to uv, and
  `npm run build` keeps `web-ui/next-env.d.ts` as committed: a tracked file our tools change
  would stop the next pull. CI checks the checkout is unchanged after install and update
- `mcp_smoke.py`: MCP `initialize` + `tools/list` over any stdio command (CI uses it over `sdpm mcp`)
- `update.*` / `uninstall.*`: explicit maintenance entry points
- `dist/install.*`: generated, standalone files used by `curl | bash` and `irm | iex`

## Build

```bash
bash scripts/install/build.sh
bash scripts/install/build.sh --check
```

Always commit source and generated files together. CI rejects drift. The shell sources remain compatible with macOS's bash 3.2. Windows support is verified in CI only; it has not received manual Windows QA yet.

## Smoke tests

A real install from the working tree, into an isolated home (this is what CI runs on all
three OS; see `.github/workflows/installer.yml`):

```bash
MIRROR="$(mktemp -d)/mirror.git"; git clone -q --bare . "$MIRROR"; git -C "$MIRROR" branch -f main HEAD
export SDPM_HOME="$(mktemp -d)/.sdpm" SDPM_LAUNCHER_DIR="$(mktemp -d)/bin" SDPM_REPO_URL="$MIRROR"
bash scripts/install/dist/install.sh --mcp-only --non-interactive --skip-libreoffice --no-register
"$SDPM_LAUNCHER_DIR/sdpm"                       # status
"$SDPM_LAUNCHER_DIR/sdpm" register --dry-run    # never executes
python3 scripts/install/mcp_smoke.py "$SDPM_LAUNCHER_DIR/sdpm" mcp
```

`SDPM_REPO_URL` exists for exactly this: the installer clones `main`, so a local mirror
serves the current tree under that name. `--deps-only` still installs just the dependencies.

`sdpm update` from a launcher that predates the refresh step (every install before it
carries the #397 launcher), in the same isolated home. Set `HOME` and `KIRO_HOME` to
temporary directories as well and keep other MCP clients off `PATH`: the refresh registers
again every client that already has SDPM.

```bash
git show 7c53267d:scripts/install/launcher.sh > "$SDPM_LAUNCHER_DIR/sdpm"
git -C "$SDPM_HOME/checkout" reset -q --hard HEAD~1
"$SDPM_LAUNCHER_DIR/sdpm" update                # "… (once: this sdpm command predates the step)"
cmp "$SDPM_LAUNCHER_DIR/sdpm" scripts/install/launcher.sh
"$SDPM_LAUNCHER_DIR/sdpm" update                # new launcher: "sdpm command: up to date"
```

`sdpm update` from a checkout whose tracked files a tool changed (an install on 1c618b58 had
`sdpm/uv.lock`, which `main` deletes, and `web-ui/next-env.d.ts`). The #397 launcher stops at
the pull; the new launcher, the installer and the documented `git … stash` line get past it:

```bash
git -C "$SDPM_HOME/checkout" reset -q --hard 1c618b58
echo "# rewritten by uv" >> "$SDPM_HOME/checkout/sdpm/uv.lock"
git show 7c53267d:scripts/install/launcher.sh > "$SDPM_LAUNCHER_DIR/sdpm"
"$SDPM_LAUNCHER_DIR/sdpm" update                # stops: "Your local changes … would be overwritten"
bash scripts/install/dist/install.sh --non-interactive --skip-libreoffice   # keeps the profile; sets them aside
git -C "$SDPM_HOME/checkout" stash list         # the changes, kept
```

## Dependency policy

The dependency-only mode installs git, uv, LibreOffice (unless skipped), and poppler. The
MCP-only profile clones the repository to `~/.sdpm/checkout`, syncs `servers/local` and
downloads the icon catalogs. The full profile additionally installs Node.js and Kiro CLI and
builds the Web UI with `NEXT_PUBLIC_MODE=local`. The profile is recorded in
`~/.sdpm/.profile`, the absolute `uv` path in `~/.sdpm/.uv-path`; the launcher and the
client configuration read both.

Windows uses winget IDs `Git.Git`, `OpenJS.NodeJS.LTS`, `TheDocumentFoundation.LibreOffice`, and `oschwartz10612.Poppler`. uv and Kiro CLI use their official PowerShell installers because a stable winget route was not confirmed.

## Sources

- ⚠️ External link — [WinGet documentation](https://learn.microsoft.com/en-us/windows/package-manager/winget/) — accessed 2026-09-24
- ⚠️ External link — [Poppler Windows releases](https://github.com/oschwartz10612/poppler-windows/releases) — accessed 2026-09-24
- ⚠️ External link — [uv installation documentation](https://docs.astral.sh/uv/getting-started/installation/) — accessed 2026-09-24
- ⚠️ External link — [Kiro CLI setup](https://kiro.dev/docs/cli/setup/) — accessed 2026-09-24
