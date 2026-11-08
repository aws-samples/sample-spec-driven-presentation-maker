# SDPM installers

This directory contains the source for the SDPM installer and the `sdpm` launcher — the one
local installation (`~/.sdpm`) that serves every MCP client and the browser Web UI.

- `install.sh` / `install.ps1`: the OS dependencies (brew / apt / winget, uv, git, LibreOffice,
  poppler, Node.js, Kiro CLI), the clone or fetch, then a hand-off to main's
  `servers/local/checkout_update.py install`; afterwards the PATH entry, the Windows `sdpm.cmd`
  shim, the desktop shortcut and the completion screen. Without a terminal they never wait
  for input (the TTY rule: stdout is a terminal and `/dev/tty` opens)
- `lib/tui.*`: progress, confirmation, and failure-log helpers
- `launcher.*`: the installed `sdpm` command, a bootstrap (`sdpm-bootstrap 1`). It resolves
  uv, fetches (`+refs/heads/main:refs/remotes/origin/main`, `+refs/tags/*:refs/tags/*`,
  `--prune`) and hands `update` to `servers/local/checkout_update.py` and everything else to
  `servers/local/sdpm_command.py`, with `uv run --no-project --isolated --python ">=3.11"`.
  It changes only if that contract changes
- `servers/local/checkout_update.py`: the install lifecycle. Stage 1 (the installed version)
  selects the target (the newest release tag on `main`, or `main` on the main channel; never a
  commit that does not contain the install's), sets changed tracked files aside in a named git
  stash, and checks the target out detached. Stage 2 (`finish`, the target's own code)
  prepares the Python environment, the Web UI and the icons, records `~/.sdpm/state.json`,
  writes the launcher, refreshes the clients and prints the upgrading notes. A failure before
  the `update-prepared` sentinel rolls back to the previous commit. Standard library only,
  one file, Python 3.8+ (old launchers run it with any Python)
- The launchers, the installers and the client configuration pass `--frozen` to uv, and
  `npm run build` keeps `web-ui/next-env.d.ts` as committed: a tracked file our tools change
  would stop the next update. CI checks the checkout is unchanged after install and update
- `release_channel_smoke.py`: the release-channel scenarios against a local mirror with v99
  test tags and file-served manifests (CI job `release-channel` on three OS; runs locally too)
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
A real mirror carries the real release tags: once a release ≥ 0.13.0 exists, set
`SDPM_CHANNEL=main` so the install runs your tree and not that release.

The release channel itself (new install on a tag, a main user who stays, `--channel main`,
the three old launchers, a changed checkout, the offline rollback, no terminal, the manifest
check and fallback) runs as one script. Isolate `HOME` and keep MCP client CLIs off `PATH`
first: step 9 installs with `--register`.

```bash
python3 scripts/install/release_channel_smoke.py --work "$(mktemp -d)/rc" --profile mcp
python3 scripts/install/release_channel_smoke.py --work "$(mktemp -d)/rc" --profile full   # Node.js 20+
```

`sdpm update` from a launcher that predates the refresh step (every install before it
carries the #397 launcher), in the same isolated home. Set `HOME` and `KIRO_HOME` to
temporary directories as well and keep other MCP clients off `PATH`: the refresh registers
again every client that already has SDPM. A real install of that launcher has `.profile`
and `.agent-name` and no `state.json`.

```bash
git show 7c53267d:scripts/install/launcher.sh > "$SDPM_LAUNCHER_DIR/sdpm"
echo mcp > "$SDPM_HOME/.profile"; echo sdpm > "$SDPM_HOME/.agent-name"; rm "$SDPM_HOME/state.json"
git -C "$SDPM_HOME/checkout" checkout -q -B main HEAD~1
"$SDPM_LAUNCHER_DIR/sdpm" update                # "… (once: this sdpm command predates the step)"
cmp "$SDPM_LAUNCHER_DIR/sdpm" scripts/install/launcher.sh
"$SDPM_LAUNCHER_DIR/sdpm" update                # new launcher: "sdpm command: up to date"
```

`sdpm update` from a checkout whose tracked files a tool changed (an install on 1c618b58 had
`sdpm/uv.lock`, which `main` deletes, and `web-ui/next-env.d.ts`). The #397 launcher stops at
the pull; the new launcher, the installer and the documented `git … stash` line get past it:

```bash
git -C "$SDPM_HOME/checkout" checkout -q -f -B main 1c618b58
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
builds the Web UI with `NEXT_PUBLIC_MODE=local` (again only when the commit changed: the
stamp `web-ui/build/.sdpm-source`). The profile, the channel, the Kiro agent name, the
installed version and the registered clients are recorded in `~/.sdpm/state.json`, the
absolute `uv` path in `~/.sdpm/.uv-path` (the bootstrap reads it before any Python runs).

Windows uses winget IDs `Git.Git`, `OpenJS.NodeJS.LTS`, `TheDocumentFoundation.LibreOffice`, and `oschwartz10612.Poppler`. uv and Kiro CLI use their official PowerShell installers because a stable winget route was not confirmed.

## Sources

- ⚠️ External link — [WinGet documentation](https://learn.microsoft.com/en-us/windows/package-manager/winget/) — accessed 2026-09-24
- ⚠️ External link — [Poppler Windows releases](https://github.com/oschwartz10612/poppler-windows/releases) — accessed 2026-09-24
- ⚠️ External link — [uv installation documentation](https://docs.astral.sh/uv/getting-started/installation/) — accessed 2026-09-24
- ⚠️ External link — [Kiro CLI setup](https://kiro.dev/docs/cli/setup/) — accessed 2026-09-24
