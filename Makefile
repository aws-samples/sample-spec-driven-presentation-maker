.PHONY: all lint test format check smoke doctor install-kiro

all: lint test

lint:
	ruff check sdpm/ servers/ shared/ api/

format:
	ruff format sdpm/ servers/ shared/ api/

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
