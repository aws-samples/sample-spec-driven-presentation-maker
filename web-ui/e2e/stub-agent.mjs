// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E stub ACP agent — stands in for kiro-cli in Playwright tests, on either agent engine.
 *
 * It reads the engine from its own arguments, as kiro-cli does: `acp --agent-engine v3` speaks
 * V3's shapes, `acp --agent <name>` V2's (src/test/fixtures/acp has the real ones; these are the
 * same shapes, written small). Both answer initialize, session/new, session/load (with `modes`,
 * the requested mode current: V2's `--agent`, V3's `_meta.kiro.modeId`) and session/set_mode,
 * and report the sdpm MCP server ready the way the engine does: V2 with
 * `_kiro.dev/mcp/server_initialized` before its answer, V3 with `_kiro/mcp/status` connecting
 * before and connected after. A V3 load answers a `_meta.createdAt` from before the stub started
 * (an existing session).
 *
 * V3 also lists its sessions (`session/list`: one session, "E2E V3 source", in /tmp/e2e-project),
 * forks one (`session/fork` → `sess_e2e-fork-<n>` in the mode of `_meta.kiro.modeId`; its load
 * names the source in `_meta.parentSessionId`), closes and deletes any session (`session/close`,
 * `session/delete`), as kiro-cli 3.1 does, and advertises them in initialize. V2 answers them with
 * Method not found. The Local server starts one stub process per chat on either engine.
 *
 * Models: `auto` (no effort), `stub-effort` (effort low / medium / high, default medium) and
 * `stub-plain`, kept per session. V3 reports them as config options, in session/new's answer and
 * in a `config_option_update` (before session/new's answer and after a load's, as kiro-cli does),
 * and changes them with session/set_config_option (`model`, `effortLevel`); V2 answers them in
 * `models` on session/new and session/load (names are the ids) and changes the model with
 * session/set_model. The prompt's last text says which model (and effort) the session ran on.
 *
 * On prompt it writes a deck to SDPM_DECK_ROOT (deck.json + slide JSON + preview PNG) and
 * streams: text → an sdpm tool call and its result (with the deckId) → two composer groups in
 * parallel, each with one tool of its own (V3: two `agent-subtask` delegations whose tools carry
 * their `agentSubtaskId`; V2: one crew with two stages, each run in a sub-agent session that
 * `_kiro.dev/subagent/list_update` names after its stage) → text → end_turn. The deck and session
 * ids carry the engine (`e2e-<engine>-deck`, `stub-<engine>-<pid>-<n>`), so one sandbox serves
 * both engines. A prompt that contains `deck=<slug>` names its deck `e2e-<engine>-<slug>` instead.
 * A prompt that contains `[slow]` then streams a text chunk every 200 ms for up to 30 s
 * (`[slow=<n>]`: n chunks), and answers `cancelled` when its session is cancelled (else end_turn);
 * other sessions' prompts run meanwhile. When a slow prompt answers, the stub writes
 * `<deck dir>/.stub-prompt-done`, so a test sees the turn end while no tab is open. While
 * `<SDPM_DECK_ROOT>/.stub-slow-start` exists, session/new answers after 3 s.
 *
 * Compose in the background (the Local server runs the composers, compose-run.ts):
 * - A process started for `sdpm-composer` (V2 `--agent sdpm-composer`) or a session opened in that
 *   mode (V3 `modeId`) is a composer. Its prompt (`deck_id:` path, `assigned_slugs:`) gets two sdpm
 *   tool calls, then `slides/<slug>.json` is written every 500 ms until the `[hold=<ms>]` of the
 *   instruction (default 3000) has passed, or the session is cancelled (`cancelled`); then
 *   `output.pptx` is touched (not with `[stale]`) and the prompt ends `end_turn`. A
 *   `_session/steer` to a running composer answers `{queued: true}` (V3 with a messageId), is
 *   injected at its next step (V3 `steering_injected`, V2 `AgentExecutionSteeringInjected`) and
 *   lands in every slide file's `messages`, as messages in its prompt do.
 * - The orchestrator: `[compose]` (one group) or `[groups N]` makes the deck and calls
 *   `compose_slides`, whose result is the dispatched shape (groups `s1`…`sN`, the prompt's
 *   `[hold=…]` and `[stale]` copied into each instruction), then ends its turn; `[message N]` calls
 *   `message_composer(N, "Use the title 'Steered title'.")`; `[chat]` answers "51"; a prompt with a
 *   `<compose_result>` answers "Report seen: <status>." and, for `"build": "stale"`, calls
 *   `generate_pptx` and touches the deck's `output.pptx`. Without a tag, the turn is as above.
 * - Every process appends `{pid, sessionId, role, event: "prompt" | "answer", wake, text, t}` to
 *   `SDPM_STUB_TRACE` when it is set (`text`: the prompt's first 200 characters).
 */
import fs from "node:fs"
import path from "node:path"
import readline from "node:readline"

const ARGS = process.argv.slice(2)
const ENGINE = ARGS.includes("--agent-engine") ? ARGS[ARGS.indexOf("--agent-engine") + 1] : "v2"
const AGENT = ARGS.includes("--agent") ? ARGS[ARGS.indexOf("--agent") + 1] : ""
const DECK_ROOT = process.env.SDPM_DECK_ROOT
const DEFAULT_DECK_ID = `e2e-${ENGINE}-deck`
const STARTED_AT = new Date(Date.now() - 60_000).toISOString()
const MODES = ["sdpm-orchestrator", "sdpm-composer", "sdpm-style", "sdpm-translate"]

/** sessionId → its current mode. */
const sessions = new Map()
/** sessionId → its model and effort. */
const sessionModels = new Map()
let sessionCount = 0
/** sessionId → how to end its running `[slow]` prompt (on session/cancel). */
const slowPrompts = new Map()
/** sessionId → its running composer turn: `cancel()` and `steer({text, messageId})`. */
const composerTurns = new Map()
/** sessionId → the deck and slugs of its composer prompt (a follow-up prompt names none). */
const composerWork = new Map()
/** The deck the orchestrator's last compose_slides named. */
let lastComposeDeck = null
let callCount = 0
let steerCount = 0
const STUB_TRACE = process.env.SDPM_STUB_TRACE
const MESSAGE_PREFIX = "Message from the orchestrator while you work: "

function trace(sessionId, role, event, extra = {}) {
  if (STUB_TRACE) fs.appendFileSync(STUB_TRACE, JSON.stringify({ pid: process.pid, sessionId, role, event, t: Date.now(), ...extra }) + "\n")
}

function isComposer(sessionId) {
  return ENGINE === "v3" ? sessions.get(sessionId) === "sdpm-composer" : AGENT === "sdpm-composer"
}

/** V3 fork id → its source. */
const forks = new Map()
const V3_SOURCE = { sessionId: "sess_e2e-v3-source", cwd: "/tmp/e2e-project", title: "E2E V3 source" }

const MODELS = [
  { value: "auto", name: "Auto", _meta: { kiro: { rateMultiplier: 1, hasEffort: false } } },
  { value: "stub-effort", name: "Stub Effort", _meta: { kiro: { rateMultiplier: 2, hasEffort: true, effortLevels: ["low", "medium", "high"], defaultEffortLevel: "medium" } } },
  { value: "stub-plain", name: "Stub Plain", _meta: { kiro: { hasEffort: false } } },
]

function modelOf(sessionId) {
  if (!sessionModels.has(sessionId)) sessionModels.set(sessionId, { model: "auto", effort: null })
  return sessionModels.get(sessionId)
}

function setModel(sessionId, model) {
  const effort = MODELS.find((m) => m.value === model)?._meta.kiro.defaultEffortLevel ?? null
  sessionModels.set(sessionId, { model, effort })
}

/** V3: the session's mode, model and (for a model with effort) effort options. */
function configOptions(sessionId) {
  const { model, effort } = modelOf(sessionId)
  const options = [
    { type: "select", id: "mode", name: "Mode", category: "mode", currentValue: sessions.get(sessionId), options: MODES.map((value) => ({ value, name: value })) },
    { type: "select", id: "model", name: "Model", category: "model", currentValue: model, options: MODELS },
  ]
  const levels = MODELS.find((m) => m.value === model)?._meta.kiro.effortLevels
  if (levels) options.push({ type: "select", id: "effortLevel", name: "Effort", category: "thought_level", currentValue: effort, options: levels.map((value) => ({ value, name: value })) })
  return options
}

function configUpdate(sessionId) {
  update(sessionId, { sessionUpdate: "config_option_update", configOptions: configOptions(sessionId) })
}

/** V2: the models as session/new and session/load answer them. */
function v2Models(sessionId) {
  return { currentModelId: modelOf(sessionId).model, availableModels: MODELS.map((m) => ({ modelId: m.value, name: m.value })) }
}

// 1x1 transparent PNG
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
)

