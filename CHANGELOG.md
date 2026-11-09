# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(while in 0.x, breaking changes may occur in MINOR releases).

Entries before v0.5.0 were written retroactively as summaries.

Under an Upgrading section, the bullets after **Local installs (`sdpm update`).** are what
`sdpm update` prints when it brings that version in; each says what to do.

## [Unreleased]

### Fixed

- **Cloud chat: a reply the model's content filter stopped now says so.** Strands ends such
  a turn normally with no text, so the chat showed an empty reply. The agent now sends a
  `content_filtered` error for a `content_filtered` or `guardrail_intervened` stop, and the
  Web UI shows "The model stopped its reply because of its content filter".
- **Cloud `run_python` and `run_style_python` stop user code after 120 seconds.** The tool
  returns `Error: execution timed out (120s)…` as a normal result, so the composer can go
  on. Before, a hung call blocked the composer for 10 minutes and then failed with
  `ConflictException … Session already terminated`, which hid the real cause. Stopping a
  session the sandbox already ended no longer replaces the result.
- **Cloud chat: throttling names the cause.** The message now says the model's usage quota
  or rate limit was reached and suggests waiting or choosing another model in Settings, in
  English and Japanese.
- **Local: `init_deck_workspace` refuses a path as the deck name.** Given a name such as
  `/Users/me/decks/q3`, it used to create `<deck root>/<timestamp>-/Users/me/decks/q3`, a
  folder nested under a date-only folder that the Web UI does not list. The tool (and the
  CLI `init_deck_workspace` without `-o`) now returns an error saying the name is a folder
  name without a path, and creates nothing; decks always go to `<deck root>/<timestamp>-<name>`.
  `make test` no longer leaves such folders in `~/Documents/SDPM-Presentations`.
- **New styles get a real name and description.** "Create with AI" on the Styles page used
  to save a placeholder right away as `style-<date>-<time>` with the title "Untitled Style"
  and told the agent to keep that name, so every new style (and every abandoned attempt)
  showed up that way in the gallery and `list_styles()`. The page now opens the chat with no
  file; the agent names the style after what it is for, writes the `<title>` description
  from the first save, and the page then moves to that style. Styles you already have keep
  their names.

### Added

- `sdpm open <deck>` opens a deck in the browser Web UI and starts the Web UI if it is not
  running. For clients that do not declare MCP Apps, the local MCP server adds a note for the
  user naming that command (`note_for_user`) to the result when it creates or builds a deck in
  the deck root `sdpm open` searches.
- **A style gallery in MCP Apps clients.** In a client that declares MCP Apps
  (`io.modelcontextprotocol/ui`), the `list_styles` result shows as cards in the chat with
  each style's slides; **Use this style** sends the choice back as the user's message. Both
  the local and the remote server serve it; the remote shows the user's own styles from S3.
  The view reads previews through `app_action`, a tool only the view calls, which clients
  without MCP Apps do not see in `tools/list`. Their `list_styles` result is unchanged. The
  servers declare the extension in their initialize result. The remote server is stateless,
  so it lists `app_action` only to clients that declare MCP Apps in each request's `_meta`;
  a host that refuses view calls to unlisted tools shows the remote gallery's cards without
  previews, and **Use this style** still works.
- **A deck viewer in MCP Apps clients**, on the local and the remote server. `check_specs`
  opens it on the Outline tab with the check's errors and warnings, and the new
  `show_deck(deck_id)` opens it on the Slides tab; one view holds the Brief, Outline and Slides
  tabs and a **Refresh** button. Slide previews are the compose SVG the Web UI's live preview
  draws, shown in its final state (a JPEG of the preview image when a slide has none, as for
  HTML decks), and a machine that cannot make previews says what to install. A host that
  redacts long base64 strings in a view's data (Kiro Crew does) leaves embedded images empty,
  and the view says so; text and shapes still show. Frames drawn on a slide with a comment are saved as
  `reviews/<id>.json` and sent as the Web UI's review message; outline edits come back as a
  diff for the agent to apply; **Outline looks good** confirms the outline. The slide view asks
  for full screen where the host offers it. Clients without MCP Apps see no new tool
  (`show_deck` is listed only to MCP Apps clients) and the same `check_specs` result; the
  remote server lists `show_deck` only to clients that declare MCP Apps in each request's
  `_meta`.
- **Two built-in styles for Japanese decks: `gradient-card` and `mono-blue`.**
  `gradient-card` is dark, for technical walkthroughs on a shared screen: rules, bands, icon
  nodes and connectors with a thin blue-to-violet gradient, and one magenta outline for the
  subject. `mono-blue` is white, for briefings read alone afterwards: sentence titles, a grey
  takeaway band and one blue pointer per slide. Both draw their own cover and closing, so
  they work with the bundled `blank-dark` and `blank-light` templates; the catalogue now has
  18 styles.

### Changed

- A deck made through an MCP client opens in the Local Web UI as a new chat on that deck
  without the "no Kiro session" notice.
- Clearer descriptions for the briefing, prism-dark, signal, aws-console, bento,
  neo-brutalist and prism-light styles: each now says when to use it.
- **The orchestrator picks a style through `list_styles`.** `start_presentation` no longer
  returns `styles` (with only the bundled styles its result shrinks from about 16,700 to about
  10,300 characters); it still returns the templates and the output directory. The orchestrator calls
  `list_styles()`, chooses from the user's pinned and own styles (every style when nothing
  is pinned), and calls `list_styles(include_all=true)` when none fits or the user wants to
  see others. In MCP Apps clients the style gallery now shows during a normal request. The
  Cloud agent's system prompt carries the templates only and lists styles with the same
  tool. `start_style` still returns every style. Pins that match no existing style now
  count as no pins: for a user with no styles of their own, `list_styles()` returns every
  style instead of none.

### Removed

- The local `list_styles` no longer opens a browser gallery or writes
  `/tmp/sdpm-styles-index.html` and `/tmp/sdpm-styles-gallery/`. The CLI `list_styles` prints
  the text listing only, and its `--no-browse` option is gone: drop it from scripts.
  `sdpm.knowledge.reference.open_styles_gallery` and `generate_styles_index` are removed
  with it.

## [0.13.0] - 2026-11-09

The Local Web UI now runs kiro-cli on its V3 engine and composes slides in the background,
as the Cloud Web UI does. Local installs follow releases instead of `main`, the Kiro CLI
`sdpm` agent no longer hands requests to copies of itself, styles draw icons from the asset
catalog instead of embedding them, and `start_composing` returns under 25,000 characters
for a 3-slide deck instead of about 80,000.

### Upgrading from 0.12

