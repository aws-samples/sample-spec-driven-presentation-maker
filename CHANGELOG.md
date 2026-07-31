# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(while in 0.x, breaking changes may occur in MINOR releases).

Entries before v0.5.0 were written retroactively as summaries.

## [Unreleased]

### Fixed

- **Cloud agent output-token limit**: model profiles now set an explicit
  `max_tokens` (Claude 32768, others 8192) — Bedrock's small default truncated
  long single-call outputs (e.g. writing `specs/brief.md` from a long article)
  and killed the turn with a generic error. `MaxTokensReachedException` is also
  classified now (`max_output`) so the Web UI shows an actionable message
  instead of "something went wrong".

### Changed

- **L4 agent personas unified**: the cloud agent (Strands) now fetches mode
  behavior from `personas/*.md` through the same `start_presentation(mode=...)`
  port as every other client, instead of carrying its own copies in
  `agent/prompts/role/`. Duplicated role/workflow prompt files were removed;
  only transport-specific wiring (attachment wire format, `compose_slides`
  report format) remains in `agent/prompts/`. Prompt changes now touch only
  `personas/` for all layers.
- **Internal API move**: `sdpm.engine.diff.diff_report` / `load_slides_json_or_pptx`
  moved to `sdpm.api` (dependency-rule fix; `engine.diff` now exposes the pure
  `diff_slides(base, edit)`). These were internal APIs — update imports if you
  consumed them directly.

## [0.5.0] - 2026-07-31

Breaking architecture cleanup. No changes to the slide JSON schema — existing
decks and cloud data keep working. See the
[migration guide](docs/en/migration-v0.5.md) for upgrade steps.

### Changed (breaking)

- **Directory layout**: `skill/` → `sdpm/`, `mcp-local/` → `servers/local/`,
  `mcp-server/` → `servers/remote/`, `agents/` → `clients/claude-code/agents/`
- **Engine split**: the `sdpm` package is now organised as two peer subpackages —
  `sdpm.engine` (json ↔ pptx) and `sdpm.knowledge` (references / assets)
- **Skill files removed**: mode behavior now lives in `personas/*.md` and is
  served to any MCP client via the new `start_presentation(mode=...)` tool.
  Claude Code plugin no longer installs skills; Kiro installer no longer
  symlinks skill directories
- **Single tool contract**: every MCP tool is defined once in `sdpm.tools`;
  both servers bind the same functions (local: 24 tools, remote: 22 tools)
- **Docs**: English docs are canonical; Japanese docs reduced to README and
  getting-started

### Added

- `start_presentation(mode=...)` MCP tool — serves vibe / spec / style /
  composer / single personas to any MCP client
- `SDPM_SKILL_ROOT` environment override for path anchors (used by the remote
  Docker image, gateway integrations)
- Migration guide: `docs/en/migration-v0.5.md`

### Fixed

- Pinned `mcp>=1.28.1,<2` across local server, remote server, and agent —
  mcp 2.0.0 removed `mcp.server.fastmcp` and crashed fresh container builds

## [0.4.0] - 2026-07-30

- Kiro CLI support: installer, composer agent, skill dispatch (#207)
- PPTX import: bring existing decks into the agent + edit flow, hand-edit sync
  via `diff_pptx` (#149, #215, #220)
- Template notes (built-in and local), template picker in Art Direction pane
  (#203, #204)
- User-local styles, assets, config, and template directories with
  cross-platform paths (#96, #99)
- Per-user model switching via Settings (#100)

## [0.3.x] - 2026-05-12 .. 2026-06-02

- 0.3.0: composer web fetch, image aspect-ratio fit, SVG color fixes (#139, #146)
- 0.3.1–0.3.8: stability fixes (template upload in local mode, template
  analysis via `uv run`), workshop content, one-click deploy buttons
  (#167, #168, #170, #171)

## [0.2.x] - 2026-05-01 .. 2026-05-11

- 0.2.0: agent separation, parallel slide generation, model config refactor (#71)
- 0.2.1: fontSize token discipline check, Python 3.14 compatibility fixes
  (#133, #136)

## [0.1.0] - 2026-05-01

- Initial release: spec-driven slide generation (Engine json ↔ pptx, CLI,
  local/remote MCP servers, Strands Agent, React Web UI, CDK stacks)

[Unreleased]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.3.8...v0.4.0
[0.3.x]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.2.1...v0.3.8
[0.2.x]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.1.0...v0.2.1
[0.1.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/releases/tag/v0.1.0