function send(obj) {
  process.stdout.write(JSON.stringify({ jsonrpc: "2.0", ...obj }) + "\n")
}

function answer(msg, result) {
  send({ id: msg.id, result })
}

function update(sessionId, u) {
  send({ method: "session/update", params: { sessionId, update: u } })
}

function modes(sessionId) {
  return { currentModeId: sessions.get(sessionId), availableModes: MODES.map((id) => ({ id, name: id })) }
}

/** V3: one full snapshot of the session's MCP servers. */
function mcpStatus(sessionId, status) {
  send({ method: "_kiro/mcp/status", params: { sessionId, servers: [{ name: "sdpm", status }] } })
}

/**
 * Answer a request that opens or switches a session, with the sdpm server's readiness around it
 * (V3: `before` / `after` the answer, while the server connects).
 */
function answerReady(msg, sessionId, result, { before = () => {}, after = () => {} } = {}) {
  if (ENGINE === "v3") {
    mcpStatus(sessionId, "connecting")
    before()
    answer(msg, result)
    after()
    mcpStatus(sessionId, "connected")
  } else {
    send({ method: "_kiro.dev/mcp/server_initialized", params: { sessionId, serverName: "sdpm" } })
    answer(msg, result)
  }
}

/** The deck a prompt names (`deck=<slug>`), else the default one. */
function deckIdOf(promptText) {
  const named = /deck=([a-z0-9-]+)/.exec(promptText)
  return named ? `e2e-${ENGINE}-${named[1]}` : DEFAULT_DECK_ID
}

