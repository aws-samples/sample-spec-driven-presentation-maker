.PHONY: all lint test format check install-kiro

all: lint test

lint:
	ruff check skill/ mcp-local/ mcp-server/ shared/ api/

format:
	ruff format skill/ mcp-local/ mcp-server/ shared/ api/

test:
	python -m pytest tests/ -v

check: lint test
	@echo "All checks passed"

install-kiro:
	uv run python3 clients/kiro/install.py
