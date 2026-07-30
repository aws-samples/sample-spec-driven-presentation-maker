.PHONY: all lint test format check install-kiro

all: lint test

lint:
	ruff check sdpm/ servers/ shared/ api/

format:
	ruff format sdpm/ servers/ shared/ api/

test:
	python -m pytest tests/ -v

check: lint test
	@echo "All checks passed"

install-kiro:
	uv run python3 clients/kiro/install.py