function createDeckOnDisk(deckId) {
  const dir = path.join(DECK_ROOT, deckId)
  fs.mkdirSync(path.join(dir, "slides"), { recursive: true })
  fs.mkdirSync(path.join(dir, "preview"), { recursive: true })
  fs.writeFileSync(path.join(dir, "deck.json"), JSON.stringify({ name: `E2E Test Deck (${ENGINE})` }))
  fs.writeFileSync(
    path.join(dir, "slides", "intro.json"),
    JSON.stringify({ slug: "intro", elements: [] }),
  )
  fs.writeFileSync(path.join(dir, "preview", "intro.png"), PNG_1X1)
  return dir
}

function text(sessionId, t) {
  update(sessionId, { sessionUpdate: "agent_message_chunk", content: { type: "text", text: t } })
}

/** The two composer groups of a deck: their slugs, in the orchestrator's delegation template. */
function groupsOf(deckId) {
  return [
    { name: "intro", prompt: `deck_id: ${deckId}\nassigned_slugs: ["intro"]\nmode: pptx` },
    { name: "outro", prompt: `deck_id: ${deckId}\nassigned_slugs: ["outro"]\nmode: pptx` },
  ]
}

/** An sdpm tool call that completes with `result`, in the engine's shape. */
function sdpmTool(sessionId, toolCallId, tool, input, result, extraMeta = {}) {
  if (ENGINE === "v3") {
    const meta = { _meta: { kiro: { serverName: "sdpm", toolOrigin: "default", ...extraMeta } } }
    const rawInput = { tool_id: `sdpm::${tool}`, arguments: input }
    update(sessionId, { sessionUpdate: "tool_call", toolCallId, title: `@sdpm/${tool}`, kind: "other", status: "pending", rawInput, ...meta })
    update(sessionId, { sessionUpdate: "tool_call_update", toolCallId, status: "completed", title: `@sdpm/${tool}`, rawInput, rawOutput: { response: JSON.stringify(result) }, ...meta })
  } else {
    update(sessionId, { sessionUpdate: "tool_call", toolCallId, title: `Running: @sdpm/${tool}`, rawInput: input, _meta: { kiro: { toolName: tool, mcpServerName: "sdpm" } } })
    update(sessionId, {
      sessionUpdate: "tool_call_update", toolCallId, status: "completed",
      rawOutput: { items: [{ Json: { content: [{ text: JSON.stringify(result) }] } }] },
    })
  }
}

