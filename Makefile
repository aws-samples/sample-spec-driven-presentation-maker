.PHONY: all lint test format check smoke doctor lock register-dev mcp-config-dev

all: lint test

lint:
	uv run ruff check sdpm/ servers/ shared/ api/ agent/

format:
	uv run ruff format sdpm/ servers/ shared/ api/ agent/

test:
	uv run pytest tests/ -v

check: lint test
	@echo "All checks passed"

# Integration smoke: boots servers/local over real stdio (no mocks)
smoke:
	uv run python scripts/smoke_local.py

# Diagnose local setup (uv / LibreOffice / poppler / checkout paths)
doctor:
	uv run python scripts/doctor.py

# Point your MCP clients at THIS checkout, next to (not instead of) an installed ~/.sdpm.
# Kiro CLI gets its own agent so `kiro-cli chat --agent sdpm-dev` runs your working tree
# while `--agent sdpm` keeps running the installed release. AGENT=sdpm-feature-x for worktrees.
AGENT ?= sdpm-dev
register-dev:
	uv run --directory servers/local python client_config.py --checkout "$(CURDIR)" --agent-name $(AGENT) register $(CLIENTS)

mcp-config-dev:
	uv run --directory servers/local python client_config.py --checkout "$(CURDIR)" --agent-name $(AGENT) print --all

# Re-resolve the workspace lock (uv.lock) after editing any member's pyproject.toml.
# One universal lock covers every surface: servers/local on any OS, both runtime images
# (linux/arm64, Python 3.13) and the API Lambda (x86_64, Python 3.13).
lock:
	uv lock
