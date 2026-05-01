# Contributing Guidelines

Thank you for your interest in contributing to this project. Whether it's a bug report, new feature, correction, or additional documentation, we greatly value feedback and contributions from our community.

Please read [AGENTS.md](AGENTS.md) first for project structure, layer architecture, and conventions.

## How to contribute

1. Fork the repository
2. Create a branch with a conventional prefix (`feat/...`, `fix/...`, `docs/...`, `refactor/...`)
3. Make your changes
4. Verify locally: `make all` and `ash scan --mode local --fail-on-findings`
5. Commit with a [Conventional Commits](https://www.conventionalcommits.org/) message (`feat: ...`, `fix: ...`, `docs: ...`, etc.)
6. Push and open a Pull Request

CI runs ruff, pytest, and ASH (security scan) on every PR. Failing checks block merge.

## Development setup

This repo uses `uv` — do not call `python` directly. The root `pyproject.toml` provides a single dev dependency group that covers all layers.

```bash
# Install dev dependencies (ruff, pytest, engine, and runtime deps)
uv sync --group dev

# Run all checks (lint + tests)
make all

# Individual targets
make lint     # ruff check
make test     # pytest
make format   # ruff format (write changes)
```

For web-ui / infra TypeScript changes, use `npm ci` in the respective directory.

## Security scanning

Before opening a PR, run the [AWS Automated Security Helper](https://github.com/awslabs/automated-security-helper) locally to catch findings early:

```bash
# One-time install (recommended as an alias)
alias ash="uvx git+https://github.com/awslabs/automated-security-helper.git@v3"

# Scan
ash scan --mode local --fail-on-findings
```

CI runs the same scan with `--fail-on-findings`, so local failures will also fail CI.

## Code style

- All public functions must have docstrings (purpose, args, returns)
- Type hints on all function signatures
- Non-obvious code must be commented
- No silent fallback to default values — fail loudly
- Named parameters preferred over positional
- File header: `# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.` + `# SPDX-License-Identifier: MIT-0`
- For non-security hash usage (e.g. content deduplication with md5), add `usedforsecurity=False` to satisfy bandit B303

## Which layer to modify

The engine in `skill/sdpm/` is the single source of truth for business logic. Prefer extending the engine over duplicating logic in `mcp-local/`, `mcp-server/`, or `agent/`. See [AGENTS.md](AGENTS.md) and the layering rules for details.

## Reporting bugs / feature requests

Use the GitHub issue tracker for bugs and feature requests. Include repro steps and environment details where relevant.

## Security issue notifications

If you discover a potential security issue in this project, notify AWS/Amazon Security via our [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/) instead of filing a public GitHub issue.

## Licensing

See the [LICENSE](LICENSE) file for our project's licensing. We will ask you to confirm the licensing of your contribution.
