# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(while in 0.x, breaking changes may occur in MINOR releases).

Entries before v0.5.0 were written retroactively as summaries.

## [Unreleased]

### Added

- **Sign-up settings for the default Cognito user pool.** `auth.selfSignUp` in
  `infra/config.yaml` turns self sign-up on, and `auth.allowedEmailDomains` limits it to the
  listed email domains. A Cognito Pre sign-up Lambda trigger checks the domain of each
  sign-up request: exact match, case-insensitive, subdomains not included (list each one).
  Users created by an administrator are not checked. `allowedEmailDomains` without
  `selfSignUp: true`, or an entry that is not a domain name, fails the synth. See
  [Developer guide](docs/en/developer-guide.md#default-amazon-cognito-user-pool).
  `infra` now has CDK assertion tests (`cd infra && npm test`), run in CI.
- **`agent-spectrum` style.** A bundled concept style made to be watched rather than presented
  (screen recordings, animated previews, README stills): a flat near-black ground, light type,
  and the Web UI's five builder colours (blue, teal, violet, amber, pink) in a fixed order, used
  only to tell the parts of a figure apart. Every slide carries a five-segment stripe; labels and
  tags are monospaced at 16pt so they stay legible when a slide is shown at README width. The
  README key visual is built in it.
- **Comments on the preview.** Mark what to change directly on the slides and send it as one
  change request (修正依頼). Turn on the **Comment** tool from the preview header, with `C`,
  or from the button that appears when hovering a slide. Drag to outline an area, or click
  to place a frame when nothing is being edited (a click while a frame is selected only
  confirms it). Each frame gets a letter name (A, B, …, AA) that comments can reference with
  `@A`; a frame may stay without a comment (a place another comment points to), and only an
  explicit delete (with undo) removes it, or Esc on a frame just drawn. Frames can be moved
  and resized, hovering a frame shows its comment, and unsent frames survive a reload. They
  collect above the chat input, where **Request changes** (「修正を依頼」) sends them with
  whatever is typed in the input as the message, once a frame has a comment or the message is
  set (until then the frames list says what is missing). The server writes `reviews/<id>.json` in the
  deck — only what was sent (note, slide size, comments with frames in slide pixels) plus a
  short guide for the composers — and returns the chat message the Web UI sends: the note and
  the comments grouped by slide, the file path, how to dispatch them (one composer per slide,
  given the file path and that slide's comment names) and a `[review:<id>]` marker. The
  orchestrator works from the message alone; the composers read the file. Nobody rewrites the
  file, each new request replaces the deck's previous one, and the role documents are
  unchanged (the feature is the Web UI's). The chat shows the request as a card with its
  frames, built from the message so it restores from chat history on both the AWS stack and
  locally; it shows no progress (the agent's reply tells the result), and the sent frames leave
  the slides once the request is created. When the chat send fails, the frames and the note go
  back to the drafts and the input to be sent again. HTML decks show stacked static slide previews while the tool is on, so frames and the
  agent see the same layout. New API route `POST /decks/{id}/reviews` (edit permission,
  validated frames, slugs and sizes) with a matching local route; the message and guide texts
  live once in `shared/review_template.json`. `get_deck` now returns `slideSize` for PPTX
  decks too, and the cloud sandbox syncs `reviews/`. (#473)

### Changed

- **Faster first output on every Cloud turn.** The agent no longer waits for the optional
  AWS Knowledge and AWS Pricing MCP servers, the Memory session, and `start_presentation` one
  after another before it calls the model. It fetches `start_presentation` as soon as the
  Presentation Maker server is connected and loads the Memory session at the same time. The
  AWS Knowledge and AWS Pricing MCP clients are connected once per agent process and reused
  on later turns (neither uses the signed-in user's token). If one is still connecting when
  the first turn is ready, that turn goes ahead without it and the chat shows it as not
  connected in time; later turns use it once it has connected. A client whose server has
  stopped is rebuilt on the next turn, under the same rule. On SIGTERM the agent also closes
  these clients (and the AWS Pricing server process) while it exits. The role documents and each
  user's style and template list are fetched through the MCP server once per agent process
  and kept in memory, so later turns make no `start_presentation` call. A style or template
  added during the session shows up in the system prompt in the next agent session; the
  agent's `list_styles` / `list_templates` tools still return the current lists.
- **The first reply in a new Cloud deck no longer waits for the LibreOffice warm-up.** The MCP
  server started its background LibreOffice warm-up from the platform's health checks: right
  after each microVM was restored, and again every 5 minutes. It then competed with the
  agent's first `start_presentation` for disk and CPU (dev: 0.5–30 s, 0.7 s without it). The
  warm-up now starts once per process, after the client has sent no request for 3 seconds
  (on a new deck, right after `start_presentation`; in each composer's own microVM, after
  it has connected and before its first tool call), and does not run again once it has
  succeeded. The
  server also reads the AWS API definitions, the bundled style list and the role documents at
  startup, so the V2 snapshot holds them (dev: 0.73 s → 0.50 s).
  The MCP runtime's `platformVersion: "V2"` is now declared in `infra/lib/runtime-stack.ts`
  instead of being set outside CloudFormation, and its `DEPLOY_TIMESTAMP` environment variable
  is removed: a deploy that changes neither the image nor the configuration no longer creates
  a runtime version (each one rebuilds the V2 snapshot).
  **Upgrade:** a new deployment now runs the MCP runtime on V2 instead of V1; see
  [Security](docs/en/security.md#agentcore-runtime-platform-versions).
- **Self sign-up is now off by default in the AWS stack.** The default Cognito user pool
  accepts only users created by an administrator (Cognito console or
  `aws cognito-idp admin-create-user`, see
  [Deploy guide](docs/en/deploy-cloudshell.md#creating-a-cognito-user-layer-4)); the sign-in
  page no longer offers sign-up. One-Click Deploy still creates the first user for
  NotificationEmailAddress.
  **Upgrade:** the next deploy of `SdpmAuth` switches an existing user pool to
  administrator-created users. The user pool is updated in place: existing users keep their
  accounts and sign in as before. To keep self sign-up on, set `auth.selfSignUp: true` in
  `infra/config.yaml` before you deploy.
- **`run_python` returns the same result for PPTX decks locally and in the cloud.** The
  post-processing after a PPTX deck edit (full build, render of the affected slides,
  measurement, compose, previews) now lives in `sdpm.api.refresh_pptx`; both servers only do
  the I/O around it. The measurement and warnings part of the result follows the cloud format.
  Before:

  ```
  Local  warnings          ["fonts auto-detected from template", "page02 (Title Only) offset: -35.2% (top-heavy)", "  page02(body) …"]
                           (every build warning without measure_slides, the measured pages' lines with it;
                           the list replaced {"outline": …})
         lint_diagnostics  [{slide, element, rule, message}]   (copy of errors.lintDiagnostics)
         measure           "📐 Text measurement …" (with "⚠ Layout issues") | "No matching slides found for given slugs"
                           | "Measure error: …"
         invalid layouts   not reported
  Cloud  warnings          {"layoutBias": [{slide, layout, bbox, offset, direction}]}   (replaced {"outline": …})
         measure           "📐 Text measurement …" (no "⚠ Layout issues") | '{"error": "…"}'
         errors.<slug>     {"invalidLayout": "…", "available": […]}   (measured slugs)
         build warnings    not reported
  ```

  After, on both servers:

  ```
  warnings   {"outline": "…",                                  (outline lint; always kept)
              "layoutBias": [{slide, layout, bbox, offset, direction}],
              "build": ["  page02(body) element[4]: include src …"]}
             layoutBias and build come with measure_slides only, for the measured pages
             (full-deck page numbers); build holds the "pageNN" lines, not the layout-bias lines
  measure    "📐 Text measurement …" plus the "⚠ Layout issues" section when the judge finds any
             | '{"error": "No matching slides found for given slugs"}'
             | '{"error": "LibreOffice SVG export failed"}' | '{"error": "…"}'
  errors     {"lintDiagnostics": […], "<slug>": {"invalidLayout": "…", "available": […]}}
  ```

  Migration: read build warnings from `warnings["build"]` (a dict now, not a list) and lint
  results from `errors.lintDiagnostics` (`lint_diagnostics` is gone); parse `measure` as JSON
  when it does not start with `📐`. Transport keys stay as they were: locally `pptx`,
  `compose`, `compose_error`, `preview_files`, `preview_error`, `render_error`, `preview`
  (`unavailable`, with measure_slides); in the cloud `previewHint`, `readOnly`, and the
  `pptx_error` texts. The role documents are unchanged (none of them names these fields).
  Side effects: the local live preview's compose files now carry `sourceHash` and are not
  written for a slide whose layout name is invalid (it showed the fallback layout), and a
  written slide's older compose files are removed. In the cloud, the rebuilt PPTX goes through
  the same build as `generate_pptx` (icon check, `autoSpacing`, `defaultBackground`, an
  auto-set `defaultTextColor` instead of a failure), and previews are rendered from the changed
  slides instead of the whole deck, as locally (a template whose master shows the slide number
  as a plain text field then shows the partial render's number in those previews and compose
  files, as the local ones always did). In the cloud, `previewHint` is left out when the
  render of the changed slides failed (the same result's `pptx_error` / `measure` says why).
  `sdpm.engine.schema.read_deck_format` replaces five
  separate deck.json format readers; the CLI no longer crashes on a deck.json that is not an
  object.
- **The README opens with the key visual.** An animation of the Web UI composing a seven-slide
  deck about SDPM (in `agent-spectrum`), the install commands right under it, then the same
  slide in seven bundled styles. The deck page, comment and Styles screenshots are retaken on
  that deck, and its slides replace the old six-slide sample. The deck (with the layout-pass
  version of each slide) and the scripts that build it through the Local server, replay the
  builds in the Local Web UI and record the GIF are in `docs/assets/src/hero/`; the gallery is
  built from `docs/assets/src/style-gallery/`. Both read the bundled styles at build time.
  `README_ja.md` shows the Japanese deck.
- **Documentation reorganized for first-time readers.** The README now shows example output
  and the three ways to use SDPM (your AI agent, the Web UI on your computer, a team server
  on AWS). `docs/en/getting-started.md` is the user guide; checkout setup and CDK deployment
  moved to `docs/en/developer-guide.md`, security notes to `docs/en/security.md`, and the
  migration guides to `docs/en/migration/`. The workflow and architecture diagrams are redrawn
  from the current code. New Japanese translations: custom templates and uninstall.
- **One Python lock for everything.** The repository root is now a uv workspace (`sdpm`,
  `servers/local`, `servers/remote`, `agent`, `api`) with a single `uv.lock`. The MCP Runtime
  and Agent Runtime images and the API Lambda bundle install exactly the locked versions,
  hash-checked, and never resolve dependencies at build time. The tests run against the same
  lock. Removed: `sdpm/uv.lock`, `servers/local/uv.lock`, `servers/remote/constraints.txt`,
  `agent/requirements.txt`, `agent/requirements.lock`, `api/requirements.txt`. To change a
  dependency, edit the member's `pyproject.toml` and run `make lock` (`uv lock`). (#475)
  - **Local installs:** `sdpm update` keeps working unchanged. The MCP server's environment
    moves from `~/.sdpm/checkout/servers/local/.venv` to `~/.sdpm/checkout/.venv`. You can
    delete the old `servers/local/.venv` and `sdpm/.venv` directories in the checkout.
  - **AWS deploys:** the Agent Runtime image now builds from the repository root (both images
    share the root `.dockerignore`, now an allowlist). The API Lambda bundle targets
    `manylinux_2_34` (the python3.13 runtime's Amazon Linux 2023) and is built by
    `scripts/bundle_api_lambda.sh`.
- **CI builds and starts what a deploy ships.** Both runtime images are built on linux/arm64
  and started (MCP `initialize` + `tools/list`, Agent `/ping`), and the API Lambda bundle is
  imported in the Lambda runtime image. This replaces the `container-deps` dry runs. The
  Python tests run on 3.13, the version the images ship, and the local smoke test runs on
  3.11, the oldest supported version, with only the local server's dependencies. (#474)
- **Dependabot's minor and patch updates for uv and GitHub Actions merge on their own** once
  the required CI checks pass (`.github/workflows/dependabot-auto-merge.yml`). Major updates
  and npm updates (`web-ui`, `infra`) are still merged by hand. (#476)
- **Upload conversion moved into the core.** The PDF / DOCX / XLSX / PPTX conversion of
  attachments now lives in `sdpm.tools.attachment.ingest` (formerly `shared.ingest`), so
  `sdpm-skill` now depends on `pypdf>=6.15.0`, `pdfplumber`, `python-docx` and `openpyxl`.
  Conversion results are unchanged. (#477)
- **One style per name in the AWS style lists.** When a user saves a style under the name of
  a bundled style (for example `report`), the Web UI style gallery (`GET /styles`) and the MCP
  Runtime's `list_styles` and `start_style` catalogue now list it once, as the user's style,
  instead of listing both. This is the rule Local already followed, and the style that
  `apply_style` and the gallery preview load was already the user's, so applied styles do not
  change. Agents on the AWS stack see one `report` entry (`"source": "user"`) where they used
  to see two. The Web UI gallery lists the user's styles before the bundled ones. The style,
  pin and template code of the API Lambda and the MCP Runtime now shares
  `shared/user_library.py`; DynamoDB keys and S3 paths are unchanged.
- **One set of attachment rules for every client.** How the orchestrator reads attachments
  and cites them in the brief and outline now lives only in `orchestrator.md` and the
  `attachments` guide, which every client reads: read with `read_attachment` first, list
  each source under the brief's **Sources** with the part the slides need (section, page or
  `read_attachment` line range), naming an attached file by its file name and `attachments/`
  path, point each slide's `evidence` at that part, and refer to imported material by the
  returned `bundlePath` plus the listed path. The AWS stack's agent prompt keeps only the
  `[Attached:…]` marker format (`agent/prompts/common/attachments.md`); its extra rules
  (content summaries in the brief, citation examples, importing only when composers need the
  file) are gone, so Cloud briefs follow the same rules as Local clients and every attached
  file is imported. Line references stay, now as the `read_attachment` line range in Sources
  and `evidence`.

### Removed

- **Deck sharing with specific users and the `collaborator` role (breaking).** The Share dialog (user
  search, collaborator list), the deck card's Share menu item and collaborator badge, and the
  **Shared** tab of the deck list are gone, together with `GET /decks/shared` and the
  `SHARED#` lookup in `shared/authz.py`. The feature never worked: nothing wrote `SHARED#`
  records, and the `/decks/{id}/share` and `/users/search` routes the dialog called did not
  exist. Deck roles are now owner / viewer / none with the permission matrix otherwise
  unchanged. Public / private visibility stays as it is: to show a deck to others, make it
  public (**Internal**) or download the PPTX / HTML. (#479)
  **Migration:** use public / private visibility, or download the PPTX / HTML and send the file.
- **Unused code.** Web UI components, helpers and dependencies that nothing called are gone,
  together with the `include=slideJson` option of `GET /decks/{id}` (now ignored), the local
  Web UI's `/api/agent/config` route and the API Lambda's direct document-parser
  dependencies. The Web UI used none of them. (#478)
- **The compose card's own stop button.** The **Cancel** button on the compose card (Cloud
  only), its "Stopping…" state and the summary of what each composer did before stopping are
  gone. To stop, use the main stop button next to the chat input: it stops the whole turn,
  compose included (Cloud ends the runtime session, Local sends ACP `session/cancel`). Its
  tooltip no longer changes to "Force stop" while slides are being composed. The cancel used a
  marker file written into the agent's microVM through the runtime's `/commands` API, and the
  agent told the composers to stop through a special tool result; both side channels are
  removed, and the `compose_slides` report no longer has a `cancelled` status.
- **The composers' per-slide time budget.** Composers no longer get a deadline (90 s per slide,
  `COMPOSER_SECONDS_PER_SLIDE`) or the "Time budget reached" notice that told them to stop
  polishing, and the compose card no longer shows composers as "rushed". The runaway guards
  stay: a composer is still stopped after 5 consecutive tool errors or a tool-call loop / cap.

### Fixed

- **Stopping a Cloud turn no longer leaves it running in the background.** The stop button
  ends the runtime session, and AgentCore then sends the agent's process SIGTERM. The agent
  used to wait for the running turn to finish, so the turn and its composers kept calling
  tools and writing slides, MCP calls and Memory events until the platform ended the
  process 10–60 seconds later. The agent now stops on SIGTERM: it ends the running turns,
  drops every tool call, direct MCP call and Memory event from then on, and exits within
  3 seconds. Composers also stop when their turn is cancelled, even after the parent turn
  has ended (they used to miss the cancel and could keep composing for minutes), and a
  cancelled compose returns at once with status `cancelled` instead of waiting for them.
  A call the agent had already sent to the MCP Runtime still completes there.
- **A slide's live preview is no longer taken from another slide's compose file.** The API
  picked a slide's latest `compose/{slug}_{epoch}.json` by the prefix `compose/{slug}_`, so slug
  `slide` also took the legacy numbered files `slide_N_*.json`, and in a deck without an outline
  slug `intro` could take slide `intro_2`'s file. Writing a slide's compose on the AWS stack
  deleted the older files with the same prefix, so it also removed `intro_2`'s. Both now match
  the whole name, as the MCP Runtime, the local server and the local Web UI already did.
- **The API Lambda no longer leaves template copies in `/tmp`.** Listing templates (when a
  builtin template had to be analysed) and registering an uploaded template downloaded the
  `.pptx` into a temporary directory that was never removed, so a warm Lambda container
  collected them. The download now goes to a directory that is removed after the analysis.
- **Local Web UI no longer opens the deck folder as a deck.** Starting a new chat briefly
  switched the view to a deck named after the deck folder (`SDPM-Presentations`), which the
  local server answered with 404, and every new deck sent a `PATCH` the local server does not
  have (405). The deck folder is no longer taken for a deck, and Local mode skips the `PATCH`
  (it already links the chat session to the deck on its own). (#480)
- **Local Web UI frees a deck's agent process when its turn ends.** After a turn that used
  composer sub-agents, or the first turn on a reopened deck whose process had been stopped,
  the local server kept marking the kiro-cli process as busy: kiro-cli sends no end-of-turn
  notice for sub-agent sessions, and reopening a session replays its history under its own
  id, which the server took for a sub-agent that never finished. Busy processes are never
  stopped to make room, so the limit of three processes stopped the most recently used idle
  one instead of the oldest, or was not enforced at all once every process looked busy. The
  turn now ends when kiro-cli answers the chat's prompt, and sub-agent sessions are tracked
  only within the turn (the stop button still cancels them).
- **Cloud `import_attachment` reports conversion errors.** A failed conversion (for example a
  limit hit while extracting) came back as `IMPORT_ERROR` with the message `'importKey'`; the
  tool now returns the actual error code and message.
- **Cloud `read_attachment` works again.** Since 2026-10-08 every call failed with
  `validation error for read_attachmentOutput — Input should be a valid string`: the remote
  server declared the tool as returning a string while it returns the result object, and the
  MCP output check rejected it. Agents fell back to `import_attachment`, so attachments still
  arrived, but without the paged read first. The tool now returns the same object as the
  local server, and a test checks every remote tool's declared return type against what it
  returns.
- **Local live preview keeps cut-outs in icons and shapes.** LibreOffice sets `fill-rule="evenodd"`
  (and the default stroke width and join) once on the root `<svg>`; the local server dropped
  it when splitting the slide into fragments, so shapes with holes rendered filled in the
  Web UI's live preview. The local and remote servers now share one compose module
  (`sdpm.engine.preview.compose`), which carries the remote fix for this and the local
  removal of `textLength` / `lengthAdjust` (WebKit squashed glyphs to fit them), so the
  cloud live preview strips those too.
- **Previews no longer add a shadow to shapes and lines on light templates.** Shapes and
  connectors built from slide JSON kept python-pptx's default `<p:style>`, whose effect
  reference points at the template theme's shadow. The builder wrote an empty `<a:effectLst/>`
  to cancel it, which PowerPoint honours but LibreOffice ignores, so preview PNGs and the
  Web UI live preview drew a shadow under every rectangle (visible on `blank-light`). The
  effect reference now points at no theme effect (`idx="0"`), so an element has a shadow only
  when its JSON asks for one, as the slide JSON spec says.

### Security

- **Agent and MCP runtime sessions are bound to their owner.** New session ids created by
  the Web UI start with a prefix derived from the signed-in user (`shared/session_owner.py`,
  mirrored in `web-ui/src/lib/sessionId.ts`), and the agent and the MCP server admit such an
  id only for that user. Each runtime process serves one user. Existing decks keep their
  chat: a chat id from before this change is admitted when AgentCore Memory holds that
  user's history for it, and a deck without history continues under the user's own id. The
  agent forwards an owner-prefixed id to the MCP runtime (also for composer groups,
  `<id>-gN`). A refused call gets an error event with no details; a chat tab opened before
  the update may be asked to reload the page once (new error code
  `session_reload_required`). Deploy the Web UI first, then SdpmRuntime, then SdpmAgent.
  Local mode is unchanged.
- **The AgentCore runtimes allow only the operations the app uses.** The agent and MCP
  runtimes, their `DEFAULT` endpoints and the named endpoints `sdpm_agent_endpoint` and
  `sdpm_endpoint` now carry a resource-based policy (`AWS::BedrockAgentCore::ResourcePolicy`,
  managed in `infra/`) that allows `InvokeAgentRuntime` and `StopRuntimeSession` and denies
  `InvokeAgentRuntimeCommand`. Any other runtime operation is refused. Chat, the stop
  button, the agent's calls to the MCP runtime and external MCP clients keep working; a
  caller that ran commands in a runtime session through `InvokeAgentRuntimeCommand` now gets
  403.
- **Narrow the agent's execution role to what it uses.** The agent role no longer has access to
  the decks table or the PPTX bucket (deck storage is the MCP server's), and the agent runtime no
  longer gets the `DECKS_TABLE` / `PPTX_BUCKET` variables. AgentCore access is limited to the
  Memory events the session manager writes and reads, on the agent's own Memory; ECR pulls to the
  image repository; and the role explicitly denies user-id delegation
  (`InvokeAgentRuntimeForUser`, `GetWorkloadAccessTokenForUserId`) and any call made through an
  AWS-managed MCP server. The trust policies of the agent and MCP runtime roles accept AgentCore
  only for resources of the deploying account and Region (`aws:SourceAccount` /
  `aws:SourceArn`). The MCP runtime role drops its unused AWS Marketplace permissions and its
  ECR pull on `*`, and the API Lambda's `ListEvents` is limited to the agent's Memory.
- **Limit the AWS knowledge tools to documentation tools.** The agent connects to the public AWS
  Knowledge MCP Server endpoint (`knowledge-mcp.global.api.aws`) and offers its model only
  `aws___search_documentation`, `aws___read_documentation`, `aws___retrieve_skill`,
  `aws___list_regions` and `aws___get_regional_availability`. The `mcp-proxy-for-aws`
  dependency is removed.
- **The agent accepts `prompt` as text only.** An invocation whose `prompt` is not a string is
  answered with a `bad_input` error.
- **The agent no longer sees the user's id in Cloud attachments.** The upload handle the API
  returns and the Web UI puts in the `[Attached:…]` marker is now `uploads/{uuid}/{name}`
  instead of the S3 key `uploads/{userId}/{uuid}/{name}`. The MCP server builds the S3 key from
  the signed-in caller, so a handle can only name the caller's own uploads; `read_attachment`
  and `import_attachment` return the handle in their results and errors, and errors that
  name an S3 key under the user's prefix have the id removed. The S3 layout, the per-user
  quota and the 90-day expiry are unchanged, so nothing is migrated. During a transition the
  previous form is still accepted for the caller's own uploads (and answered with the new
  handle); another user's id in it is refused without repeating the id. The previous form
  will be removed in the first minor release after 90 days from this release, when every
  upload it can name has expired.
- **Public decks no longer reveal their owner.** `GET /decks/public` and the other deck lists
  no longer return `createdBy` (the owner's user id); nothing in the Web UI used it.
- **`GET /decks/{id}` returns `chatSessionId` to the owner only.** Viewers of a public deck get
  `null`.
- **`run_style_python` no longer returns the style's S3 key.** `saved` is now
  `{filename, name}`.
- **Composers see only their deck tools.** The Presentation Maker client each composer group
  gets now carries the composer's tool allowlist, as the orchestrator's already did.
- **Local Web UI refuses cross-site POSTs.** Every POST route of the local server (`sdpm webui`,
  `npm run dev:local`) now answers 403 when the browser's `Origin` is another site, so a page
  open in the same browser can no longer drive the local agent, upload files or change styles
  and templates through `127.0.0.1`. Requests without an `Origin` header (scripts, curl) are
  unaffected. (#473)

## [0.11.0] - 2026-10-31

### Added

- **HTML output mode.** A deck can be a browser presentation instead of a PPTX, locally and
  on the AWS stack. Ask for an HTML / browser deck, write `@format:html`, or use the
  **Build as HTML** pill (「HTML で作成」) on the first chat screen (also in the `/` picker's
  **Format** section; PPTX stays the default). The deck gets `deck.json`
  `outputFormat: "html"` (`init_deck_workspace(name, output_format="html")`, which also
  returns `format_notes`, the `html-deck` guide), and composers are dispatched with
  `start_composing(deck_id, assigned_slugs, mode="html")`, which returns the HTML composer
  document, the template's converted layouts and the deck's shared `deck.css`. HTML decks
  choose a template and style as PPTX decks do (`apply_style(deck_id, style, template)`);
  template decorations are converted to SVG when LibreOffice and poppler are installed.
  Each slide is an HTML fragment under `slides/`; `run_python` assembles them into one
  offline `output.html` on reveal.js 6 with speaker notes (`S` opens the speaker view), and
  every image is embedded. Slides may run inline scripts, with Apache ECharts 6.1.0 and D3
  7.9.0 embedded only in decks that declare them (`<section data-libs="echarts d3">`); all
  three libraries are vendored under `sdpm/vendor/` with their licenses and a checksum
  manifest checked in CI. `output.html` carries a Content-Security-Policy that allows only
  the engine's scripts and each slide's inline scripts by sha256 hash, plus `data:` images,
  fonts and media (`connect-src 'none'`, no-referrer), and every external link opens in a new
  tab. Static checks cover structure, layouts and placeholders, fonts, `deck.css`, embedded
  sizes, CSP-blocked constructs and scripts that reach outside the deck (`script-external`:
  navigation, new tabs, external URLs, WebRTC). After each build that changes slides, the
  browser check opens those slides in a browser (locally headless Chrome or Edge, in the
  cloud AWS AgentCore Browser) with network requests blocked and WebRTC disabled before slide
  code runs, reports layout findings (`overlap`, `overflow`, `outside-region`,
  `decoration-overlap`) and JS errors as warnings (`browser_check` in the result;
  `SDPM_BROWSER=none` turns it off), and leaves a PNG per slide (`preview_files` locally,
  `get_preview` in the cloud). A skipped, stopped or unfinished check is reported as such,
  never as clean. In the Web UI an HTML deck plays in a sandboxed in-app player with
  **Present** (new tab, link valid for 4 hours), **PDF** (print view, template backgrounds
  included) and **HTML** (download `output.html`); slides whose scripts reach outside the
  deck are listed in a warning next to Present / Download, on shared decks too. Thumbnails
  are static per-slide HTML in `sandbox=""` iframes; the local Web UI has one **Open**
  button. Sharing and public decks work as for PPTX; HTML files live under `html/` in the
  deck bucket and are served only through presigned URLs. The CLI gains `generate_html
  <deck>`. Translation, PPTX import, hand-edit sync, `code_to_slide` and the local
  `generate_pptx` refuse HTML decks with a message, and an invalid `deck.json`
  `outputFormat` stops every build. New dependency: `websockets`. The local Web UI dev
  servers (`npm run dev`, `npm run dev:local`) now listen on 127.0.0.1 only. PPTX behaviour
  is unchanged and the MCP tool count stays at 20. Deploy: SdpmData, SdpmRuntime,
  SdpmAgent, SdpmWebUi and the Web UI.
- **Claude Haiku 5.5** is a selectable model (`global.anthropic.claude-haiku-5-5`) for
  both Chat and Create. It uses the extended-thinking profile (no `temperature`; Bedrock
  rejects 0.1 with "temperature is deprecated"), with prompt caching enabled, and is
  listed in the example config's Recommended group. Unlike Haiku 4.5 it is not
  excluded from the Create picker.

### Changed

- **AgentCore runtime role.** The MCP runtime role gains
  `bedrock-agentcore:StartBrowserSession`, `StopBrowserSession` and
  `ConnectBrowserAutomationStream` on `arn:aws:bedrock-agentcore:<region>:aws:browser/aws.browser.v1`
  only.

### Removed

- **Python 3.10 is no longer supported (breaking).** `requires-python` is now `>=3.11`
  for `sdpm`, `servers/local`, `servers/remote` and the repository root, and the Claude
  Desktop bundle (`scripts/mcpb/manifest.json`) requires `>=3.11`. Python 3.10 reached
  end of life in October 2026, and Pillow 13 (which fixes the open Pillow advisories) no
  longer supports it, so 3.10 installs were stuck on a vulnerable Pillow 12.3.0.
  **Migration:** usually nothing to do. Every entry point runs through `uv`, which
  downloads a matching Python when the one on the machine is too old. Only setups that
  disable uv's Python downloads (`UV_PYTHON_DOWNLOADS=never`, offline machines) need a
  Python 3.11+ on the machine.

### Security

- Pillow 12.3.0 → 13.0.0 and pypdf 6.19.0 → 6.21.4 in every lock and in the
  `servers/remote` image constraints (Dependabot critical / high advisories).

## [0.10.4] - 2026-10-02

### Fixed

- **Web UI previews no longer go stale when a slide is edited without being measured.**
  `run_python` used to regenerate the live-preview data (`compose/`) and preview images only
  for the `measure_slides` slugs, so a slide written in the same call but not listed — or a
  slide the layout pass wrote but did not sample — kept its old (or no) preview. Rendering now
  follows the change: every slide the written files can alter (the slide itself, slides
  referencing a changed `includes/` file, `override` children, or every slide when `deck.json`
  / `specs/outline.md` changed) is re-rendered, plus the `measure_slides` slugs. Measurement
  (overflow, layout bias, invalid layouts) still covers only `measure_slides`. Applies to both
  the local and the AWS server. A layout pass now renders every slide it writes, so that call
  takes longer.

## [0.10.3] - 2026-09-30

### Added

- **GPT-6.1 Sol** is a selectable model (`global.openai.gpt-6.1-sol`) and replaces
  GPT-6 Sol in the example config's Recommended group. It uses the same profile as the
  other GPT models (no `temperature`, no Bedrock `cachePoint` — both are rejected on
  Converse; model-native implicit prompt caching still applies).

### Fixed

- **Local Web UI: "Continue from a kiro session" picker loads in well under a second.**
  It used to read every session log under `~/.kiro/sessions/cli` in full on each open
  (measured ~100 s on a 3.7 GB store); the list is now built from session metadata, and
  a log is read only up to its first prompt when a session has no stored title. The
  per-session message count is no longer shown. The "Show all" list also scrolls now
  instead of being clipped.

## [0.10.2] - 2026-09-29

### Added

- **Claude Sonnet 5.5** is a selectable model (`global.anthropic.claude-sonnet-5-5`) and
  replaces Sonnet 5 in the example config's Recommended group. It uses the
  extended-thinking profile (no `temperature`; Bedrock rejects 0.1 with "temperature is
  deprecated"), with prompt caching enabled.

## [0.10.1] - 2026-09-28

### Fixed

- **Continuing a kiro-cli session no longer starts without the sdpm tools (Web UI
  Local mode)** — after forking a session the Web UI switches the agent with
  `session/set_mode`, which replies before the orchestrator's `sdpm` MCP server is up.
  The continuation greeting could then run without `start_presentation` and fall back
  to reading role documents from the checkout. The fork now waits for
  `_kiro.dev/mcp/server_initialized` (`sdpm`) before the first prompt, up to the
  server's 120 s timeout.

## [0.10.0] - 2026-09-28

### Added

- **MCP prompts `sdpm-vibe`, `sdpm-spec`, `sdpm-style`, `sdpm-translate`** — user-invoked entry
  points every MCP client can surface (Claude Desktop's "+" menu, Claude Code
  `/mcp__sdpm__sdpm-vibe`, VS Code `/mcp.sdpm.sdpm-vibe`, Kiro CLI `/sdpm-vibe`). `sdpm-vibe` and
  `sdpm-spec` carry the `Interaction mode: fast` / `dialogue` token the orchestrator
  already understands, so the Web UI's Spec / Vibe choice is available from any
  client; each prompt is one line naming the role's entry tool — the role text
  itself is still fetched, never copied. Defined once in `sdpm.tools.prompts`,
  bound by the local, ACP and remote servers.

- **Role entry tools — `start_presentation`, `start_composing`, `start_style`,
  `start_translation`.** Each returns the role document *and* what that role
  always reads first, in one call: the orchestrator gets the style and template
  catalogues and the output directory; a composer gets the slide JSON spec, the
  deck's `brief` / `outline` / `art_direction`, `deck.json`, the template's
  layout analysis, which slides exist, and the JSON of its assigned slides (plus
  any override-group head they inherit from, marked read-only) — after the specs
  have been validated, so a composer never starts from broken specs; the style
  role gets the catalogue and one bundled style's HTML to imitate; translate gets
  the source deck's shape and the sibling path. The payload is split into a
  deck-independent `static` part (cacheable) and a per-call part. Register the
  MCP server and ask for slides: with no skills, no agent definition and server
  instructions disabled, the first tool the model calls is `start_presentation`
  in 9/9 trials on Kiro CLI and 9/9 on Claude Code (previously 7/9
  `read_workflows`, 1/9 straight to `init_presentation`, 1/9 no tool at all).
  The CLI has a matching `start <role>` subcommand.
- **`apply_style` returns `style_toc`** — a line-numbered map of the style file
  (one entry per `<style>` block and per `.slide`: line, classes, preceding
  comments, first visible text) so the orchestrator reads the rules and outline
  guidance it needs with one `run_python` `read_text` + line slice. Structural
  only: no dependence on the Part convention a user-authored style may skip.
- `SDPM_DISABLE_INSTRUCTIONS=1` serves no MCP server instructions — nothing
  depends on them any more; the entry tools' own descriptions carry the routing.

- **One installer, one launcher.** `install.sh` / `install.ps1` install SDPM into
  `~/.sdpm` once — dependencies, checkout, MCP server environment, icon catalogs — and
  create the `sdpm` launcher. The installer asks two questions: whether to add the browser
  Web UI (`--full` / `--mcp-only`; MCP-only needs no Node.js) and which detected MCP
  clients to connect — a checklist of the detected clients, ending in a ✓ / – / ✗ result table
  (`--register` / `--no-register`). `sdpm webui` starts the Web UI,
  `sdpm mcp` runs the server on stdio, `sdpm register` / `unregister` / `mcp-config`
  connect clients through their own CLIs — Claude Code, VS Code, Codex — or open Cursor's
  deep link built with the real paths; other clients get the JSON and the file it belongs
  in. Kiro CLI gets a dedicated `sdpm` agent (`~/.kiro/agents/sdpm.json`: the MCP server,
  trusted `@sdpm` / `use_subagent`, sub-agents restricted to itself, no prompt text) instead
  of an entry in the global `mcp.json` — nothing is added to other sessions, and composers
  need no approval per `run_python`. `sdpm register kiro-cli` also detects the old
  installer's `sdpm-composer` agent, skill links and global `mcp.json` entry and offers to
  remove them; a user-authored agent of the same name is left alone. `sdpm` alone shows status; `sdpm update
  [--with-webui]` upgrades both surfaces; `sdpm uninstall` removes everything. Client
  detection, configuration and registration live once in
  `servers/local/client_config.py`; both launchers delegate to it. Every client
  configuration points at the absolute `uv` and checkout paths (GUI apps do not inherit
  `PATH`). Same command set on macOS, Linux and Windows (Windows verified in CI only).
- **Previews report what is missing, once, where it matters.** When LibreOffice or
  poppler is absent, the build result carries `preview: {"status": "unavailable",
  "missing": [...], "install": "<one command for this OS>"}` and the deck still builds;
  nothing else nags. Icon catalogs missing for any reason are fetched in the background on
  the server's first start (`SDPM_AUTO_INSTALL_ASSETS=0` opts out), and `search_assets`
  reports a missing or in-progress catalog instead of exiting the process.

- **Bundled styles re-organised into two tiers** — an *orthodox* tier for when
  looks do not matter (`report`, `briefing`, `aws-light`, `aws-dark`) and a
  *concept* tier chosen by look (added in phases, listed below). The previous
  purpose-based lineup (`consulting`, `keynote`, `facilitation`, `engineering`,
  `lecture`) is removed: purpose belongs to the outline, not the style, and
  those five differed from each other only by accent hue. Each style is a
  rulebook, reference and gallery sample in one file: a design decision with
  DO / DON'T rules derived from it, a Message & Outline part (per-slide
  density, title grammar, chapter shape), palette and type ramp with
  usage rules, the repeated frame, and 8–12 annotated pattern slides showing how
  *that* style builds numbers, comparisons, processes, tables, charts and more.
  All styles define `--color-text` (read by `apply_style`) and `--fs-*` sizes (read
  by the build-time font-size lint). Lineup and intent: `docs/en/custom-template.md`.
  - `report` — white, serif findings, one deep-green accent, tables and small
    multiples, greyscale-safe.
  - `briefing` — dark technical-briefing style (noun-phrase titles with a
    topic sentence, header bands and rules instead of cards, one teal accent).
  - `aws-dark` / `aws-light` — Squid Ink or white ground, the official
    service-category colours as `--cat-*` tokens with per-background tints,
    official icons, one Smile Orange emphasis per slide; the two files differ
    only in `:root` and the palette specimens.
  - Concept tier, chosen by look. Each states numeric limits for how far the
    look may be pushed (border and shadow sizes, colours per slide, words per
    title, rotation) so composers cannot drift: `neo-brutalist` (cream, 6px
    black borders, hard 12px shadows, flat primary fills), `typographic`
    (white, 384px display type bleeding off the left edge, black-and-grey
    focus stacks, one red word, no shapes at all),
    `signal` (near-black, one safety-yellow panel, upright ultra-bold
    headlines, hazard stripe), `racing` (near-black, italic condensed
    headlines, blue-violet-red stripe, speed lines), `bento` (soft grey, white
    rounded tiles on a fixed grid, one dark and at most one accent tile),
    `newspaper` (aged paper, serif headlines, hairlines, 2–3 justified
    columns, drop cap, one red), `swiss-poster` (white, one red geometric
    shape that may bleed, grid lines, vertical label), `duotone` (near-black
    and orange split by one hard edge, orange type as the accent on the dark
    field, shape bar charts with one white bar).
  - `prism-dark` / `prism-light` — the first bundled styles whose identity is a
    gradient. The rule is a role, not a quota: one violet-to-pink gradient is a
    *pointer* that marks the thing the slide title is talking about (gradient
    text on the key figure, a 4px outline plus one filled pill on the chosen
    card, or one gradient bar); everything else is flat, and a 40px gradient bar
    down the left edge is the only constant. Crisp edges only — no blur, glow,
    radial ramps or gradient panels. Note: LibreOffice previews render
    `textGradient` / `lineGradient` as the first stop colour (solid violet);
    PowerPoint and Keynote render the gradient. Shape fills preview correctly.
  - `aws-console` — the deck looks like the AWS Management Console. Two dark
    header bands (wordmark, a search box that shows the deck title and slide
    index, a notification badge counting open actions, date and presenter in the
    region / account positions, a favourites row of numbered section chips, the current one lit) over a
    white toolbar; a page title with an Info link and an outline + orange button
    pair; white 2px-bordered containers with drag handle, Info link, kebab and
    resize handle; blue links and blue metrics; three fixed status colours;
    dense 56px rows instead of prose. Orange appears only as the one action
    button. Final concept-tier lineup is eleven styles (the planned `memphis`,
    `chalkboard`, `art-deco` and `zine` were dropped).
- **Style contract test** (`tests/test_builtin_styles_contract.py`) and a
  style-verification sample deck (`tests/fixtures/style-sample-deck/`).
- **Styles now set the deck ground.** `apply_style` copies the style's
  `--color-bg` into `deck.json` as `defaultBackground`, and the builder fills
  every slide that has no `background` of its own with it (table auto-colours
  and the icon theme follow). Until now only `--color-text` was applied, so a
  cream or near-black style rendered on the template's white or navy unless
  each slide set `background` by hand.
- **Bulk delete in the deck list** — hover a card in My Decks and tick its
  checkbox (or press "Select" in the header) to enter selection mode; click
  toggles, shift-click selects a range, ⌘/Ctrl+A selects everything shown,
  Escape leaves. A floating bar shows the count with Select all / Delete /
  Cancel; one confirmation deletes the whole selection (five requests in
  flight at a time, progress in the bar, failures reported and left in the
  list). Owner tab only; the local build shows the checkbox permanently on
  touch-sized screens.
- **Claude Opus 5.5, GPT-6 Sol and GPT-6 Luna** are selectable models
  (`global.anthropic.claude-opus-5-5`, `global.openai.gpt-6-sol`,
  `global.openai.gpt-6-luna`). Opus 5.5 uses the extended-thinking profile
  (no `temperature`, prompt cache on); Sol and Luna use the same Converse
  profile as Astra (no `temperature`, no Bedrock `cachePoint` — implicit
  caching only). All three are compose-capable. Add the IDs to
  `model.allowedModelIds` in `infra/config.yaml` and redeploy to enable them.
- **Recommended / Other models grouping in the model picker** — operators can
  list a few models under `model.recommendedModelIds` in `infra/config.yaml`;
  the Settings Chat / Create pickers then show them first under a "Recommended"
  heading and the remaining allowed models under "Other models" (order within
  each group follows `allowedModelIds`). Without the key the list stays flat.
  Both defaults must be in the recommended list — `cdk synth` fails otherwise.
  The badge on the default model now reads "Default" instead of "Recommended".
- **`/` picker for template and style in the chat input** — typing `/` at the
  start of a line or after whitespace opens an inline popup to pick a
  template or style without leaving the compose flow; Enter/Tab/click inserts
  an `@template:<name>` or `@style:<name>` token (quoted when the name has
  spaces) at the cursor. The existing Art Direction pane pickers (template
  cards, style cards) now insert the same tokens instead of a fixed English
  sentence. Sent messages highlight the tokens like existing `@Page N`
  mentions. The orchestrator treats these tokens as explicit choices — it
  uses them as given, in fast mode too, and asks rather than substituting if
  the named template or style does not exist.

- **Continue a deck from a kiro-cli session (Web UI Local mode)** — any chat
  you had in `kiro-cli` on the machine can be the starting point of a deck.
  The empty chat offers the last 24 hours of sessions as cards; the **+** menu
  opens the full picker grouped by project (subagent children and SDPM's own
  sessions are hidden by default). Picking one forks the session into a new ID
  — the files under `~/.kiro/sessions/cli/` are never written — loads it over
  ACP `session/load`, switches the agent to `sdpm-orchestrator` with
  `session/set_mode`, and the agent replies at once with what the work was
  about plus one question (audience and talk length). A chip above the chat
  shows the source session. The orchestrator workflow gained a `Continued
  from:` paragraph defining that first reply.

### Removed

- **The plugin layer, skills and the Kiro installer.** `plugin.json` + `mcp.json` (Agent
  Plugins / Kiro Power), `.claude-plugin/`, `.codex-plugin/` + `.mcp.json`, `skills/`, the
  `sdpm-composer` Claude Code agent, `clients/kiro/install.py` and `make install-kiro`.
  Since the `start_*` entry tools (#394) and the `sdpm-*` prompts (#395) nothing has to be
  placed on the agent side; these only wrapped one MCP server line in vendor manifests
  and carried three extra copies of the version. The `uvx --from git+https://…` path and
  its generated snippets are removed with them: PyPI is unavailable to this repository,
  the git URL followed `main` yet was frozen by uv's cache, and it gave a user who also
  installed the Web UI a second copy of the server. Migration: run the installer once and
  see `docs/en/migration-onboarding.md`. The Claude Desktop `.mcpb` bundle stays
  (now built from `scripts/mcpb/`).

### Fixed

- `code_block` rendered code one character per line: the element margins were written
  as EMU (`50000` / `30000`) but the builder reads them as px, so the text area collapsed.
  Margins are now px (8 / 5), the code body uses a monospace font on every surface, and
  the remote server's `code_block` shares `sdpm.api.code_block` instead of a second
  element builder. (Reported in
  [a fork-update writeup](https://qiita.com/yama3133/items/1b1dc9c26f47ab726ec5).)

- `grid` accepts `rows` / `columns` given as an int (`"rows": 1`) or a token list;
  the int form crashed the tool in a real composer run.

- **A typed element carrying `_comment` is built, not dropped.** The builder,
  diff and lint treated *any* element with a `_comment` key as a comment-only
  entry and skipped it, although `slide-json-spec` says the key may be used
  inside elements as an ignored annotation. A layout pass that annotated its
  frame elements (`{"type": "textbox", "_comment": "frame: slide title", …}`)
  therefore shipped a deck with no titles, edge bars or rules — and nothing
  warned. Only entries without a `type` (section markers, `region:` layout
  regions) are comment-only now (`sdpm.engine.schema.is_comment_element`).
- **`list_styles` no longer makes hidden styles look non-existent.** With pins
  set, the default listing drops every style that is neither pinned nor
  user-created, and the orchestrator is told not to substitute a style it cannot
  find — so asking for an unpinned bundled style was answered with "that style
  does not exist". The payload now carries `other_styles` (the hidden names) and
  a `hint` whenever the pin filter dropped something, so the agent can use the
  name directly with `apply_style` (which never depended on pins) or fetch
  descriptions with `include_all=True`. Both keys are absent when nothing was
  hidden. Local and remote servers share the new `build_styles_listing()`.
- **Shapes and connectors no longer inherit the template theme's shadow.**
  python-pptx gives every autoshape a default `<p:style effectRef>` that
  resolves to the theme's effect style — an outer shadow in the Office default
  theme and in the bundled blank templates — so any filled shape or line built
  from JSON without a `shadow` key grew a shadow nobody asked for. The builder
  now always writes an explicit effect list (empty when no effect is requested),
  and `"shadow": "none"` (also glow / softEdge / reflection / bevel) is an
  explicit off instead of falling back to the `md` preset. Decks that relied on
  the accidental theme shadow will render flat; set `"shadow": "sm"` where a
  shadow is wanted.
- **Local ACP prompt errors no longer hang the stream** — an RPC error from
  `session/prompt` now surfaces on the SSE stream as an error event instead of
  an unhandled rejection with the chat stuck in "thinking".
- **Local MCP server starts on native Windows** (#385). The attachment stage
  cache imported the POSIX-only `fcntl` module at load time and fsynced
  directories by opening them, both of which fail on Windows. The cache and the
  import bundle committer now share one lock-free `publish_directory`
  primitive (`sdpm.tools.attachment.atomic`): stage in a writer-unique
  directory, fsync, then a single rename; if another writer lands first, verify
  and reuse its result. This also drops a lock file whose unlink-on-release
  could let two writers hold the lock at once, and aligns the cache's fsync
  coverage with the bundle committer's. Directory fsync is skipped on Windows.

### Changed

- **A style is now a short deck about itself, built in itself.** The bundled styles drop their
  specimen parts — palette and type-ramp sheets, the finished-pattern Part 7, per-slide frame
  copies — and become Cover → Rules → Message & Outline → Patterns → Closing, every slide a real
  slide of the style at the style's **own density** (a `<!-- Density: N -->` marker the
  contract test enforces on every slide). What the gallery shows is what a deck in that style
  looks like, and composers no longer copy cramped reference slides. Palette and size usage
  live in comments beside the `:root` tokens; frames, components and patterns are commented
  where they first appear. Components are named by **role** from one vocabulary in the style
  workflow (`container`, `selected`, `takeaway`, `numbered`, `metric`, `step`, `connector`,
  `tag`, `table`, `chart`, `icon` required; `phase`, `hub`, `axis`, … optional); each pattern slide
  (`comparison`, `columns`, `process`, `metric`, `table`, `chart`, `diagram` required) is built as the
  pattern it explains and names its regions for the layout pass. Non-rectangular parts use
  `.shape-<json shape name>` classes drawn with `clip-path`. The 15 files total 594k characters
  instead of 829k. Tokens and `<title>` descriptions are unchanged, so decks already built and
  user styles in the old skeleton keep working.

- **Slides draw their structure instead of writing it.** Decks built since the component
  vocabulary was dropped carried no icons and almost no diagrams. The slide JSON spec gains
  **Visual forms** — when to draw, how to use icons (`search_assets`, label, size, colour), and
  build recipes for flow, cycle, hub, hierarchy, matrix, spectrum, timeline, stack, funnel,
  brace, progress, isotype, before-after and icon + label rows. The outline names the form a
  slide's content calls for; the composer treats a style's patterns as how it draws, not as the
  limit of what a slide may show. Every bundled style defines its `icon` treatment, states how
  much it illustrates, and carries a `diagram` pattern; icons are inline SVG symbols named after
  their `search_assets` asset, so the gallery shows them too.

- **Styles carry no stock decoration.** The decoration roles (orb, ring, glow, gradient
  field, watermark, accent bar, hero graphic, icon frame) are gone from the style workflow,
  the slide JSON spec and all 15 bundled styles; a named list of ornament became a menu every
  style picked from. Decoration is now defined like any other component, and its comment says
  what it does in that style's decision (Signal's hazard rail, Racing's cover speed lines).
  The restored component catalog guide (`components.md`) is removed again: A/B decks with and
  without it were equally rich, and the guide cost every composer ~40k characters.

- **`start_presentation` / `start_style` return every style, `pinned` flagged.**
  The pin filter is a gallery concern; the role picking a style sees the whole
  catalogue with the user's favourites marked. `list_styles` keeps its
  pinned-by-default behaviour.
- **Bundled styles no longer prescribe a slide count.** 13 of 15 stated a range
  (often with a "20-minute talk" assumption). Length follows the brief and the
  material; a style states per-slide density and chapter shape. The ranges are
  rephrased as density statements in each style's voice; the style workflow's
  Part 3 contract and the orchestrator say the same.
- **`init_presentation` → `init_deck_workspace`.** The old name read like the
  place to start and competed with the entry tool; the tool only creates
  `deck.json`, `slides/` and `specs/`. Same signature and result.
- **`slide-json-spec` is a guide** (`read_guides(["slide-json-spec"])`) — it
  arrives with `start_composing` / `start_translation`, so re-reading it is the
  only remaining direct use.
- **Role documents no longer ask for what the entry tool already returned**
  (no `list_styles()` / `list_templates()` step; the composer reads its inputs
  from the `start_composing` payload rather than from files). The orchestrator's
  composer spawn prompt is `start_composing(deck_id, assigned_slugs)` and works
  with any sub-agent that has the sdpm tools — a dedicated composer agent or a
  skill is no longer required, and the `sdpm-*` skills are now one-line calls to
  the entry tools.
- **Tool descriptions say when to call a tool; what each argument means is on the
  argument (schema property description); formats, examples and internal structures
  live in guides.** `grid`, `arch_diagram` and `diff_pptx` point at their guides
  instead of inlining the spec; a new `attachments` guide takes what
  `read_attachment` / `import_attachment` carried. The local server's tool
  surface (description + schema, sent to the model on every turn) shrinks from
  18.4K to 13.6K characters. With the rewritten descriptions the first tool the
  model calls, MCP only, was the matching entry tool in 30/30 trials on each of
  Kiro CLI and Claude Code (create / edit / outline / translate / style prompts).
- **Cloud agent (L4)** loads roles through the same entry tools: the role
  document goes to the system prompt (`Source.mcp(..., pick="static.workflow")`),
  the composer's slide spec joins the cached system prefix, and each composer
  opens with a replayed `start_composing` call instead of the agent hand-rolling
  a `run_python` prefetch of the specs. `compose_slides` lost its
  `_prefetch_deck_specs` and template pre-analysis.
- **The `style` workflow now defines what a style is** — the Part 0–7 skeleton,
  the `:root` token contract, HTML constraints and writing principles (state the
  design decision, derive the rules; describe by design, not by brand). Demo type
  is rendered at true slide scale (`calc(var(--fs-*) * 1.5)`: the 1920 px canvas is
  960 slide-pt, CSS draws 1pt as 1.333 px), so box heights copied from a style no
  longer overflow when built.
- **Orchestrator writes the style before the outline** (brief → style → outline):
  a style's Message & Outline part fixes deck length, density, title grammar and
  chapter shape, so an outline written first had to be rewritten.
- **Onboarding now starts with two equal entry points** — the README and Getting Started
  ask whether to use the full browser experience or the AI agent already installed, then
  provide a one-action path. Layer terminology moved out of setup instructions and remains
  in the architecture reference. The Web UI Local mode is no longer labeled experimental.
- **`sdpm-skill` now builds with hatchling** — source distributions and wheels include the
  runtime knowledge, templates, and shared support code required by checkout-free `uvx`
  execution.
- **Off-screen slides are always drawn in their final state** — the
  agent-cursor animation now plays only for a live update on the slide you are
  looking at. A change that lands on a slide out of view is drawn immediately
  and completely, with nothing held back and no replay when you scroll to it.
  This walks back the "kept undrawn and replayed within 60 s" behaviour
  introduced with the large-deck animation work below: on review it meant
  waiting through a re-enactment on every slide, two at a time, and whether a
  slide replayed or simply appeared depended on how fast you scrolled. The
  load-reducing parts (two concurrent animations, one typewriter frame loop,
  hoisted defs, `content-visibility: auto`, follow-scroll) are unchanged.
- **Slide list moves instead of jumping** — slides that appear, disappear or
  move in the Slides tab slide into place (both grid and full view); a
  regenerated preview crossfades over the old image instead of flashing a
  skeleton, and its glow starts when the new image is actually on screen.
  Clicking a thumbnail in grid view opens the full view at that slide (the card
  grows into place). Reveal stagger is capped so the last slide of a long deck
  no longer waits. All motion honours the OS reduced-motion setting.
- **Chat input height is always right** — the message box now grows with its
  content via `react-textarea-autosize` (1–5 rows) instead of a hand-rolled
  height calculation that could misjudge IME composition and pasted text.
- **Compose animation is cheap again on large decks** — only slides in view
  are drawn by the agent cursors (at most two at a time); changes that land on
  a slide you are not looking at are kept undrawn and replayed with the same
  cursor animation when you reach it (within 60 s; older changes just appear).
  One shared frame loop drives every typewriter, defs are mounted once per
  deck, off-screen slides skip layout and paint, and the per-slide polling is
  gone. Main-thread work during a compose burst drops by about half and a
  finished deck scrolls at full frame rate. The full view now follows the
  slide being composed until you scroll yourself.

### Removed

- **`list_guides`.** `read_guides`' description lists the guide catalogue.
- **`diff_pptx` as an MCP tool.** Hand-edit sync stays a CLI operation
  (`pptx_builder.py diff_pptx`), as the `hand-edit-sync` guide now says; it was
  never bound on the remote server and was marked for removal.
- **`read_workflows` / `list_workflows`.** Role documents are delivered by the
  `start_*` entry tools (and the CLI `start` subcommand); the spec is a guide.
  A client that still calls `read_workflows(["orchestrator"])` should call
  `start_presentation()` instead.
- **`sdpm/references/examples/components.pptx` — the "component vocabulary"
  (`read_examples(["components/all"])`, ~40 KB of text read by every
  composer).** An A/B run on the same material with two bundled styles
  (`prism-dark`, `report`) showed no quality difference without it: the
  composer never used the catalog's shape vocabulary (chevron, brace,
  progress ring …) even when given it — the style HTML decides the design —
  while session text shrank 12–28 % and turns 13–41 %. The three engine facts
  that lived only in the catalog moved into `slide-json-spec`
  (`marginTop: 0` for exact alignment, base orientation of `triangle` /
  `arrow_right` under `rotation`, lines carry no `text`). Same reasoning as
  the `patterns.pptx` removal in 0.9.0.
- **The `read_examples` tool and CLI subcommand.** With the component
  vocabulary gone it only served `styles/<name>`, which no workflow calls —
  styles are reached through `list_styles` / `apply_style`. The CLI gains a
  `list_styles` subcommand (`--all`, `--no-browse`) so the L1 path keeps the
  style listing and browser gallery under the contract name.
- **Bundled styles `border`, `corporate-executive`, `cute-playful`,
  `elegant-dark`, `elegant-light`, `flat-shadow`, `lumina`, `tech-cyber`.** They
  were early swatch-and-type-ramp demos with no composition rules and used
  `--size-*` tokens the lint does not read. No migration path: pick one of the six
  new styles (or copy an old file from git history into `~/.config/sdpm/styles/`
  to keep using it). Decks already built keep their `specs/art-direction.html`.
  Pinned names in `state.json` that no longer exist are ignored; re-pin.
- **"Parallel agents" toggle in the chat Options** — it did not do what it
  said. On the cloud stack it switched to a `single` agent mode that dropped
  `compose_slides` entirely (the orchestrator wrote every slide itself, slowly
  and without the compose board); in local mode it reached nothing at all. It
  also hid the Spec / Vibe selector when off. Composers always run now. The
  `single` and `separated` wire values are gone — the agent accepts `spec`,
  `vibe`, `composer`, `style_creator`; a payload without `mode` defaults to
  `spec` (was `single`).

## [0.9.0] - 2026-09-22

### Added

- **Outline view as a slide storyboard** — the Web UI's outline tab shows
  each slide as a 16:9 card: the claim as headline, the body in full, visual
  and evidence small at the bottom; chapters (`##`) divide the deck. Grid by
  default with a persisted column alternative. Text never drops below the
  11px floor.
- **Edit the outline in the storyboard and send the changes** — every card
  field, chapter heading and the deck name are editable in place; add
  (ghost card), duplicate, delete with undo, reorder by drag (across
  chapters, keyboard too) or ⌥↑/↓, ⌘Z/⇧⌘Z history, a markdown drawer with
  changed lines highlighted. "Send changes" (⌘S) writes `specs/outline.md`
  and posts a user message to the chat carrying the unified diff (with a
  note that new `slide-N` slugs are placeholders, and — toggle, on by
  default — a request to polish the wording), so the agent picks the edit
  up in the same conversation. No agent-side changes: the file is written
  unconditionally and the diff is how the agent learns what happened. New
  API `PUT /decks/{id}/specs/outline` (cloud) and matching local route.
  Web UI now depends on `@dnd-kit/react`, `motion` and
  `react-textarea-autosize`.
- **`sdpm-composer` skill entry point** — a fourth thin dispatcher
  (`skills/sdpm-composer`) for the role a spawned composer sub-agent plays;
  it calls `read_workflows(["composer"])` and stops. Dedicated composer
  agent definitions (Kiro, Claude Code) now point at this skill instead of
  a `personas/composer.md` file reference.
- **`docs/en/migration-role-workflows.md`** — breaking-change table and per-environment
  migration steps for the workflow consolidation below.

### Changed

- **Compose is two passes: layout, then content** — the scaffold pass becomes the
  **layout pass** (`task_instruction: "Layout pass."`): one composer sees every slide and
  decides each slide's template layout, frame elements and named content regions
  (`_comment` elements with x/y/w/h, invisible in output), derived from one grid, written
  in one batched `run_python` call. Content composers realize their slides inside those
  regions. The consistency-review and fixes passes are gone: layout consistency is now
  by construction, and the orchestrator looks at previews and re-dispatches a composer
  per slide that needs a change.
- **`run_python` requires `deck_id`** — the sandbox always runs inside a deck
  workspace. The workspace-less "calculation" mode is gone: on the cloud it accepted
  file writes and discarded them silently (a composer lost a whole scaffold pass this
  way), on the local server it could not write at all. Create the deck with
  `init_presentation` first, then compute. Also new: `check_specs` validates
  deck.json and outline.md before composing (`compose_slides` runs it first).
- **Web UI Spec / Vibe and "Parallel agents" keep their behaviour without personas** —
  the orchestrator workflow defines two tokens, `Interaction mode: dialogue` (the user
  wants to shape the deck in conversation) and `Interaction mode: fast` (build from material);
  the cloud agent passes the token as a one-line system part and the local ACP route
  prepends it to a session's first prompt. `single` (parallel agents off) is the same
  workflow with no composer sub-agents, composing slides itself.
- **Outline sub-items are now `body` / `visual` / `evidence`** — these three keys replace
  `what_to_say` / `what_to_show` / `evidence` / `notes`. This is breaking for existing
  enriched outlines: old-key lines are shown as prose rather than parsed as slide sub-items.
- **Mode behavior consolidated into role documents, served via
  `read_workflows`** — `start_presentation(mode=...)` and `personas/*.md`
  are removed. Each role (orchestrator, composer, style, translate) now has
  exactly one document, `sdpm/references/workflows/<role>.md`, containing
  both the role definition and its procedure; entry points (skills, agent
  definitions, `SKILL.md`, server instructions) only ever name a role for
  `read_workflows` to fetch, never restate its behavior. This removes the
  persona/workflow duplication that v0.5's persona layer had reintroduced.
- **`vibe` and `spec` modes merged into a single `sdpm-create` skill** —
  the dialogue-depth distinction is gone; how much back-and-forth happens
  is driven by the user's own wording, not a mode argument. `skills/sdpm-vibe`
  and `skills/sdpm-spec` are replaced by `skills/sdpm-create`.
  `skills/sdpm-style` and `skills/sdpm-translate` are unchanged in purpose,
  now dispatching to `read_workflows(["style"])` / `read_workflows(["translate"])`.
- **CLI subcommands renamed to match MCP tool (contract) names** — e.g.
  `generate` → `generate_pptx`, `examples` → `read_examples`,
  `workflows` → `read_workflows`, `guides` → `read_guides`,
  `analyze-template` → `analyze_template`, `search-assets` → `search_assets`,
  `list-templates` → `list_templates`, `init` → `init_presentation`,
  `code-block` → `code_to_slide`, `layout` → `arch_diagram`,
  `diff` → `diff_pptx`. Workflow/guide text now reads identically whether
  called as an MCP tool or a CLI subcommand. No aliases for the old names.
  See [Migration: role workflows](docs/en/migration/role-workflows.md) for the full table.
- **`slide-json-spec` moved to `sdpm/references/spec/`** — it is a fact
  document, not a role document; still resolved by `read_workflows` for
  backward compatibility. **`hand-edit-sync` moved to
  `sdpm/references/guides/`** — it is an occasional-need procedure, not a
  role.

### Removed

- **`sdpm/references/examples/patterns.pptx` and the `search-patterns`
  CLI/tool** — an audit of all 18 cataloged patterns found their techniques
  either duplicated in `components/all` or not measurably improving output
  versus letting the model reason from the style HTML and component
  vocabulary directly. No migration path; if a specific technique is
  needed again, express it directly in slide JSON per
  `read_workflows(["slide-json-spec"])`.

> **Migrating from v0.5?** See [Migration: role workflows](docs/en/migration/role-workflows.md)
> for the full breaking-change list and upgrade steps per environment.

## [0.8.2] - 2026-09-21

### Fixed

- **WebP previews and deck thumbnails were not generated after v0.8.1.**
  `schedule_webp_background` relied on an asyncio event loop; tools now run on
  worker threads, so the task silently never started and `generate_pptx`
  produced no slide previews and no thumbnail. It runs on a daemon thread now.
- **`get_preview` right after `run_python` could see a missing or stale image.**
  v0.8.1 moved preview generation into a background task; `get_preview` now
  waits for that task (per deck, up to 90s), and the task renders the
  measured slugs' WebP before the live-preview JSON.
- **Code Interpreter session start could stall for minutes on AgentCore V2.**
  Every AWS client now uses a 5s connect timeout. Prompt APIs (S3, DynamoDB,
  SSM, session start/stop, embeddings) get read 30s / 3 attempts; the user-code
  `invoke_code_interpreter` gets read 600s and a single attempt so a stall can
  never execute the code twice.

## [0.8.1] - 2026-09-20

### Fixed

- **Remote MCP server no longer stalls or dies during long tool calls.**
  FastMCP ran synchronous tools on the event loop, so a minute in
  LibreOffice blocked AgentCore's `/ping` and the session was terminated
  mid-run. Every remote tool now runs in a worker thread (`offloaded_tool`);
  the WebP background task does too.
- **AgentCore Runtime platform V2: first S3 call after restore no longer
  hangs.** boto3 clients built at import carried connection state into the
  V2 snapshot; the first call on a restored microVM could block for minutes
  (observed: `list_templates` unanswered after 9 min). Clients are now built
  on first use, with bounded botocore timeouts (connect 5s / read 30s /
  3 attempts / TCP keepalive).
- **AgentCore Runtime platform V2: LibreOffice's first run per microVM
  (~60s) is warmed in the background.** The restored root filesystem is
  lazily fetched, so the first `soffice` run paid ~60s of first-touch disk
  reads (3s thereafter). The server now converts a blank template in the
  background when an MCP session starts, before the composer reaches its
  first `run_python`. Measured: layout-pass `run_python` 85s → 14s.

### Changed

- **`run_python` returns as soon as measure is done.** The live-preview
  JSON (compose) and the measured slugs' WebP finish in a background thread;
  `previewHint` now says the images are being generated. Previews render
  only the measured pages, the LibreOffice SVG is parsed once, and per-slug
  compose runs in a thread pool. Phase timings (`prepare_s3`, `build`,
  `measure`, `artifact_s3`, background compose) are logged at INFO.

## [0.8.0] - 2026-09-20

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
- **GPT-6 Astra** (`global.openai.gpt-6-astra`) is selectable for chat and
  create. Throughput is roughly a third of GPT-5.6 Terra (~25 vs ~90 output
  tokens/s measured in `ap-northeast-1`), so expect longer waits on
  compose-heavy runs.
- **Kimi K3** (`global.moonshotai.kimi-k3`) is selectable for chat and create.
  Its Converse constraints are identical to the GPT models' — it rejects
  `temperature`, `topP` and Bedrock's `cachePoint`, while its own implicit
  prompt caching is on by default — so it reuses the same invocation profile
  and needed no new agent code. Throughput is competitive with GPT-5.6 Terra
  (~80–175 output tokens/s measured in `ap-northeast-1`). Note it always emits
  reasoning content, and those tokens count against the output budget: a
  one-word answer costs ~50 output tokens where Claude spends ~5, so short
  interactions are disproportionately expensive.

### Changed

- **MCP servers connect concurrently instead of one after another** — Strands
  connects them serially: `ToolRegistry.process_tools()` iterates the tools list
  and blocks on `await provider.load_tools()` for each ToolProvider in turn. With
  three servers — the Presentation Maker one on AgentCore plus two AWS servers
  pinned to `us-east-1` — that put their handshakes on the critical path back to
  back, and a profile attributed roughly 2.6s to the two AWS ones alone. They are
  now connected up front in a thread pool; `load_tools()` caches its result, so
  Strands' own call is a cache hit. Measured on the dev stack: agent setup went
  from 7.72s to **5.14s**. As a side effect the `required` flag in `MCP_DEFS` now
  does what it always claimed — it was only guarding client construction, which is
  lazy and cannot fail, so an unreachable optional server used to surface as a hard
  failure inside Strands (`MCPClient` defaults to `continue_on_error=False`).
  An optional server that cannot be reached is now dropped with a status entry.
- **`diff_pptx` is no longer offered on the cloud path** — `servers/remote` does not
  bind it, so listing it in the agent's tool allowlist produced a "not found on MCP
  server" warning on every request. The hand-edit sync workflow stays a local/CLI
  capability and the workflow document says so; the tool is slated for removal.

- **OpenAI GPT models are served through the Converse API** instead of
  `bedrock-mantle`. They are now registered under their global inference
  profile ids (`global.openai.gpt-5.6-terra`, `global.openai.gpt-6-astra`) and
  go through the same `BedrockModel` path as every other model. This removes
  `agent/mantle_client.py`, the `MANTLE_MODELS` / `MANTLE_RESPONSES_MODELS`
  tables and their region-resolution helper, the OpenAI SDK dependency
  (`strands-agents[openai]`), and the `bedrock-mantle:CreateInference` /
  `bedrock-mantle:CallWithBearerToken` IAM grants on the agent role.
  Prompt caching still applies: these models do not accept Bedrock's
  `cachePoint` block, but their own implicit prompt caching is on by default.

### Removed

- **GPT-5.5 and GPT-5.4** — not available as Bedrock foundation models, so they
  cannot be reached over the Converse API. They were only ever callable through
  the removed `bedrock-mantle` path.
- **Nova 2 Lite** — it was registered as `us.amazon.nova-2-lite-v1:0`, a
  US-only cross-region inference profile that does not exist in the deployment
  region, so selecting it always failed with `ValidationException: The provided
  model identifier is invalid`.

### Fixed

- **The Claude Code plugin manifest tracks the engine version again** —
  `.claude-plugin/plugin.json` sat at `0.3.0` while the engine reached `0.7.1`.
  `plugin.json` and `.codex-plugin/plugin.json` each had a test asserting they
  follow `sdpm.__version__`; this manifest had none, so the drift went unnoticed
  across several releases. It now carries the same guard.


- **The knowledge base id is resolved per request instead of at import** — the
  remote MCP server read `KB_SSM_PARAM` from SSM at module import and built its
  `KBSync` from the result. SSM exists so that value can change without a
  redeploy, so caching it at startup pinned the runtime to whatever the id was
  when the process began. It is now resolved on first use and refreshed every
  300s. This also matters on AgentCore Runtime `platformVersion` V2, which
  snapshots the process after initialization and shares that memory state with
  every restored instance: a value read at import is frozen for the life of the
  snapshot, where V1's periodic container recycling used to re-read it. Tool
  registration for `search_slides` now depends on configuration rather than on a
  successful read, so a transient SSM failure no longer removes the tool for the
  life of the process.
- **MCP requests no longer start a new microVM on every agent turn** — the agent
  connected to the Presentation Maker MCP server on AgentCore Runtime without
  sending `Mcp-Session-Id`. AgentCore routes MCP requests to a microVM by that
  header and mints a fresh session id for any request arriving without one, so
  each agent turn — plus each composer slide group, which builds its own client —
  paid a new-session start on a 630 MiB image. The caller's session id is now
  forwarded, and composer groups use `{session_id}-g{n}` so they keep the
  per-group isolation they were written for while still reusing their own microVM
  across composes. Measured in `ap-northeast-1`: 0.18-0.20s with a consistent id,
  0.59s without one when warm capacity happened to be available, and 17.6-19.7s
  without one when it was not. Replaying an id after the 900s idle timeout returns
  HTTP 200 and re-establishes the session, so no re-initialize path is needed
  (verified for the stateless MCP server this project runs).
- **Importing an attachment from a URL works again** — `fetch_url` sends
  `Connection: close`, which makes `http.client` set `response.will_close`, and
  `getresponse()` then hands the connection to the response by calling
  `HTTPConnection.close()` — setting `conn.sock` to `None` before a single byte of
  the body is read. The body loop re-armed its idle read timeout on that socket
  every iteration, so every URL fetch died with `AttributeError: 'NoneType'
  object has no attribute 'settimeout'` and the agent reported the failure as a
  sandbox networking problem. The loop now re-arms the timeout on a socket
  reference captured before `getresponse()`, and stops once the body is closed
  (the fd is really gone by then). The idle read timeout is preserved rather than
  dropped: it is still bounded by both `IDLE_READ_TIMEOUT_S` and the remaining
  total budget on every read.
- **Tool results carrying images work on GPT models** — OpenAI GPT models on
  Bedrock Converse reject an `image` block nested inside a `toolResult`
  (`ValidationException: This model doesn't support the image field for user
  messages`), which broke slide-preview review in compose and `web_fetch` on
  image URLs. A `BeforeModelCallEvent` hook (`agent/message_hooks.py`) now
  moves such images up to sit beside the `toolResult` in the same user message
  — a shape both GPT and Claude accept, so it is applied to every model rather
  than gated per model. The image still reaches the model, so vision is
  preserved. It runs before every model call (not on message-added), so it also
  normalizes pre-seeded composer history and restored sessions.
- **GPT models no longer send `temperature`** — both GPT-6 Astra and GPT-5.6
  Terra reject the field on Converse (`This model doesn't support the
  temperature field`). The removed `bedrock-mantle` path had accepted it, so
  the profile carried `temperature=0.7` until the migration.

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
[migration guide](docs/en/migration/v0.5.md) for upgrade steps.

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

[Unreleased]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.10.4...v0.11.0
[0.10.4]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.10.3...v0.10.4
[0.10.3]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.10.2...v0.10.3
[0.10.2]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.10.1...v0.10.2
[0.10.1]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.8.2...v0.9.0
[0.8.2]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.7.1...v0.8.0
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
