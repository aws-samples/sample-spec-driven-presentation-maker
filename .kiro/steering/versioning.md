<!-- PUBLIC: This file is git-tracked and visible in the public repository. -->

# Versioning

## Engine Version
- Single source of truth: `__version__` in `skill/sdpm/__init__.py`
- `skill/pyproject.toml` uses dynamic version, auto-read from `__init__.py`
- When changing version, edit `__init__.py` only

## SemVer
- MAJOR: Breaking changes to Engine API (e.g., existing JSON no longer works)
- MINOR: New features, new slide patterns
- PATCH: Bug fixes
- While in 0.x, breaking changes may occur in MINOR releases
- The 1.0.0 release will signal API stability

## Release
- Milestone-based (manual decision)
- Tag when user-facing changes have accumulated
- Breaking changes must always bump MAJOR
- No release needed for internal-only refactoring
- Git tag format: `v{MAJOR}.{MINOR}.{PATCH}` (e.g., `v0.1.0`)
- After tag push, create GitHub Releases with key changes noted
