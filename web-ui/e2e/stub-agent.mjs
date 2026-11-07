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
 * On prompt it writes a deck to SDPM_DECK_ROOT (deck.json + slide JSON + preview PNG) and
 * streams: text → an sdpm tool call and its result (with the deckId) → (V3) two delegations to
 * the composer, each with one tool of its own → text → end_turn. The deck and session ids carry
 * the engine (`e2e-<engine>-deck`, `stub-<engine>-<pid>`), so one sandbox serves both engines.
 */
import fs from "node:fs"
import path from "node:path"
import readline from "node:readline"

const ARGS = process.argv.slice(2)
const ENGINE = ARGS.includes("--agent-engine") ? ARGS[ARGS.indexOf("--agent-engine") + 1] : "v2"
const AGENT = ARGS.includes("--agent") ? ARGS[ARGS.indexOf("--agent") + 1] : ""
const DECK_ROOT = process.env.SDPM_DECK_ROOT
const DECK_ID = `e2e-${ENGINE}-deck`
const STARTED_AT = new Date(Date.now() - 60_000).toISOString()
const MODES = ["sdpm-orchestrator", "sdpm-composer", "sdpm-style", "sdpm-translate"]

/** sessionId → its current mode. */
const sessions = new Map()
let sessionCount = 0

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

/** Answer a request that opens or switches a session, with the sdpm server's readiness around it. */
function answerReady(msg, sessionId, result) {
  if (ENGINE === "v3") {
    mcpStatus(sessionId, "connecting")
    answer(msg, result)
    mcpStatus(sessionId, "connected")
  } else {
    send({ method: "_kiro.dev/mcp/server_initialized", params: { sessionId, serverName: "sdpm" } })
    answer(msg, result)
  }
}

function createDeckOnDisk() {
  const dir = path.join(DECK_ROOT, DECK_ID)
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

/** V3: a delegation to the composer, its one tool, and its end. */
function delegation(sessionId, n) {
  const toolCallId = `invoke_subagent_stub-${n}`
  const agentSubtaskId = `stub-subtask-${n}`
  const rawInput = { name: "sdpm-composer", prompt: `assigned_slugs: ["intro"]\nGroup ${n} of the stub deck.` }
  const meta = { _meta: { kiro: { kind: "agent-subtask", agentSubtaskId } } }
  update(sessionId, { sessionUpdate: "tool_call", toolCallId, title: "Sub-agent: sdpm-composer", kind: "other", status: "pending", rawInput, ...meta })
  sdpmTool(sessionId, `stub-composer-tool-${n}`, "list_templates", {}, { templates: [] }, { agentSubtaskId })
  update(sessionId, { sessionUpdate: "tool_call_update", toolCallId, title: "Sub-agent: sdpm-composer", status: "completed", rawInput, rawOutput: "done", ...meta })
}

function handlePrompt(msg) {
  const sessionId = msg.params.sessionId
  text(sessionId, "Creating your deck… ")
  const outputDir = createDeckOnDisk()
  sdpmTool(sessionId, "stub-tool-1", "init_deck_workspace", { template: "e2e" }, { deckId: DECK_ID, output_dir: outputDir })
  if (ENGINE === "v3") {
    delegation(sessionId, 1)
    delegation(sessionId, 2)
  }
  text(sessionId, "Done! Your deck is ready.")
  answer(msg, { stopReason: "end_turn" })
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
      answer(msg, { protocolVersion: 1, agentCapabilities: { loadSession: true } })
      break
    case "session/new": {
      const sessionId = `stub-${ENGINE}-${process.pid}-${++sessionCount}`
      sessions.set(sessionId, ENGINE === "v3" ? msg.params?._meta?.kiro?.modeId ?? "vibe" : AGENT)
      answerReady(msg, sessionId, { sessionId, modes: modes(sessionId) })
      break
    }
    case "session/load": {
      const sessionId = msg.params.sessionId
      if (!sessions.has(sessionId)) sessions.set(sessionId, ENGINE === "v3" ? "sdpm-orchestrator" : AGENT)
      answerReady(msg, sessionId, { modes: modes(sessionId), ...(ENGINE === "v3" ? { _meta: { createdAt: STARTED_AT } } : {}) })
      break
    }
    case "session/set_mode":
      sessions.set(msg.params.sessionId, msg.params.modeId)
      answerReady(msg, msg.params.sessionId, {})
      break
    case "session/prompt":
      handlePrompt(msg)
      break
    default:
      // Another request (a steer): Method not found, as kiro-cli answers what it does not implement.
      if (msg.id != null) send({ id: msg.id, error: { code: -32601, message: `Method not found: ${msg.method}` } })
      // notifications (session/cancel etc.) — ignore
      break
  }
})
