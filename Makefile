.PHONY: all lint test format check smoke doctor install-kiro lock

all: lint test

lint:
	ruff check sdpm/ servers/ shared/ api/ agent/

format:
	ruff format sdpm/ servers/ shared/ api/ agent/

test:
	python -m pytest tests/ -v

check: lint test
	@echo "All checks passed"

# Integration smoke: boots servers/local over real stdio (no mocks)
smoke:
	uv run python scripts/smoke_local.py

# Diagnose local setup (uv / LibreOffice / poppler / checkout paths)
doctor:
	uv run python scripts/doctor.py

install-kiro:
	uv run python3 clients/kiro/install.py

# Regenerate container dependency locks (agent + servers/remote).
# Both images build for linux/arm64 + Python 3.13 (AgentCore Runtime).
lock:
	uv pip compile agent/requirements.txt \
		--python-version 3.13 --python-platform aarch64-unknown-linux-gnu \
		--no-header -o agent/requirements.lock
	uv pip compile servers/remote/pyproject.toml \
		--python-version 3.13 --python-platform aarch64-unknown-linux-gnu \
		--no-header --no-emit-package sdpm-skill \
		-o servers/remote/constraints.txt
