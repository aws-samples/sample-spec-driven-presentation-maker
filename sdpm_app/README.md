# SDPM Local App

Browser-based distribution of SDPM — no macOS signing required.

## Install

```bash
brew install uv
uv tool install sdpm-app
```

## Usage

```bash
sdpm start  # → http://localhost:8765 opens automatically
```

## macOS: Create a double-clickable app

```bash
sdpm install-shortcut  # → ~/Applications/SDPM.app
```

Open Finder → Applications → SDPM to launch without a terminal.
Since the .app is generated locally on your machine, macOS does not
apply quarantine/Gatekeeper restrictions.

## Development (rebuilding the web UI)

```bash
./sdpm_app/build-web.sh  # rebuilds web-ui static export into sdpm_app/web/
```
