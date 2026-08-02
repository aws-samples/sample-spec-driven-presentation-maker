<!-- PUBLIC: This file is git-tracked and visible in the public repository. -->

# Versioning

## Engine Version
- Single source of truth: `__version__` in `sdpm/sdpm/__init__.py`
- `sdpm/pyproject.toml` uses dynamic version, auto-read from `__init__.py`
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
- Do not pre-assign version numbers to refactoring themes in roadmaps —
  name them "Theme N" and decide the tag at release time (a tag gated on
  e.g. E2E can be overtaken by the next theme, breaking the numbering)
- Breaking changes bump MAJOR once 1.0.0 is reached; while in 0.x they may
  ship in a MINOR release (consistent with the SemVer section above)
- While in 0.x, tool/API removals may ship without a deprecation period —
  breaking changes are announced in the CHANGELOG (with migration notes),
  not via in-product deprecation warnings. Revisit this policy at 1.0.0
- No release needed for internal-only refactoring
- Git tag format: `v{MAJOR}.{MINOR}.{PATCH}` (e.g., `v0.1.0`)

## Changelog
- `CHANGELOG.md` (Keep a Changelog format) — update the `[Unreleased]` section
  as user-facing changes land; move entries under a version heading when tagging
- Internal-only refactoring does not need an entry unless it breaks consumers