/** V3: one delegation to the composer per group, in parallel: all calls, then each one's tool, then their ends. */
function delegationsV3(sessionId, deckId) {
  const delegations = groupsOf(deckId).map((group, i) => ({
    toolCallId: `invoke_subagent_stub-${i + 1}`,
    agentSubtaskId: `stub-subtask-${i + 1}`,
    rawInput: { name: "sdpm-composer", prompt: group.prompt },
  }))
  const call = (d, extra) => ({ toolCallId: d.toolCallId, title: "Sub-agent: sdpm-composer", kind: "other", rawInput: d.rawInput, _meta: { kiro: { kind: "agent-subtask", agentSubtaskId: d.agentSubtaskId } }, ...extra })
  for (const d of delegations) update(sessionId, { sessionUpdate: "tool_call", ...call(d, { status: "pending" }) })
  delegations.forEach((d, i) => sdpmTool(sessionId, `stub-composer-tool-${i + 1}`, "list_templates", {}, { templates: [] }, { agentSubtaskId: d.agentSubtaskId }))
  for (const d of delegations) update(sessionId, { sessionUpdate: "tool_call_update", ...call(d, { status: "completed", rawOutput: "done" }) })
}

/** V2: the subagent list, as the full list kiro-cli sends each time. */
function subagentList(children, status) {
  send({ method: "_kiro.dev/subagent/list_update", params: {
    subagents: children.map((child) => ({ sessionId: child.sessionId, sessionName: child.name, agentName: "sdpm-composer", status: { type: status } })),
    pendingStages: [],
  } })
}

/** V2: one crew with a stage per group; each stage runs in its own sub-agent session, then the crew completes. */
function crewV2(sessionId, deckId) {
  const GROUPS = groupsOf(deckId)
  const toolCallId = "stub-crew-1"
  send({ method: "_kiro.dev/session/update", params: { sessionId, update: { sessionUpdate: "tool_call_chunk", toolCallId, title: "subagent", kind: "other" } } })
  update(sessionId, {
    sessionUpdate: "tool_call", toolCallId, title: "Spawning agent crew",
    rawInput: { mode: "blocking", task: "Compose the stub deck", stages: GROUPS.map((g) => ({ name: g.name, role: "sdpm-composer", prompt_template: g.prompt })) },
    _meta: { kiro: { toolName: "subagent" } },
  })
  const children = GROUPS.map((g, i) => ({ name: g.name, sessionId: `${sessionId}-composer-${i + 1}` }))
  subagentList(children, "working")
  children.forEach((child, i) => sdpmTool(child.sessionId, `stub-composer-tool-${i + 1}`, "list_templates", {}, { templates: [] }))
  subagentList(children, "terminated")
  subagentList([], "terminated")
  update(sessionId, { sessionUpdate: "tool_call_update", toolCallId, status: "completed", title: "Spawning agent crew" })
}