**If `sdpm update` stops with "Your local changes to the following files would be
overwritten by merge"** (`sdpm/uv.lock`, `web-ui/next-env.d.ts`): the `sdpm` command of an
install from before this release cannot get past files its tools rewrote. Run the installer
again (it keeps your profile, agent name and registered clients), or set the changes aside
and update again:
`git -C ~/.sdpm/checkout -c user.name=sdpm -c user.email=sdpm@localhost stash && sdpm update`.
See [Troubleshooting](docs/en/getting-started.md#sdpm-update-stops).

**If you installed with `SDPM_LAUNCHER_DIR`** and that directory is not on `PATH`, set
`SDPM_LAUNCHER_DIR` again for the first `sdpm update` after 0.12, or run the installer
again. That update replaces the `sdpm` command only where it finds it.

**Local installs (`sdpm update`).**

- **sdpm follows releases.** `sdpm update` and the installer now move your install to the
  latest release, never back to an older commit. The first `sdpm update` after 0.12 pulls
  `main`, then moves to the latest release that contains the commit you had. An install
  ahead of the latest release (one updated before 0.13.0 was out) stays and says so
  (`Staying on …`) until a release contains it. To follow every merged change, run
  `sdpm update --channel main` once (`--channel release` goes back).
- **The `sdpm` command is a small bootstrap now.** The first `sdpm update` after 0.12
  replaces it; commands, options and output stay the same. `~/.sdpm/state.json` now records
  the installed version, the channel, the profile, the Kiro agent name and the registered
  clients. It replaces `~/.sdpm/.profile` and `~/.sdpm/.agent-name`: the first update keeps
  them, the next `sdpm update` or installer run removes them. Nothing to do, unless a script
  of yours reads those two files: read `state.json` instead.
- **Kiro CLI.** `sdpm update` has rewritten the `sdpm` agent (or the name you chose at
  install). kiro-cli 2.x and 3.x both load it as it is, and it waits for the sdpm server
  before its first turn, so kiro-cli 3.x no longer hands your request to a copy of itself.
  What other tools added to the agent is kept. Start it as its own agent:
  `kiro-cli chat --agent sdpm` (or `/agent sdpm`). Run `make register-dev` again for a
  development agent.
- **Browser Web UI (`sdpm webui`).** It now runs kiro-cli on its V3 engine, which needs
  kiro-cli 3.0 or later (`kiro-cli --version`). With an older kiro-cli the chat says
  kiro-cli could not start: update kiro-cli, or choose V2 in Settings → Agent engine. The
  other Web UI changes are under "Local Web UI" in the CHANGELOG.

**Local Web UI.** These items apply to the browser Web UI on your machine (`sdpm webui`, or
`npm run dev:local` in `web-ui/`). Each item below is "what changes / what to do".

- **The Local Web UI runs kiro-cli on its V3 agent engine.** New chats and reopened decks
  start `kiro-cli acp --agent-engine v3`; the sdpm agents run as V3 modes. / Check the
  kiro-cli version as in **Browser Web UI** above. To go back to the V2 engine, open
  Settings → Agent engine and pick V2, or write `{"version": 2, "engine": "v2"}` to
  `servers/local/.sdpm/acp-config.json`. The setting takes effect from the next message.
- **Agent definitions are generated in a form both engines read.**
  `servers/local/.kiro/agents/` now carries `permissions` rules, and its marker file is
  `README.txt` (V3 reads every `.md` there as an agent). The orchestrator dispatches
  composers with `@sdpm/compose_slides` instead of the `sdpm-composer` sub-agent. / Nothing;
  the directory is regenerated on the next chat. A definition you added to `acp-agents/`
  without `permissions` is converted the same way. One that has `permissions` is used as
  written.
- **An old `servers/local/.sdpm/acp-config.json` keeps only the command and environment.**
  Its `args` (for example `--agent sdpm-spec`) are no longer used: V2-only flags would keep
  kiro-cli on V2. / Nothing. The file is rewritten in the new form the first time you change
  the engine in Settings, and the old one is kept as `acp-config.v1.json.bak`.
- **Existing decks keep their conversation.** V3 loads the V2 session a deck's `.session`
  names and carries its history over. A deck whose session kiro-cli no longer has starts a
  new one and says so above the reply. / Nothing. If you switch back to V2, decks started
  under V3 start a new conversation, and decks you continued under V3 resume from where they
  were before the switch. The two engines keep separate histories after that: switching back
  and forth, each engine continues from its own last turn in that deck, so the turns made
  under the other engine are not in its context. When that happens, the chat says so above
  the reply; the deck files themselves are always up to date.
- **Each chat runs its own kiro-cli, on V3 as on V2.** At most three kiro-cli processes with
  a chat run at once; a new chat ends the least recently active idle one. A chat that is
  working (opening, running a turn, preparing its prompt or composing in the background) is
  never ended by that limit or by an engine switch; when every chat is working, one more
  kiro-cli starts. A chat whose kiro-cli was ended reopens its session with your next
  message. / Nothing.
- **Slides are composed in the background.** The orchestrator hands the slides to composers
  and ends its turn, so the chat answers while they work. Each composer runs in its own
  kiro-cli, up to four at a time, next to the chats' kiro-cli processes: about 0.5 GB of
  memory per idle composer, up to about 0.87 GB while it renders previews. Stop ends the
  composers within about 1 s, and a change of direction you send while they work reaches
  the running composers. A closed tab does not stop them; the reopened deck shows the
  result. / Nothing; there is no setting or restart.
- **Model and effort are chosen in the chat.** A pill above the chat input sets this chat's
  model and, on V3, its effort. Settings → Model stays the default for new chats. The
  composers run on the chat's model and effort instead of the Settings model. / Nothing.
- **The Web UI lists the decks in your `output_dir`.** If you set `output_dir` in
  `~/.config/sdpm/config.json` (or `SDPM_OUTPUT_DIR`), the Web UI now uses that folder, like
  the MCP server and the CLI. / Decks you made in the Web UI before stay in
  `~/Documents/SDPM-Presentations` and no longer show: move them into your `output_dir`, or
  set `SDPM_DECK_ROOT` to that old folder. Restart the Web UI after changing `output_dir`.
- **Your global Kiro steering applies to the sdpm agents.** Rules in `~/.kiro/steering` that
  are always included reach the sdpm agents' context, under V3 as under V2. / Nothing.

### Added

- **Local Web UI: send a message while the agent works.** As in Cloud, the chat input stays
  open during a turn, and a message sent then goes into the running turn through kiro-cli's
  `_session/steer`. The bubble shows "Sent while the agent works", then "Read by the agent".
  If the turn ends before the agent reads it, the turn continues with that message. Stop
  marks an unread message "Not delivered" and removes it from kiro-cli's queue, so it does
  not join your next message. When kiro-cli does not accept the message (no turn running any
  more), the chat says so and keeps the text in the input.
- **Local Web UI: kiro-cli's V3 engine can run the sdpm agents.** Settings has a new
  **Agent engine** section (Local only) to choose V3 or V2; the choice is saved in
  `servers/local/.sdpm/acp-config.json` and takes effect from the next message, and decks
  whose kiro-cli is idle reopen their session on the new engine. The agent definitions under
  `servers/local/.kiro/agents/` are now generated in a form both engines read (V3 permission
  rules next to the V2 fields; the marker file is `README.txt`). On V3 a deck keeps its
  conversation, including decks started on V2; when a deck's session also ran on the other
  engine, the chat says so above the reply, since each engine keeps its own history. kiro-cli's
  permission requests are answered automatically only within the safe default: sdpm MCP
  tools and file reads on the deck folder and kiro-cli's `tool-outputs/`, always with the
  offered allow-once option. / See Upgrading from 0.12.
- **Local Web UI: choose the model and effort in the chat.** A pill above the chat input
  shows the chat's model and opens a menu of the models kiro-cli offers and, on V3, the
  effort levels of the chosen model (V2 has no effort). The choice changes this chat's kiro
  session at once when it is idle, otherwise from the next message, and kiro-cli keeps it
  with the session. Settings → Model stays the default for new chats; the composers follow
  the chat's choice. Settings → Model lists the models without starting kiro-cli. /
  Nothing.
- **Local Web UI: slides are composed in the background.** As in Cloud, the orchestrator
  dispatches the composers with `compose_slides` and ends its turn, so you can keep chatting
  while they write the slides. A change of direction reaches a running composer through
  `message_composer`; when every group has finished, the orchestrator gets the report once
  and tells you. Stop ends the composers within about 1 s; a closed tab does not stop them,
  and the reopened deck shows the result. Each composer runs in its own kiro-cli, up to four
  at a time: about 0.5 GB of memory per idle composer, up to about 0.87 GB while it renders
  previews. On V3 and V2. / Nothing.

### Changed

- **Composers get their inputs inline and read the rest on demand.** `start_composing` now
  returns `deck.art_direction_toc` (each block of `specs/art-direction.html` as a line range
  with its comments) instead of the whole style in `deck.art_direction`, and `static.slide_spec`
  is the core of the slide format; element fields, effects, media and visual forms moved to
  the new guides `slide-json-elements`, `slide-json-media`, `slide-json-effects` and
  `visual-forms` (HTML: slide scripts to `slide-html-scripts`). The composer role documents
  say which parts to read. The result for a 3-slide deck with any bundled style stays under
  25,000 characters (it was about 80,000), so kiro-cli's V3 engine no longer moves it to a
  file. `apply_style`'s `style_toc` entries gain `start` / `end`, and each slide's `comment`
  now lists the comments inside its range. / A client that read `deck.art_direction` reads
  `specs/art-direction.html` instead.
- **The installer and `sdpm update` follow the latest release.** The install line is the
  same, but it installs the newest release tag (`vX.Y.Z`, no pre-releases) instead of the
  tip of `main`, and `sdpm update` moves to the next release. Neither ever moves an install
  backwards: one ahead of the latest release stays until a release contains it (exit 0, one
  line). `--channel main` (`-Channel main`, `SDPM_CHANNEL=main`) follows `main`; the choice
  is kept in `~/.sdpm/state.json` and `--channel release` goes back. The checkout is moved
  to the target commit (detached), changed tracked files go to a named git stash as before,
  and when the new version's Python environment or Web UI cannot be prepared, the install
  goes back to the commit it was on and re-syncs that environment (`Back on …, as before`).
  The Web UI is rebuilt only when the commit changed. / Nothing. Run
  `sdpm update --channel main` if you want every merged change.
- **The `sdpm` command is a small bootstrap.** It fetches and hands every command to the
  checkout (`servers/local/checkout_update.py` for `sdpm update`,
  `servers/local/sdpm_command.py` for the rest), so a fix to `sdpm update` reaches every
  install with the release that carries it. The installer stops writing the command itself:
  the installed version writes it. Commands, options and output stay the same; the status
  line also names the channel. / Nothing.
- **`~/.sdpm/state.json` records the install.** The installed release and commit, the
  channel, the profile, the Kiro agent name and the registered clients. It replaces
  `~/.sdpm/.profile` and `~/.sdpm/.agent-name`, which the first update or installer run
  with the new `sdpm` command moves into it and removes. `~/.sdpm/.uv-path` stays. / Nothing.
- **Nothing waits for input without a terminal.** Without a terminal (an agent, CI, a pipe)
  the installer behaves as with `--non-interactive`; when sudo needs a password there, it
  prints the commands to run and exits 1. `sdpm update` never prompts and reports through
  its exit code (0 updated, up to date or stayed; 1 failed; 2 usage; 130 interrupted).
  `sdpm register` without a terminal registers nothing unless given `--yes` or client names
  (exit 2), and `sdpm uninstall` asks to be run in a terminal. / Agents: see AGENTS.md
  "Updating it for a user".
- **Each release carries six small manifests.** `release-{macos,linux,windows}-{install,update}.json`,
  generated by `release.yml` from `scripts/release/manifest.toml`. Each install and update
  downloads the one for its OS and kind of run; GitHub counts these downloads, and nothing
  else is sent. A release without manifests, or one that cannot be fetched, falls back to
  the git tags. Release tags must be on `main`; other tags are published as pre-releases or
  refused. / Nothing.
- **`sdpm update` brings the whole install up to date.** After the pull and the rebuild it
  replaces the `sdpm` command with the checkout's launcher and registers SDPM again with
  the MCP clients that already have it: the Kiro CLI agent (under the name chosen at
  install), Claude Code and Codex. It adds no client; clients it finds without SDPM are
  named with the `sdpm register` command that adds them. VS Code and Cursor cannot report
  whether they have SDPM, so they are left as they are, and so is a Claude Code or Codex
  `sdpm` server that runs another checkout (`make register-dev`). It removes what earlier versions
  left and nothing uses: `servers/local/.venv` and `sdpm/.venv` (before 0.12), the files of
  the old Kiro installer, and the `.bak` copies kiro-cli 3.x made of the `sdpm` agent. Last,
  it prints the Upgrading notes for local installs that are new since your previous
  version. The `sdpm` command of an install made before this change does not replace
  itself; its first `sdpm update` does all of this once, and later updates run the new
  command. The "Installing icon catalogs" step is gone: it never installed anything (the
  installer installs the catalogs, and the MCP server does when they are missing). /
  Nothing, unless you installed with `SDPM_LAUNCHER_DIR`: see Upgrading from 0.12.
- **Running the installer over an install keeps its choices.** It uses the install's
  profile and Kiro agent name unless `--full`, `--mcp-only` or `--agent-name` says
  otherwise, and instead of the client checklist it registers SDPM again with the clients
  that have it, removes leftovers and prints the upgrading notes, as `sdpm update` does.
  `--register` also adds the detected clients without SDPM; `--no-register` touches no
  client. / Nothing.
- **Local Web UI runs kiro-cli on its V3 engine by default.** V2 stays selectable in
  Settings → Agent engine. / See Upgrading from 0.12.
- **Local Web UI: each chat runs its own kiro-cli, and a chat that is working is never
  ended** by the limit of three kiro-cli processes with a chat or by an engine switch, while
  it opens, runs a turn, prepares its prompt or composes in the background.
  `servers/local/.kiro/agents/` is left as it is when nothing changed. / Nothing.
- **The bundled `aws-light` and `aws-dark` styles have a new content-slide frame.** Every
  content slide now pairs a one-line topic title (a noun phrase) with a lead of up to two
  lines that states the slide's finding, in dark orange (`aws-light`) or amber (`aws-dark`).
  The section label above the title is gone and content starts lower, at y 350 in
  `aws-light` and y 340 in `aws-dark`. The lead colour is part of the frame, so each slide
  still has one orange emphasis. Service icons no longer sit on a category-tint circle with
  a border: the icon stands alone at the same sizes, and its own colours (the category
  square of an `Arch_` service icon, the category-coloured glyph of a `Res_` resource icon)
  identify the category. Category colour stays on labels, group borders and group fills.
  Style names and descriptions are unchanged; decks that
  already use either style keep their copy in `specs/art-direction.html` until
  `apply_style` is run again.
- **The AWS design guide (`guides/aws-design.md`) no longer lists the "AWS default
  template" colour palette.** No bundled template matches it. Icon selection and the AWS
  service category colours stay.
- **The agent runtime runs on AgentCore platform V2.** `platformVersion: "V2"` is now
  declared in `infra/lib/agent-stack.ts`, so the SdpmAgent deploy moves the agent runtime
  to V2, like the MCP runtime in 0.12.0. The agent's environment no longer carries
  `DEPLOY_TIMESTAMP`, so a deploy that changes neither the image nor the configuration no
  longer creates a runtime version. The agent draws the `random` module's values from the
  kernel (`shared/snapshot_random.py`), so OpenTelemetry trace and span ids and retry jitter
  do not repeat across instances restored from the same snapshot. / Nothing. To stay on
  V1, see [Security](docs/en/security.md#agentcore-runtime-platform-versions).
- **Styles carry icon references only.** The style rule (`workflows/style.md`) and the 16
  bundled styles no longer embed icon shapes (`<symbol>`): a style draws an icon with
  `<svg class="icon"><use href="#<source>/<name>"/></svg>`, and every place that shows a
  style (the Web UI gallery and previews in Cloud and Local, and the local browser gallery
  opened by `list_styles`) draws the shape from the asset catalog. Composers read 3–20%
  less per bundled style (`aws-dark` 20%). User styles that embed `<symbol>`s keep working
  as they are and need no rebuild; their own shapes are used. Decks keep their
  `specs/art-direction.html` copy until `apply_style` runs again. A style exported or
  copied to My Styles from the Web UI contains references only.

### Fixed

- **Kiro CLI 3.x: the `sdpm` agent no longer hands your request to a copy of itself.** On
  the V3 engine the first turn went out before the sdpm server had connected, so the only
  slide tool the agent could see was the sub-agent that starts another `sdpm`; it passed the
  whole request down, sometimes several levels, before any slide work began, and the
  innermost copy then wrote every slide alone. The agent now waits for the sdpm server
  (`waitForReady`) and its description says a sub-agent runs only the role its prompt names.
  The first sdpm tool now starts in 7–10 s instead of 16–41 s, and composers run in parallel
  again. / `sdpm update` brings an existing `sdpm` agent up to date.
- **The Local Web UI continues a deck made elsewhere on that deck.** A deck with no kiro
  session to resume (made by an MCP client or Kiro CLI, or whose session kiro-cli no longer
  has) started a new session whose first prompt did not say which deck it was, so the agent
  read other decks and asked which one to work on. That first prompt now starts with
  `Current deck: <deck directory>`, and the orchestrator workflow reads that deck's
  `deck.json` and `specs/` first and continues it. / Nothing.
- **`run_python` shows folders and suggests decks.** The sandbox's `list_files()` returned
  only files, so an agent looking at a deck concluded that `slides/` and `specs/` were
  missing; it now returns folders too, ending with `/` (`slides/`), on Local and Cloud. A
  `deck_id` that is not a deck directory names up to five deck folders called `<name>` or
  `…-<name>` (deck folders are `YYYYMMDD-HHMM-<name>`), newest first. / Code that filters
  `list_files()` by extension is unaffected; code that treats every entry as a file skips
  names ending with `/`.
- **The Local Web UI finds decks in the folder the MCP server writes to.** The Web UI and
  its MCP server (`server_acp.py`) read only `SDPM_DECK_ROOT`, while the CLI and the local
  MCP server (`server.py`) read `SDPM_OUTPUT_DIR` and `output_dir` in `config.json`, so a
  deck made over MCP after changing `output_dir` did not appear in the Web UI. All of them
  now use one order: `SDPM_DECK_ROOT` → `SDPM_OUTPUT_DIR` → `output_dir` in
  `~/.config/sdpm/config.json` (`~` expanded; empty means the default, no longer the
  current folder) → `~/Documents/SDPM-Presentations`. / See Upgrading from 0.12.
- **The Web UI's MCP server installs the icon catalogs by itself.** `server_acp.py` now
  fetches them in the background on first start when none is installed, as `server.py`
  does, instead of the agent asking the Web UI user to run an install command.
  `SDPM_AUTO_INSTALL_ASSETS=0` turns this off. / Nothing.
- **The installer says when its directory is not on `PATH`.** The hint never appeared,
  because the installer had already added the directory to its own `PATH`. / Nothing.
- **`sdpm doctor` no longer installs packages into the checkout.** It ran uv at the
  checkout root, which synced the whole workspace there (and the next `sdpm update` removed
  it again); it now runs in the MCP server's environment. / Nothing.
- **`sdpm webui` opens only an SDPM Web UI.** When its port was taken by another program it
  opened that program in the browser; it now says which port is in use and how to choose
  another (`SDPM_WEBUI_PORT`). Its wait for the server to start ends with a failed start.
  / Nothing.
- **Deploying `SdpmAuth` alone no longer removes the CloudFront URL from the Web UI's
  Cognito app client.** Each `SdpmAuth` deploy that changed the client reset its callback
  and logout URLs to `http://localhost:3000`, so nobody could sign in to the Web UI, and a
  routine `SdpmWebUi` deploy did not put the URL back. `SdpmAuth` now owns the whole list
  (`http://localhost:3000` and the Web UI's CloudFront URL, nothing else): `SdpmWebUi`
  publishes its URL in SSM (`/sdpm/web-ui/site-url`), and a function in `SdpmAuth` writes
  the list after every change to the client and whenever `SdpmWebUi` creates or changes its
  URL. / Deploy `SdpmAuth` before `SdpmWebUi` once (`./scripts/deploy.sh` does); after
  that, either stack can be deployed alone.
- **`sdpm update` gets past changed files in the checkout.** Tools of earlier versions
  rewrote tracked files in `~/.sdpm/checkout` (uv `sdpm/uv.lock`, the Web UI build
  `web-ui/next-env.d.ts`), and the pull then stopped with "Your local changes … would be
  overwritten". The update now moves changes to tracked files into a git stash named after
  the update, lists them and prints the `git stash apply` command that brings them back;
  nothing is reset or cleaned, and untracked files are not touched. The step is
  `servers/local/checkout_update.py`, run as of the fetched `main` before anything is
  checked out, so later fixes to it reach old checkouts too. Running the installer over an
  existing install does the same. Our tools no longer change tracked files: uv runs with
  `--frozen` in the launcher, the installer and the MCP client configuration (`sdpm update`
  registers the clients again with it), and the Web UI build (`npm run build`) leaves
  `web-ui/next-env.d.ts` as committed. / Nothing; an install from before this release, see
  Upgrading above.
- **The `sdpm` Kiro agent keeps what other tools added.** `sdpm register kiro-cli` and
  `sdpm update` rewrote `~/.kiro/agents/sdpm.json` whole, dropping other MCP servers, their
  tools, other tools' settings (for example `toolsSettings.execute_bash`) and kiro-cli's
  `kiroUpgrade`. They now update only what SDPM owns (the `sdpm` server, its tools, allowed
  tools, subagent settings and permission rules) and keep the rest. A file with only
  kiro-cli 2.x fields gets the 3.x permission rule of each addition that has one with the
  same meaning (an allowed MCP server, a trusted agent); when an addition has none, such as
  a 2.x deny list, the file is left as it is and the message names the setting. / Nothing.
  Settings already dropped by an earlier rewrite have to be added again by the tool that
  added them.
- **Registering with a Kiro CLI that is not signed in yet no longer fails.** `kiro-cli
  agent validate` refuses to run before `kiro-cli login`, so `sdpm register`, the
  installer's `--register` and `sdpm update` reported Kiro CLI as failed and exited with 1
  although the agent file was written correctly. The `--full` installer always hit this,
  having just installed kiro-cli. Registration now checks `kiro-cli whoami` first; when
  kiro-cli is not signed in it skips the validation, reports the agent as registered and
  says to run `kiro-cli login` first. / Nothing.
- **Result marks are coloured only on a terminal.** `sdpm register`, `sdpm update` and
  `sdpm doctor` printed ANSI colour codes into logs and agent output. They now colour the
  ✓ / ✗ / ! marks only when the output is a terminal and `NO_COLOR` is not set. / Nothing.
- **MCP runtime: OpenTelemetry ids no longer repeat across V2 restores.** Every microVM
  restored from the same snapshot started the `random` module from the same state, so
  OpenTelemetry trace and span ids (and botocore retry jitter) could be identical across
  instances. The MCP server now draws those values from the kernel
  (`shared/snapshot_random.py`, installed before the server starts). / Nothing.
- **The Web UI style covers and per-slide previews show their icons.** They showed empty
  circles, because the preview dropped the icon definitions placed before the first slide.
- **Local Web UI: a chat turn no longer hangs or ends silently.** When kiro-cli stops while
  it answers, the chat shows that it stopped instead of loading forever, and the next send
  works. A turn that ends because the model refused, or hit its output or step limit
  (`refusal`, `max_tokens`, `max_turn_requests`), closes with a message saying so. An error
  from another request during a turn no longer cuts the reply off. A kiro-cli that does not
  answer at start-up gives a "did not respond in time" message after 30 s (initialize) or
  3 minutes (session start or load) instead of waiting forever. kiro-cli's permission
  requests are answered with an option it offered, which kiro-cli V3 needs. (#518) / Nothing.
- **Local Web UI: Stop works while kiro-cli starts**, also when only `POST /api/agent/stop`
  is sent (another tab): no message is sent to the agent, and the reply's stream ends as
  stopped. / Nothing.
- **Local Web UI: a kiro-cli that exits, or is ended to make room for another chat, no longer
  loses a new chat's conversation.** The chat's next message reopens its session. / Nothing.
- **Local Web UI: decks without a saved Kiro session can be chatted with.** A deck made by
  an MCP client or Kiro CLI has no `.session` file, and sending a message in it answered
  HTTP 500 every time; so did a deck whose kiro session no longer exists (kiro-cli V2). The
  chat now starts a new kiro session, saves it to the deck's `.session` and says above the
  reply that the agent does not have the earlier conversation. Later messages, and the deck
  reopened after kiro-cli was stopped, continue that session. / Nothing.
- **Local Web UI: reconnecting to a running chat no longer repeats its events.** When the
  browser's stream to a running turn dropped and reconnected, it could show text and tool
  steps twice: the live stream numbered its events differently from the buffer the
  reconnect resumes from. The live stream and the replay now use the same event numbers.
  / Nothing.
- **Local Web UI: a deck created while no browser was listening keeps its conversation.**
  The deck's `.session` (and, for a chat continued from a kiro session, its origin) was only
  written while the chat's first stream was open, so a deck made after the tab was closed or
  the stream reconnected did not remember its conversation when reopened. The server now
  saves them as soon as the turn creates the deck. / Nothing.
- **Local Web UI: a reply that finished while the tab was closed shows when the deck is
  reopened.** A reopened deck's chat showed only what had been saved while the tab was open
  (on V3 often nothing), and a deck reopened while its reply still ran did not follow it: the
  reconnect of its own followed only text and tool steps, and only of a running turn. It now
  follows the chat's work the way Cloud's does. A reopened or reloaded deck replays the chat's
  last work once, with the messages sent during it, also when it ended while no tab was open,
  and then follows it live. A message sent while that work runs goes into it, and Stop stops
  it. / Nothing.
- **Local Web UI: kiro-cli start-up failures say what to do.** When kiro-cli is not
  installed or too old, is not signed in, starts another agent than the sdpm one (its
  definitions were rejected), or the sdpm MCP server fails to start, the chat now says which
  and what to do instead of a generic error or a reply from an agent without the sdpm tools.
  The start waits until the sdpm MCP server is ready, so a new or reopened chat no longer
  begins without its tools. A tool call that fails shows as failed. / Nothing.
- **Local Web UI: the Compose card shows each group's slides and finishes.** On both
  engines the card lists the slides each composer group was assigned (the `assigned_slugs`
  line of the delegation), marks every group done or failed as its composer ends, and closes
  once all of them have. Groups delegated in parallel share one card. A card could keep
  spinning after the turn was over (V3 never closed it, V2 kept groups without an end); now
  the end of the turn closes it, and a group still running then, after a Stop for example,
  shows as failed. / Nothing.
- **Local Web UI: "Continue from a kiro session" lists kiro-cli's V3 sessions.** The list
  read only V2's session files, so sessions saved by kiro-cli 3.x's default engine (V3) were
  missing. With the agent engine set to V3, the list now has V3's sessions, from kiro-cli's
  own session list, and the earlier V2 sessions next to them, newest first, each with a small
  V3 / V2 badge. Picking one branches it with kiro-cli's fork; a V2 session is imported by
  V3. With the agent engine set to V2, only V2 sessions are listed, and a line under the list
  says so. The original session is never changed. / Nothing.
- **Kiro CLI: the `sdpm` agent loads as-is in kiro-cli 3.x (V3).** `sdpm register` wrote
  the agent in the 2.x format only (`allowedTools`, `toolsSettings`). V3 converts such a
  file when it starts and saves the old one as `sdpm.json.bak`, `sdpm.json.bak.1`, and so
  on, once more after every `sdpm register`. With `chat.enableAutoAgentUpgrade` set to
  `false` it did not convert the file. Interactive chat then fell back to the default
  agent without the sdpm tools, and `--no-interactive` stopped with exit code 4. The agent
  file now also carries the V3 fields (`permissions.rules`, `subagent/<name>`), so V2 and
  V3 both read it unchanged and it is never rewritten. `sdpm unregister` also removes the
  `.bak` copies that V3 made of our file. Start the agent itself (`kiro-cli chat --agent
  sdpm` or `/agent sdpm`). When another agent delegates to `sdpm`, V3 asks you to approve
  each sdpm tool the sub-agent calls. / `sdpm update` rewrites the agent file (see
  Changed). Run `make register-dev` again for a development agent.
- **Web UI: a reload or a direct link opens the deck with its conversation.** Reloading a
  deck page, or opening `/decks/#<id>` from a link, put the chat on the empty "New" tab and
  closed it, so the deck's saved conversation looked gone; only opening the deck from the
  list showed it. Both now open the deck's chat tab (and the chat panel on a desktop
  window), as the list does. The address is read once the page has loaded, which also stops
  the hydration error React reported for direct links. / Nothing.
- **Local Web UI: no wording for features that only the cloud Web UI has.** The search box
  said "Search slides across the organization…", but the Local Web UI filters your decks by
  name; it now says "Search decks…". The deck header no longer shows the Private / Internal
  sharing button, since Local decks are never shared. The cloud Web UI is unchanged. /
  Nothing.

### Security

- **Local Web UI: the server answers only requests addressed to it by a loopback name.**
  Every request to the Local server (API routes and pages) must carry a `Host` of
  `127.0.0.1`, `localhost` or `[::1]` on the server's own port; anything else, or no `Host`,
  gets 403 before a route runs. Before, a web page on another domain that resolved to
  127.0.0.1 could reach the API, which has no sign-in. The check runs in one place
  (`web-ui/src/proxy.ts`), so new routes are covered, and it has no mode check of its own, so
  it applies wherever the API routes are served; the cloud build leaves it out with the API
  routes. The agent selection and model `PUT`s now also refuse cross-site requests and
  non-JSON bodies, and listing the models is a `GET` that never starts kiro-cli. Open the
  Web UI as `http://localhost:<port>` or `http://127.0.0.1:<port>`; another host name
  pointing at the machine is refused.
- **Cloud agent: `web_fetch` reaches public internet addresses only.** The agent's
  `web_fetch` tool now fetches through the same URL fetcher as the MCP attachment tools
  (`sdpm.tools.attachment.fetcher`). It rejects schemes other than http(s), ports other than
  80 and 443, and hosts that are, or resolve to, private, loopback, link-local or reserved
  addresses, including the instance metadata endpoints (`169.254.169.254`,
  `fd00:ec2::254`) and the AgentCore platform server on localhost. Every redirect hop is
  checked again, an HTTPS page cannot redirect to HTTP, and the connection goes to the
  address that passed the check, so a second DNS answer cannot redirect it. The agent gets
  a short error naming the URL and the reason. Public pages, PDFs and images are fetched
  as before. (AgentCore review F4) / Nothing.

## [0.12.0] - 2026-11-05

The Cloud Web UI now lets you send a message while the agent works, stop it for good,
come back to a running session, and keep chatting while composers write in the
background. It also adds comments on the preview, faster first replies and tighter
defaults for the AWS stack.

### Upgrading from 0.11

**AWS stack.** This release changes SdpmAuth, SdpmData, SdpmRuntime, SdpmAgent and
SdpmWebUi. Update them in one run: `git pull && ./scripts/deploy.sh`, or
`npx cdk deploy --all` in `infra/`. The new Web UI needs the new agent, and CDK updates
SdpmAgent before SdpmWebUi. Each item below is "what changes / what to do".

- **Self sign-up is off by default.** The SdpmAuth deploy switches an existing user pool
  to administrator-created users and removes sign-up from the sign-in page; existing users
  keep their accounts. / To keep self sign-up, set `auth.selfSignUp: true` in
  `infra/config.yaml` before you deploy, and optionally list `auth.allowedEmailDomains`.
  Otherwise create users as in the
  [Deploy guide](docs/en/deploy-cloudshell.md#creating-a-cognito-user-layer-4).
- **The runtimes carry resource policies.** The agent and MCP runtimes and their endpoints
  allow `InvokeAgentRuntime` and `StopRuntimeSession` (plus
  `InvokeAgentRuntimeWithWebSocketStream` on the agent runtime, for the Web UI's `/ws`) and
  deny `InvokeAgentRuntimeCommand`; the policies arrive with the SdpmRuntime and SdpmAgent
  deploys. / Nothing for the Web UI, the agent or MCP clients. A caller that used
  `InvokeAgentRuntimeCommand` gets 403.
- **Session ids carry their owner.** New session ids start with a prefix derived from the
  user's `sub`, and the agent and MCP runtimes admit such an id only for that user. Ids of
  the earlier format keep working when AgentCore Memory holds that user's history for them,
  so existing decks keep their chat. / Reload a chat tab that asks for it (once). A program
  that calls the agent's `/invocations` itself (a Slack or Teams bot) must start new session
  ids with the owner prefix and send the same id in the
  `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header; see
  [Teams & Slack](docs/en/teams-slack-integration.md#request-body). MCP clients need no
  change.
- **The MCP runtime runs on AgentCore platform V2.** `platformVersion: "V2"` is now
  declared in `infra/lib/runtime-stack.ts`, so the SdpmRuntime deploy moves the MCP runtime
  to V2, and a deploy that changes neither the image nor the configuration no longer creates
  a runtime version. / Nothing. To stay on V1, see
  [Security](docs/en/security.md#agentcore-runtime-platform-versions).
- **Runtime log groups expire.** The deploy gives the AgentCore runtime log groups,
  existing ones included, the retention in `observability.logRetentionDays` (default 30
  days), so CloudWatch Logs removes older log data after the deploy. Model request and
  response bodies are no longer written to `otel-rt-logs`. / To keep logs longer, set
  `observability.logRetentionDays` before you deploy; export anything older that you need
  first.
- **The agent's AWS knowledge tools are documentation tools only.** The agent connects to
  the public AWS Knowledge MCP Server and offers five documentation tools; the agent role
  no longer has `aws-mcp:*`. / Nothing, unless your agent relied on other AWS MCP Server
  tools.
- **Narrower execution roles.** The agent runtime no longer has the decks table, the PPTX
  bucket or the `DECKS_TABLE` / `PPTX_BUCKET` variables. / Only forks whose agent code
  reads them need a change.
- **REST API.** Deck sharing is gone (`GET /decks/shared` and the `collaborator` role);
  deck lists no longer return `createdBy`; `GET /decks/{id}` returns `chatSessionId` to the
  owner only and ignores `include=slideJson`; upload handles are `uploads/{uuid}/{name}`
  (the earlier `uploads/{userId}/…` form is still accepted for the caller's own uploads
  during a transition). / Only clients that call the API directly need to adapt. To show a
  deck to others, make it public or send the PPTX / HTML.
- **Python dependencies (forks).** One uv workspace and one root `uv.lock` replace the
  per-package locks and the `requirements*.txt` / `constraints.txt` files; the Agent image
  builds from the repository root. / To change a dependency, edit the member's
  `pyproject.toml` and run `make lock`.

**MCP clients and CLI.** No tool was added, removed or renamed (still 20), no tool argument
changed, and the CLI commands are unchanged. These results changed:

- `run_python` on PPTX decks returns the same result locally and in the cloud. Read build
  warnings from `warnings["build"]` (`warnings` is now an object with `outline`,
  `layoutBias` and `build`), lint results from `errors.lintDiagnostics` (the top-level
  `lint_diagnostics` is gone), and parse `measure` as JSON (`{"error": …}`) when it does not
  start with `📐`.
- Cloud `run_style_python` returns `saved` as `{filename, name}`, without the S3 key.
- Cloud `read_attachment` / `import_attachment` take and return upload handles
  `uploads/{uuid}/{name}`.
- Local installs: `sdpm update` works as before. The MCP server's environment moves from
  `~/.sdpm/checkout/servers/local/.venv` to `~/.sdpm/checkout/.venv`; you can delete the
  old `servers/local/.venv` and `sdpm/.venv`.

### Added

- **Cloud chat: send any time, stop, reconnect and compose in the background.** In the
  Cloud Web UI (#502, #506, #510, #512, #513):
  - The send button stays enabled while the agent works. A message sent then is a steer: it
    reaches the running turn at its next step and shows in the chat, and in Memory, where
    the agent accepted it. A steer that a stop discarded is marked as not delivered.
  - The stop button stops the session's work, composers included. After a stop the agent
    starts no new tool call, MCP call or Memory event; a Presentation Maker call already
    running on the MCP runtime finishes there (a few seconds), as in Local mode. Without an
    acknowledgement in 3 seconds the Web UI falls back to StopRuntimeSession, and the agent
    process exits within 3 seconds of SIGTERM. Closing the tab never stops a turn; a
    60-minute watchdog bounds the work.
  - Opening the deck again, reloading the page or waking the computer while the session
    works reconnects and replays what was missed. When the session's process is gone, the
    chat shows the Memory history.
  - `compose_slides` runs in the background. The orchestrator says what is being composed
    and ends its turn, and you can keep chatting. The compose card stays live across turns
    and reloads and closes when the report arrives; the orchestrator then reviews the
    slides in a turn of its own. While composers run, the orchestrator can correct one with
    `message_composer`, and a composer can answer or raise a decision with
    `report_to_orchestrator`; both show in the chat as composer notes.

  The Web UI talks to the agent over a `/ws` WebSocket, and a session keeps its MCP
  clients, Agent and Memory session manager across turns. `/invocations` (Local and
  external clients) runs on the same session runtime: a turn that dispatched a compose
  streams until the session is idle and gets the report as the compose's `toolResult`, and
  a prompt that arrives while WebSocket-started work runs becomes a steer. Local mode is
  unchanged.
- **Comments on the preview.** Turn on the **Comment** tool (preview header, `C`, or the
  button on a hovered slide), draw or click frames on the slides, name them in comments
  with `@A`, and send them with **Request changes** (「修正を依頼」) as one change request.
  Unsent frames survive a reload. The server writes `reviews/<id>.json` in the deck and
  returns the chat message; the orchestrator dispatches one composer per slide, and the
  chat shows the request as a card. HTML decks show static slide previews while the tool is
  on. New API route `POST /decks/{id}/reviews`, with a matching local route; `get_deck` now
  returns `slideSize` for PPTX decks too. Desktop only, Local and AWS. (#473)
- **`agent-spectrum` style.** A bundled concept style for slides that are watched rather
  than presented (screen recordings, README stills): near-black ground, light type, the Web
  UI's five builder colours and a five-segment stripe on every slide. (#489)

### Changed

- **Faster first reply on the AWS stack.** The agent connects its MCP clients, loads the
  Memory session and fetches `start_presentation` at the same time, and fetches the role
  documents and the user's style and template lists once per agent process. The optional
  AWS Knowledge and AWS Pricing clients connect once per process; a turn does not wait for
  one that is still connecting (the chat shows it as not connected in time). The new deck
  screen builds the session before the first prompt. The MCP server warms LibreOffice once
  per process after the client has been quiet for 3 seconds, instead of on health checks,
  and loads its static data into the V2 snapshot. A style or template added during a
  session reaches the system prompt in the next agent session; `list_styles` /
  `list_templates` always return the current lists. (#503, #504, #510)
- **Self sign-up is off by default in the AWS stack.** The default Cognito user pool
  accepts only users created by an administrator. `auth.selfSignUp: true` turns sign-up on,
  and `auth.allowedEmailDomains` limits it to the listed domains (exact, case-insensitive,
  checked by a Pre sign-up Lambda trigger; administrator-created users are not checked).
  One-Click Deploy still creates the first user. See
  [Developer guide](docs/en/developer-guide.md#default-amazon-cognito-user-pool). (#498)
- **`run_python` returns the same result for PPTX decks locally and in the cloud.** The
  post-processing after a PPTX edit (build, render of the changed slides, measurement,
  compose, previews) lives in `sdpm.api.refresh_pptx`. In the cloud the rebuilt PPTX now
  goes through the same build as `generate_pptx`, and previews are rendered from the
  changed slides only. See Upgrading for the result fields. (#494)
- **README and documentation.** The README opens with an animation of the Web UI building a
  deck, the install commands and a gallery of seven styles, and shows the three ways to use
  SDPM. `docs/en/getting-started.md` is the user guide; setup and CDK deployment moved to
  `docs/en/developer-guide.md`, security notes to `docs/en/security.md`, migration guides to
  `docs/en/migration/`. Diagrams are redrawn from the current code; new Japanese pages for
  custom templates and uninstall. (#484, #489)
- **One Python lock.** The repository root is a uv workspace (`sdpm`, `servers/local`,
  `servers/remote`, `agent`, `api`) with one `uv.lock`; the runtime images and the API
  Lambda bundle install exactly the locked versions, hash-checked. (#475)
- **CI and Dependabot.** CI builds and starts both runtime images and imports the API Lambda
  bundle in the Lambda runtime image. Dependabot minor and patch updates for uv and GitHub
  Actions merge on their own once the required checks pass. (#474, #476)
- **Upload conversion moved into the core.** PDF / DOCX / XLSX / PPTX conversion lives in
  `sdpm.tools.attachment.ingest`, so `sdpm-skill` now depends on `pypdf>=6.15.0`,
  `pdfplumber`, `python-docx` and `openpyxl`. Results are unchanged. (#477)
- **One style per name in the AWS style lists.** A user style saved under a bundled style's
  name is listed once, as the user's, in the Web UI gallery and in `list_styles` /
  `start_style`, as Local already did. (#491)
- **One set of attachment rules for every client.** How the orchestrator reads and cites
  attachments lives only in `orchestrator.md` and the `attachments` guide; the AWS agent
  prompt keeps only the `[Attached:…]` marker format, so Cloud briefs follow the Local
  rules and every attached file is imported. (#492)

### Removed

- **Deck sharing with specific users and the `collaborator` role (breaking).** The Share
  dialog, the **Shared** tab and `GET /decks/shared` are gone. The feature never worked:
  nothing wrote the sharing records. Deck roles are owner / viewer / none. To show a deck to
  others, make it public (**Internal**) or send the PPTX / HTML. (#479)
- **Unused code.** Unused Web UI components and dependencies, the `include=slideJson`
  option of `GET /decks/{id}` (now ignored), the local `/api/agent/config` route and the API
  Lambda's direct document-parser dependencies. (#478)
- **The compose card's own stop button and the composers' time budget.** The compose card's
  **Cancel** button and its "Stopping…" state are gone; the main stop button next to the
  chat input stops compose too. Composers no longer get a per-slide deadline or the "Time
  budget reached" notice, and the card no longer shows "rushed". A composer is still
  stopped after 5 consecutive tool errors or a tool-call loop. (#500)

### Fixed

- **Decks with speaker notes built on a template without a notes master now open in
  Keynote and Quick Look.** The builder declares the notes master in `presentation.xml`.
  Regenerate existing decks to pick up the fix. (#508, thanks @takke1986)
- **Deploying `SdpmAuth` no longer removes the `sdpm-mcp/invoke` scope from the Web UI's
  Cognito app client**, which made the agent's calls to the MCP runtime fail with 401. The
  client is updated in place. (#509)
- **A slide's live preview is no longer taken from another slide's compose file** (slug
  `intro` took `intro_2`'s), and writing one slide's compose on the AWS stack no longer
  deletes another's. (#494)
- **The API Lambda no longer leaves template copies in `/tmp`.** (#491)
- **Local Web UI no longer opens the deck folder as a deck** when a new chat starts, and no
  longer sends a `PATCH` the local server does not have. (#480)
- **Local Web UI reopens a deck without "Sorry, something went wrong".** A reopened deck
  reuses its live agent process; a second prompt to a busy chat or a session held by
  another kiro-cli gets a translated message. (#487)
- **Local Web UI frees a deck's agent process when its turn ends**, so the limit of three
  processes stops the oldest idle one. (#490)
- **Cloud `read_attachment` works again** (it failed on every call since 2026-10-08), and
  Cloud `import_attachment` reports the actual conversion error. (#483, #495)
- **Live previews keep cut-outs in icons and shapes.** Local and remote share one compose
  module (`sdpm.engine.preview.compose`). (#485)
- **Previews no longer add a shadow to shapes and lines on light templates.** An element
  has a shadow only when its JSON asks for one. (#486)
- **Untranslated Web UI strings** (deck page slide count, Folder button, deck list load
  error) are translated. (#488, #496)

### Security

- **The AgentCore runtimes allow only the operations the app uses.** A resource-based policy
  on the agent and MCP runtimes and their endpoints allows `InvokeAgentRuntime` and
  `StopRuntimeSession`, plus `InvokeAgentRuntimeWithWebSocketStream` on the agent runtime,
  and denies `InvokeAgentRuntimeCommand`. (#501, #510)
- **Agent and MCP runtime sessions are bound to their owner.** New session ids carry a
  prefix derived from the signed-in user (`shared/session_owner.py`), the agent and the MCP
  server admit such an id only for that user, and each runtime process serves one user. On
  `/ws` the agent checks the owner on every message. Earlier ids are admitted when Memory
  holds the user's history for them. Local mode is unchanged. (#506, #510)
- **Narrower execution roles.** The agent role loses deck storage access, is limited to its
  own Memory and image repository, and denies user-id delegation and calls through
  AWS-managed MCP servers. Both runtime roles trust AgentCore only for the deploying
  account and Region; the MCP role drops unused permissions; the API Lambda's `ListEvents`
  is limited to the agent's Memory. (#499)
- **The agent's AWS knowledge tools are limited to documentation tools**
  (`aws___search_documentation`, `aws___read_documentation`, `aws___retrieve_skill`,
  `aws___list_regions`, `aws___get_regional_availability`) on the public AWS Knowledge MCP
  Server. The `mcp-proxy-for-aws` dependency is removed. (#499)
- **The agent accepts `prompt` as text only**; anything else gets a `bad_input` error.
  (#499)
- **User ids stay out of agent context and other users' responses.** Cloud upload handles
  are `uploads/{uuid}/{name}`, and the MCP server builds the S3 key from the signed-in
  caller. The earlier form is accepted for the caller's own uploads until the first minor
  release 90 days after this one. Deck lists no longer return `createdBy`, `GET /decks/{id}`
  returns `chatSessionId` to the owner only, and `run_style_python` no longer returns the
  S3 key. (#495)
- **Composers see only their deck tools**, as the orchestrator already did. (#495)
- **Local Web UI refuses cross-site POSTs.** Every POST route of the local server answers
  403 when the browser's `Origin` is another site; requests without `Origin` (scripts,
  curl) are unaffected. (#473)
- **Model request and response bodies are no longer written to the runtime logs, and the
  runtime log groups expire.** Both runtimes set
  `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false`; token counts and the
  [usage measurement](docs/en/usage-measurement.md) events are unchanged. The runtime log
  groups get the retention in `observability.logRetentionDays` (default 30 days). The
  Strands tracer still records conversation text in the agent runtime log group. (#507)

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

[Unreleased]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.13.0...HEAD
[0.13.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/aws-samples/sample-spec-driven-presentation-maker/compare/v0.11.0...v0.12.0
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
