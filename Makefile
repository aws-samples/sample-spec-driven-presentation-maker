.PHONY: all lint test format check

all: lint test

lint:
	ruff check skill/ mcp-local/ mcp-server/ shared/ api/

format:
	ruff format skill/ mcp-local/ mcp-server/ shared/ api/

test:
	python -m pytest tests/ -v

check: lint test
	@echo "All checks passed"