/** A composer's prompt (see the header). */
function composerPrompt(sessionId, promptText, done) {
  const deckLine = /^deck_id:\s*(.+)$/m.exec(promptText)
  const slugLine = /^assigned_slugs:\s*(.+)$/m.exec(promptText)
  const work = deckLine
    ? { deckDir: deckLine[1].trim(), slugs: (slugLine?.[1] ?? "").split(",").map((slug) => slug.trim()).filter(Boolean) }
    : composerWork.get(sessionId) ?? { deckDir: null, slugs: [] }
  composerWork.set(sessionId, work)
  const hold = deckLine ? Number(/\[hold=(\d+)\]/.exec(promptText)?.[1] ?? 3000) : 500
  const stale = promptText.includes("[stale]")
  const messages = promptText.split("\n").filter((line) => line.startsWith(MESSAGE_PREFIX))
  const pending = []
  let step = 0
  sdpmTool(sessionId, `stub-composer-${process.pid}-${++callCount}`, "start_composing", { deck_id: work.deckDir, assigned_slugs: work.slugs }, { specs_ok: true })
  sdpmTool(sessionId, `stub-composer-${process.pid}-${++callCount}`, "read_guides", {}, { guides: [] })
  const write = () => {
    if (!work.deckDir) return
    for (const slug of work.slugs) {
      fs.mkdirSync(path.join(work.deckDir, "slides"), { recursive: true })
      fs.writeFileSync(path.join(work.deckDir, "slides", `${slug}.json`), JSON.stringify({ slug, step, messages }))
    }
  }
  write()
  const started = Date.now()
  const finish = (stopReason) => {
    clearInterval(timer)
    composerTurns.delete(sessionId)
    if (stopReason === "end_turn" && !stale && work.deckDir) fs.writeFileSync(path.join(work.deckDir, "output.pptx"), `stub ${Date.now()}`)
    text(sessionId, `Composed ${work.slugs.join(", ")}.`)
    done(stopReason)
  }
  const timer = setInterval(() => {
    step++
    for (const steer of pending.splice(0)) {
      messages.push(steer.text)
      if (ENGINE === "v3") update(sessionId, { sessionUpdate: "session_info_update", _meta: { kiro: { kind: "steering_injected", messageId: steer.messageId, content: steer.text } } })
      else send({ method: "_kiro.dev/session/update", params: { sessionId, update: { sessionUpdate: "AgentExecutionSteeringInjected", content: steer.text } } })
    }
    write()
    if (Date.now() - started >= hold) finish("end_turn")
  }, 500)
  composerTurns.set(sessionId, { cancel: () => finish("cancelled"), steer: (steer) => pending.push(steer) })
}

/** The orchestrator's tags (see the header); false when the prompt has none. */
function orchestratorPrompt(sessionId, promptText, done) {
  const report = /<compose_result task="[^"]*" status="([a-z]+)">/.exec(promptText)
  const groups = /\[groups (\d+)\]/.exec(promptText) ? Number(/\[groups (\d+)\]/.exec(promptText)[1]) : promptText.includes("[compose]") ? 1 : 0
  const message = /\[message (\d+)\]/.exec(promptText)
  const chat = promptText.includes("[chat]")
  if (!report && !groups && !message && !chat) return false
  if (report) {
    text(sessionId, `Report seen: ${report[1]}. `)
    if (/&quot;build&quot;|"build": ?"stale"/.test(promptText) && lastComposeDeck) {
      sdpmTool(sessionId, `stub-build-${process.pid}-${++callCount}`, "generate_pptx", { deck_id: lastComposeDeck }, { output_path: path.join(lastComposeDeck, "output.pptx") })
      fs.writeFileSync(path.join(lastComposeDeck, "output.pptx"), `stub rebuilt ${Date.now()}`)
    }
  }
  if (groups) {
    const deckId = deckIdOf(promptText)
    const outputDir = createDeckOnDisk(deckId)
    const deckDir = fs.realpathSync(outputDir)
    lastComposeDeck = deckDir
    text(sessionId, "Composing in the background… ")
    sdpmTool(sessionId, `stub-tool-${process.pid}-${++callCount}`, "init_deck_workspace", { template: "e2e" }, { deckId, output_dir: outputDir })
    const tags = (promptText.match(/\[hold=\d+\]|\[stale\]/g) ?? []).join(" ")
    const slideGroups = Array.from({ length: groups }, (_, i) => ({ slugs: [`s${i + 1}`], instruction: `Compose s${i + 1}. ${tags}`.trim() }))
    const taskId = Array.from({ length: 12 }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join("")
    sdpmTool(sessionId, `stub-compose-${process.pid}-${++callCount}`, "compose_slides", { deck_id: deckDir, slide_groups: slideGroups }, {
      status: "dispatched", task_id: taskId, deck_id: deckDir, output_format: "pptx",
      slide_groups: slideGroups.map((g, i) => ({ group: i + 1, ...g })), outline_slugs: slideGroups.flatMap((g) => g.slugs),
      notice: `Running in the background.\nTask ID: ${taskId}`,
    })
    text(sessionId, "The composers are on it.")
  }
  if (message) {
    const group = Number(message[1])
    sdpmTool(sessionId, `stub-message-${process.pid}-${++callCount}`, "message_composer", { group, text: "Use the title 'Steered title'." }, `Sent to composer ${group}; it reads the message at its next step.`)
    text(sessionId, `Told composer ${group}.`)
  }
  if (chat) text(sessionId, "51")
  done("end_turn")
  return true
}

