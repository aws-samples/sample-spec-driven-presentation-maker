# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(while in 0.x, breaking changes may occur in MINOR releases).

Entries before v0.5.0 were written retroactively as summaries.

## [Unreleased]

### Added

- **Scaffold pass in the compose workflow** — before the parallel content
  composers fan out, the orchestrator now dispatches one composer with
  `task_instruction: "Scaffold pass."` (a new composer mode alongside
  `"Consistency review."`). It batch-writes the style- and role-derived
  elements every slide shares — decoration from the art direction (accent
  bars, footer, title band) and role elements with per-slide parameters
  (titles/subtitles drafted from the outline, section labels) — into every
  `slides/*.json` via a single programmatic `run_python` for-loop (no
  individual slide edits in this mode). Elements that require imagining a
  slide's content stay with the content composers. Page numbers are
  explicitly forbidden as elements — they come from the template's native
  slide-number placeholder. Content composers then read the existing JSON
  and build on the frame instead of rewriting whole files. Cross-slide
  decoration consistency moves from post-hoc review fixes to
  by-construction, and near-identical JSON is no longer re-emitted per
  slide (token savings). Persona-only change (`personas/composer.md`,
  `vibe.md`, `spec.md`).
- **Per-user usage measurement** (#326) — Bedrock usage logs (`bedrock_usage`)
  now carry `user_id` / `session_id` / `deck_id` (composer invocations
  included), and new structured events count slides per user:
  `slides_composed` (per compose_slides call) and `slides_built` (per
  successful PPTX build). A new opt-in flag `features.enableTransactionSearch`
  (or `deploy.sh --enable-transaction-search`) enables CloudWatch Transaction
  Search for span-level per-user token queries and the GenAI Observability
  dashboard. See [Measuring Usage](docs/en/usage-measurement.md).
- **`sendToBack` element key — z-order control over placeholders** — elements
  normally render in front of template placeholders (the builder fills
  placeholders first), so a full-bleed decorative image always covered the
  title with no recourse. `"sendToBack": true` moves an element behind the
  placeholders; multiple marked elements keep their relative order. The
  PPTX importer now emits it automatically for shapes that preceded the
  first used placeholder in the source slide, so imported decks keep their
  original stacking. (#316)
- **`pptx_builder.py preview -o/--output-dir`** — the CLI preview can now
  write PNGs to a chosen directory (e.g. `{deck_dir}/preview`) instead of
  always using a temporary `_work/` folder; `--no-grid` already existed.
  `sdpm.api.preview` gains the matching `output_dir` parameter. (#316)
- **`repr` and `__name__` in the `run_python` sandbox** — agent code using
  `repr()` or the `__main__` idiom no longer needs rewriting. (#316)
- **`translate` mode with a `/sdpm-translate` entry point** — deck translation
  is now a first-class mode: `start_presentation(mode="translate")` serves
  `personas/translate.md`, and a fourth thin skill entry point
  (`skills/sdpm-translate`) exposes it as a slash command in every client
  that maps skills, alongside vibe/spec/style. The persona drives the
  existing `translate-pptx` workflow (extract → dictionary → apply → build)
  and makes the agent itself fill the translation dictionary.

- **`make install-kiro` generates a dedicated composer agent again** —
  `<KIRO_HOME>/agents/sdpm-composer.json` gives parallel compose workers the
  sdpm MCP server only, with pre-approved tools and a generous startup
  timeout. Without it, workers fall back to a general-purpose agent that
  cold-starts every MCP server in the profile per worker; on MCP-heavy
  profiles this made some parallel composers miss the sdpm server
  nondeterministically (observed with 30+ registered servers). The generated
  config is a thin pointer — its prompt is a `file://` reference into
  `personas/composer.md`, never inline behavior — and it is lifecycle-managed
  by the same ownership audit as the rest of the wiring (own/stale are
  regenerated, foreign/unknown are never touched; power mode still removes
  it). v0.5.3 dropped generation because the old installer could not manage
  the file safely across checkouts; the ownership audit removed that reason.

- **Mode entry points are back, as thin dispatchers** — `skills/sdpm-vibe`,
  `skills/sdpm-spec` and `skills/sdpm-style` let users pick a mode explicitly
  (`/sdpm-vibe` and friends in clients that expose skills as slash commands).
  v0.5.0 removed `skills/` because each file had grown a full copy of the mode
  behavior that then drifted; these are ~20 lines each and contain no behavior
  text. They call `start_presentation(mode=...)` and stop, so `personas/*.md`
  remains the only definition. A test fails if any substantial persona line
  reappears in an entry point.
- **The repository root is an Agent Plugins 1.0.0 package** — `plugin.json` and
  `mcp.json` make it loadable by Kiro (as a Power), Cursor, GitHub Copilot and
  VS Code without a client-specific installer. `mcp.json` points `uv` at
  `${PLUGIN_ROOT}/servers/local` and puts the virtualenv under
  `${PLUGIN_DATA}`, because clients copy the plugin into an install cache that
  may be read-only and is replaced on update.
- **Codex support** — `.codex-plugin/plugin.json`, a bundled MCP server
  definition in `.mcp.json`, and a repo marketplace at
  `.agents/plugins/marketplace.json`, so `codex plugin marketplace add ./` is
  enough to install the checkout locally. Codex was previously limited to the
  Layer 1 CLI path.
- **Claude Code exposes the same entry points** — `.claude-plugin/plugin.json`
  gained `skills` (bumped to 0.3.0). Its `agents` and `mcpServers` blocks are
  unchanged.
- `clients/kiro/install.py` gained `--mode {auto,legacy,power}`, `--kiro-home`
  and `--replace-existing`.

### Fixed

- **Bedrock invocation-logging custom resource is now idempotent** — it
  previously overwrote an existing account-level logging configuration on
  deploy; it now checks first and skips if logging is already configured to a
  different destination (matching the documented "skipped if already
  configured" behavior). (#326)
- **The deck-translation workflow is reachable again** — `translate-pptx`
  existed as a workflow document but nothing routed to it: the MCP server
  instructions menu stopped at D and no persona mentioned it, so an agent
  asked to translate a deck could only find it by spontaneously calling
  `list_workflows`. It is now Workflow E in the server instructions
  (pointing at the new translate mode), with routing lines in the vibe and
  single personas. The translate scripts also
  moved from the repo-root `scripts/` (deploy helpers, not shipped with the
  skill) to `sdpm/scripts/` next to `pptx_builder.py`, so the workflow's
  `scripts/translate_extract.py` commands resolve relative to the skill root
  like every other workflow — and Layer 1 skill installs actually get them.

- **`make install-kiro` no longer hijacks another checkout's Kiro setup** —
  the MCP registration was re-registered with `--force` whenever the existing
  `sdpm` entry pointed elsewhere, and the composer-agent cleanup deliberately
  deleted configs generated for any checkout. Running the installer from a
  second clone therefore repointed a working install. Every artifact the
  installer can write (MCP registration, skill symlinks, legacy composer agent)
  is now classified as own / stale / foreign / unknown against the current
  checkout; only own, stale and absent are written, foreign requires
  `--replace-existing`, and unknown is never touched. Conflicts exit non-zero
  with a report instead of succeeding quietly.
  Behavior change: a leftover pointing at a checkout that still exists is now
  left alone. One pointing at a *moved* checkout is still repaired, which was
  the staleness that cleanup existed for.
- **`clients/kiro/install.py` honours `KIRO_HOME`** — it hardcoded `~/.kiro`,
  so installs into a non-default Kiro profile silently wrote to the wrong one.
  `KIRO_HOME` is now also exported to the `kiro-cli` child process, since
  `mcp add --scope global` resolves "global" itself. Powers are global-scope
  only, so a separate profile is the only way to keep a Kiro CLI install and a
  Power install from colliding.

- **Importer: white text baked onto light cards (white-on-white)** — the
  converter adopted the shape style's `fontRef` color even when the shape's
  own `lstStyle` carried an explicit text color, which outranks `fontRef`
  in OOXML. Decks whose light-fill cards define dark text via `lstStyle`
  came back with `fontColor: #FFFFFF`. (#316)
- **Importer/builder: arrowheads lost their size** — `tailEnd`/`headEnd`
  `w`/`len` attributes are now round-tripped (`arrowEndWidth`,
  `arrowEndLength`, `arrowStartWidth`, `arrowStartLength`), so a large
  arrowhead no longer comes back as the small default.
- **Importer/builder: gradient direction distorted on non-square shapes** —
  the `scaled` attribute of linear gradients was dropped on import and
  forced to `1` on build. A `scaled="0"` gradient (true geometric angle) on
  a wide bar now renders at its original angle.
- **Importer/builder: partially-rounded rectangles on pictures** — image
  masks were limited to a 9-name allowlist and dropped their adjustment
  values. Any OOXML preset now passes through (`round1Rect`,
  `round2SameRect`, …) with its `avLst` preserved, so e.g. a picture panel
  with one rounded corner survives the round trip.
- **measure: white-on-white false positives over gradient shapes** — the
  contrast judge only recognized gradients written as `style="fill:url(…)"`;
  LibreOffice sometimes emits `fill="url(…)"` as an attribute, making the
  background "unknown" and falling back to the white slide background. Both
  forms are now treated as unknowable background (contrast check skipped).
  (#316)
- **lint: `shape-unknown-name` noise on imported decks** — camelCase raw
  OOXML presets (which the builder renders verbatim) are no longer flagged;
  pure-lowercase typos still are. (#316)

## [0.7.1] - 2026-08-05

### Fixed

- **Nested styled-text notation no longer leaks raw tags onto slides** —
  agents sometimes emit `{{bold:{{#FF0000:X}}}}` instead of the canonical
  `{{bold,#FF0000:X}}`; the parser could not see through nesting and rendered
  the inner tag as literal text. A flatten pre-pass now normalizes nesting
  (any depth, partial nesting included) to the comma form, with inner
  attributes taking priority. Non-nested input is untouched. (#123)
- **Builtin template download works from the Web UI** — downloading blank-dark /
  blank-light did nothing: the download used a `fetch()`+blob path that requires
  CORS, and the builtin resource bucket has no CORS configuration (user templates
  live in a different bucket that has one). Downloads now use the same direct-link
  navigation as deck PPTX downloads (no CORS involved), the presigned URL carries
  `Content-Disposition: attachment`, and failures show an error toast instead of
  silently doing nothing. (#281)
- **`grid` tool returns actionable errors and supports `%` / `repeat()`** —
  unsupported CSS track syntax (`auto`, `minmax()`, previously also `%` and
  `repeat()`) crashed with an uncaught `ValueError` instead of an error message
  the agent can react to. `%` and `repeat(n, X)` are now supported, unsupported
  syntax returns `{"error": ...}` naming the offending token, and the supported
  subset is documented in the tool docstring and grid guide. (#282)
- **Live preview: icons relying on even-odd fill no longer render as solid
  boxes** — LibreOffice's SVG export declares `fill-rule="evenodd"` only on the
  root `<svg>`, which the per-component fragment split dropped, so multi-subpath
  line-art icons (many AWS resource icons) lost their cutouts and appeared as
  filled rectangles in the live preview (final PNGs were unaffected). Root
  inheritable attributes are now propagated onto each fragment. (#288)

- **Architecture diagram box auto-height now works on non-16:9 templates and
  with CJK text** — the engine used a fixed 16:9 pt-to-px ratio for text
  measurement, causing boxes to undersize on 4:3 and other aspect ratios, and
  did not account for fullwidth (CJK) character width. `analyze_template` now
  reports `ptPerPx` in `slide_size`, the agent records it in `deck.json`
  `slideSize`, and `arch_diagram` accepts a `pt_per_px` parameter for accurate
  calibration. (#285)
- **Remote MCP: `analyze_template` now includes `slide_size` in cached
  results** — the cached template analysis omitted the `slide_size` field, so
  subsequent calls returned an incomplete response and the agent could not
  populate `deck.json` `slideSize`. (#285)

- **Custom templates with non-16:9 slide sizes (4:3 etc.) now lay out correctly** —
  the engine's px coordinate system followed the template width but assumed a
  fixed height of 1080, so 4:3 decks left the bottom quarter of every slide
  empty, reported false out-of-bounds warnings, mismatched placeholder
  coordinates, mis-measured text overflow, and rendered cropped previews in the
  Web UI. The canvas is now derived from the template's real dimensions
  (1920 px wide, height following the aspect ratio — 4:3 becomes 1920×1440),
  and `analyze_template` / `deck.json` carry the canvas size so slide
  composition uses the full slide. Behaviour for 16:9 templates is unchanged.
  Known limitation: architecture diagram boxes with an omitted `box.height`
  can still under-estimate text height on non-16:9 templates — specify
  `box.height` explicitly. (#208)
- **Live slide preview: the first few slides now animate** — animation was
  suppressed for 3 seconds after the slides tab appeared, and because a new
  deck switches to that tab as soon as slides arrive, the first slides were
  always shown instantly. Suppression is now based on whether the slides
  already existed when the view mounted, instead of a timer.
- **Live slide preview: the PNG fallback now actually appears** — the error
  state was reset on every 1-second poll, so the fallback was unmounted before
  it could be seen; a failure to find the render container also marked the
  slide as permanently processed, leaving an empty black box. Slides with
  nothing to draw now fall back to the rendered PNG, and the fallback image
  retries expired signed URLs.

- **AWS: uploaded custom templates now apply to PPTX generation** — the remote
  server's template resolution only searched builtin templates, so a deck
  referencing an uploaded user template silently fell back to
  `blank-dark.pptx`. Generation now resolves user templates first (same order
  as `analyze_template`), and an unresolvable template name raises an explicit
  error listing available templates instead of silently using the wrong
  design. (#206)

## [0.7.0] - 2026-08-03

### Added

- **Web UI: live design studio** — full visual redesign. Light/Dark/System
  themes (default dark), 90–125% text scaling, studio color tokens (5 agent
  work colors, ink for deliverables, red reserved for errors), and a
  two-voice typography system (Bricolage Grotesque for UI chrome, Fraunces
  for document surfaces).
- **Web UI: artifact-first review surfaces** — chat tool activity as a
  compact agent work ledger; brief as a reviewable contract document with
  approval state; outline as single-column narrative slides (number rail,
  slim skeleton cards, enriched slide faces with an evidence/visual/notes
  spec sheet); art direction as per-slide style cards sharing the same rail
  grammar, with template and style sections on one alignment axis.
- Outline workflow now asks for `##` section headings when a deck has
  distinct parts, so review surfaces can render the story arc as chapters.

### Changed

- Style cover extraction is unified client-side: both `/styles` APIs
  (cloud and local) now serve raw style HTML (`html` field replaces
  `coverHtml`), and the style gallery opens previews with zero additional
  round-trips.
- Style previews and thumbnails keep the style author's own canvas
  background instead of forcing transparency.

### Fixed

- Style thumbnails rendered the first slide at 70% (standalone-viewing
  `body zoom` was not reset in the cloud cover path), leaving gutters
  around the cover; slides now fill thumbnails edge-to-edge.
- Unpainted regions of style slides (rounded corners, frame decorations)
  showed as opaque white inside the dark UI.
- One deck slide always fits the viewport in the full-size carousel view.
- Prose art direction (`art-direction.md`, no style selected) rendered as
  raw markdown inside an iframe; it is now typeset as a document.

## [0.6.0] - 2026-08-02

### Breaking

- **Stateless attachment pipeline** — `upload_file`, `read_uploaded_file`, and
  public MCP `pptx_to_json` tools are removed. Use `read_attachment(source)`
  and `import_attachment(source, deck_id)` instead. The new tools are stateless
  (no session storage, no uploadId) and accept local paths, S3 keys, or URLs
  directly.
- **`measure_slides` standalone tool removed** — measurement is now triggered
  exclusively via `run_python(measure_slides=[...])`.
- **`list_asset_sources` tool removed** — call `search_assets(query="")` for
  the same discovery listing (sources with counts).
- **`run_python` / `run_style_python` `save` parameter removed** — writes
  always persist; the deprecated flag is no longer accepted.
- **`run_python` `files` parameter removed** — use `read_attachment` to access
  uploaded file content, then reference by path in code.
- **Session restart required** — after `git pull`, restart all Local Web UI /
  ACP sessions. The next spawn will pick up the updated agent definitions
  (`agents-sync.ts` re-derives from `acp-agents/`). `make install-kiro` is
  only needed for global MCP config cleanup, not for allowlist updates.

### Changed

- `search_assets` now supports discovery mode: calling with an empty query
  (`query=""`) returns all asset sources with counts, replacing the removed
  `list_asset_sources` tool.
- `diff_pptx` now accepts committed import bundle directories as input,
  enabling the hand-edit sync workflow without the public `pptx_to_json` tool.
- Cloud file attachments use `POST /attachments/presign` + direct S3 PUT;
  Local Web UI uses `POST /api/attachments`. The `[Attached:...]` marker
  format is now `[Attached:{"v":1,"name":"...","source":"..."}]`.

### Fixed

- Cloud and local ACP deck agents now expose `arch_diagram`, as required by the
  composition workflow, so architecture, system, and flow diagrams use automatic
  routing and crossing minimization instead of silently falling back to manual
  placement.
- Attachment presigned PUTs now use Signature Version 4 — S3 rejects the
  conditional write (`If-None-Match`) with legacy SigV2 URLs, which broke all
  browser uploads in some regions (e.g. ap-northeast-1).
- The Web UI no longer sends a message when an attachment upload fails: input
  and attachments are kept for retry and the actual error (e.g. quota
  exceeded) is shown instead of a generic failure.
- Per-user raw attachment caps recalibrated for internal/team deployments
  (1000 objects / 50GB, overridable via `ATTACHMENT_MAX_OBJECTS` /
  `ATTACHMENT_MAX_BYTES`), and S3 lifecycle rules are prefix-only so
  attachment objects from pre-0.6 releases (which carry no `sdpm-class` tag)
  also expire. Deployments upgrading from the old upload pipeline should
  purge leftover `uploads/` objects — they otherwise count toward the quota.
- `servers/remote/constraints.txt` regenerated via `make lock`;
  `cachetools` / `protobuf` are pinned by `aws-opentelemetry-distro` and are
  now excluded from Dependabot bumps until the distro itself is upgraded.

## [0.5.3] - 2026-08-01

### Changed

- **Kiro CLI: composer sub-agents are now self-spawned** — `make install-kiro`
  no longer generates `~/.kiro/agents/sdpm-composer.json`; the orchestrating
  agent spawns composer workers itself and pulls the composer behavior through
  `start_presentation(mode="composer")`. Upgrading from v0.5.2 or earlier,
  re-run `make install-kiro` once: it removes the legacy generated agent file
  (only if unmodified; a customized file is left in place with a warning).
- `start_presentation` now accepts `mode="single"` (one agent handles dialogue
  and composition end-to-end), making every persona reachable through the port.

## [0.5.2] - 2026-08-01

### Changed

- **`run_python` persistence semantics unified**: file writes now always
  persist — the `save` flag is deprecated and ignored (silent data loss when
  omitting `save=True` on Cloud is no longer possible). The deck's PPTX
  artifact refreshes automatically whenever the deck changes;
  `measure_slides` remains the trigger for the expensive verification pass
  (render, text overflow measurement, previews). Cloud sandbox write-back is
  now diff-based (changed/new files only), preventing a stale sandbox copy
  from overwriting newer S3 writes

### Fixed

- Cloud: superseded PPTX artifacts are now deleted after each refresh — the
  automatic artifact refresh no longer accumulates orphaned objects in S3
  (`update_deck` returns previous values via `UPDATED_OLD`)

## [0.5.1] - 2026-07-31

### Added

- `make doctor` — diagnoses local setup (uv / LibreOffice / poppler, checkout
  path anchors) with a moved-checkout hint
- `make smoke` — boots the local MCP server over real stdio and verifies
  template/persona resolution (also runs in CI)
- GitHub Releases are now created automatically on tag push (notes extracted
  from this changelog)

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

[Unreleased]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.7.1...HEAD
[0.7.1]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.5.3...v0.6.0
[0.5.3]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.3.8...v0.4.0
[0.3.x]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.2.1...v0.3.8
[0.2.x]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.1.0...v0.2.1
[0.1.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/releases/tag/v0.1.0