function handlePrompt(msg) {
  const sessionId = msg.params.sessionId
  const promptText = (msg.params.prompt ?? []).map((block) => block?.text ?? "").join("")
  const role = isComposer(sessionId) ? "composer" : "orchestrator"
  trace(sessionId, role, "prompt", { wake: promptText.startsWith("<compose_result"), text: promptText.slice(0, 200) })
  const done = (stopReason) => {
    trace(sessionId, role, "answer", { stopReason })
    answer(msg, { stopReason })
  }
  if (role === "composer") {
    composerPrompt(sessionId, promptText, done)
    return
  }
  if (orchestratorPrompt(sessionId, promptText, done)) return
  const deckId = deckIdOf(promptText)
  text(sessionId, "Creating your deck… ")
  const outputDir = createDeckOnDisk(deckId)
  sdpmTool(sessionId, "stub-tool-1", "init_deck_workspace", { template: "e2e" }, { deckId, output_dir: outputDir })
  if (ENGINE === "v3") delegationsV3(sessionId, deckId)
  else crewV2(sessionId, deckId)
  text(sessionId, "Done! Your deck is ready.")
  const { model, effort } = modelOf(sessionId)
  text(sessionId, ` (model: ${model}${ENGINE === "v3" && effort ? `, effort: ${effort}` : ""})`)
  const slow = /\[slow(?:=(\d+))?\]/.exec(promptText)
  if (!slow) {
    done("end_turn")
    return
  }
  // A long turn: a chunk every 200 ms, until it is cancelled or its chunks are sent.
  const limit = Number(slow[1] ?? 150)
  let chunks = 0
  const finish = (stopReason) => {
    clearInterval(timer)
    slowPrompts.delete(sessionId)
    fs.writeFileSync(path.join(outputDir, ".stub-prompt-done"), stopReason)
    done(stopReason)
  }
  const timer = setInterval(() => {
    text(sessionId, ` ${++chunks}`)
    if (chunks >= limit) finish("end_turn")
  }, 200)
  slowPrompts.set(sessionId, () => finish("cancelled"))
}

/** Answer `msg` once the slow-start marker is gone, or 3 s after it was seen. */
function afterSlowStart(answerNow) {
  if (!DECK_ROOT || !fs.existsSync(path.join(DECK_ROOT, ".stub-slow-start"))) {
    answerNow()
    return
  }
  setTimeout(answerNow, 3000)
}

function methodNotFound(msg) {
  if (msg.id != null) send({ id: msg.id, error: { code: -32601, message: `Method not found: ${msg.method}` } })
}

const rl = readline.createInterface({ input: process.stdin })
rl.on("line", (line) => {
  let msg
  try {
    msg = JSON.parse(line)
  } catch {
    return
  }
  switch (msg.method) {
    case "initialize":
      answer(msg, { protocolVersion: 1, agentCapabilities: {
        loadSession: true,
        ...(ENGINE === "v3" ? { sessionCapabilities: { list: {}, close: {}, fork: {}, delete: {} } } : {}),
      } })
      break
    case "session/list":
      if (ENGINE !== "v3") { methodNotFound(msg); break }
      answer(msg, { sessions: [{ ...V3_SOURCE, updatedAt: new Date().toISOString(), _meta: { kiro: { agentMode: "vibe", status: "idle" } } }] })
      break
    case "session/fork": {
      if (ENGINE !== "v3") { methodNotFound(msg); break }
      const sessionId = `sess_e2e-fork-${process.pid}-${forks.size + 1}`
      forks.set(sessionId, msg.params.sessionId)
      sessions.set(sessionId, msg.params?._meta?.kiro?.modeId ?? "vibe")
      answer(msg, { sessionId })
      break
    }
    case "session/close":
    case "session/delete":
      if (ENGINE !== "v3") { methodNotFound(msg); break }
      forks.delete(msg.params.sessionId)
      sessions.delete(msg.params.sessionId)
      sessionModels.delete(msg.params.sessionId)
      answer(msg, {})
      break
    case "session/new": {
      const sessionId = `stub-${ENGINE}-${process.pid}-${++sessionCount}`
      sessions.set(sessionId, ENGINE === "v3" ? msg.params?._meta?.kiro?.modeId ?? "vibe" : AGENT)
      afterSlowStart(() => {
        if (ENGINE === "v3") answerReady(msg, sessionId, { sessionId, modes: modes(sessionId), configOptions: configOptions(sessionId) }, { before: () => configUpdate(sessionId) })
        else answerReady(msg, sessionId, { sessionId, modes: modes(sessionId), models: v2Models(sessionId) })
      })
      break
    }
    case "session/load": {
      const sessionId = msg.params.sessionId
      if (!sessions.has(sessionId)) sessions.set(sessionId, ENGINE === "v3" ? "sdpm-orchestrator" : AGENT)
      const parent = forks.has(sessionId) ? { parentSessionId: forks.get(sessionId) } : {}
      if (ENGINE === "v3") answerReady(msg, sessionId, { modes: modes(sessionId), _meta: { createdAt: STARTED_AT, ...parent } }, { after: () => configUpdate(sessionId) })
      else answerReady(msg, sessionId, { modes: modes(sessionId), models: v2Models(sessionId) })
      break
    }
    case "session/set_config_option": {
      const { sessionId, configId, value } = msg.params
      if (ENGINE !== "v3") {
        send({ id: msg.id, error: { code: -32601, message: `Method not found: ${msg.method}` } })
        break
      }
      if (configId === "model") setModel(sessionId, value)
      else if (configId === "effortLevel") modelOf(sessionId).effort = value
      configUpdate(sessionId)
      answer(msg, { configOptions: configOptions(sessionId) })
      break
    }
    case "session/set_model":
      if (ENGINE !== "v2") {
        send({ id: msg.id, error: { code: -32601, message: `Method not found: ${msg.method}` } })
        break
      }
      setModel(msg.params.sessionId, msg.params.modelId)
      answer(msg, {})
      break
    case "session/set_mode":
      sessions.set(msg.params.sessionId, msg.params.modeId)
      answerReady(msg, msg.params.sessionId, {})
      break
    case "session/prompt":
      handlePrompt(msg)
      break
    case "session/cancel":
      slowPrompts.get(msg.params?.sessionId)?.()
      composerTurns.get(msg.params?.sessionId)?.cancel()
      break
    case "_session/steer": {
      const turn = composerTurns.get(msg.params?.sessionId)
      if (!turn) { methodNotFound(msg); break }
      const messageId = `steer-${process.pid}-${++steerCount}`
      turn.steer({ text: msg.params.message, messageId })
      answer(msg, ENGINE === "v3" ? { queued: true, messageId } : { queued: true })
      break
    }
    case "_session/steer/clear":
      if (isComposer(msg.params?.sessionId)) answer(msg, {})
      else methodNotFound(msg)
      break
    default:
      // Another request (a steer): Method not found, as kiro-cli answers what it does not implement.
      // Other notifications are ignored.
      methodNotFound(msg)
      break
  }
})
