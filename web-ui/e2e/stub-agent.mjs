// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E stub ACP agent — stands in for kiro-cli in Playwright tests.
 *
 * Speaks just enough of the Agent Client Protocol (JSON-RPC over stdio)
 * for acp-process.ts: initialize, session/new, session/load, session/prompt.
 * On prompt it writes a deck to SDPM_DECK_ROOT (deck.json + slide JSON +
 * preview PNG), then emits the same session/update sequence a real agent
 * produces: text chunk → tool_call → tool_call_update(completed with deckId)
 * → text chunk → end_turn.
 */
import fs from "node:fs"
import path from "node:path"
import readline from "node:readline"

const DECK_ROOT = process.env.SDPM_DECK_ROOT
const DECK_ID = process.env.SDPM_STUB_DECK_ID || "e2e-test-deck"
const SESSION_ID = "stub-session-1"

// 1x1 transparent PNG
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
)

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n")
}

function update(u) {
  send({ jsonrpc: "2.0", method: "session/update", params: { sessionId: SESSION_ID, update: u } })
}

function createDeckOnDisk() {
  const dir = path.join(DECK_ROOT, DECK_ID)
  fs.mkdirSync(path.join(dir, "slides"), { recursive: true })
  fs.mkdirSync(path.join(dir, "preview"), { recursive: true })
  fs.writeFileSync(path.join(dir, "deck.json"), JSON.stringify({ name: "E2E Test Deck" }))
  fs.writeFileSync(
    path.join(dir, "slides", "intro.json"),
    JSON.stringify({ slug: "intro", elements: [] }),
  )
  fs.writeFileSync(path.join(dir, "preview", "intro.png"), PNG_1X1)
  return dir
}

function handlePrompt(msg) {
  update({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: "Creating your deck… " } })

  const outputDir = createDeckOnDisk()
  update({
    sessionUpdate: "tool_call",
    toolCallId: "stub-tool-1",
    title: "init_presentation",
    rawInput: { template: "e2e" },
  })
  update({
    sessionUpdate: "tool_call_update",
    toolCallId: "stub-tool-1",
    status: "completed",
    rawOutput: {
      items: [{ Json: { content: [{ text: JSON.stringify({ deckId: DECK_ID, output_dir: outputDir }) }] } }],
    },
  })

  update({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: "Done! Your deck is ready." } })
  send({ jsonrpc: "2.0", id: msg.id, result: { stopReason: "end_turn" } })
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
      send({ jsonrpc: "2.0", id: msg.id, result: { protocolVersion: 1, agentCapabilities: {} } })
      break
    case "session/new":
      send({ jsonrpc: "2.0", id: msg.id, result: { sessionId: SESSION_ID } })
      break
    case "session/load":
      send({ jsonrpc: "2.0", id: msg.id, result: {} })
      break
    case "session/prompt":
      handlePrompt(msg)
      break
    default:
      // notifications (session/cancel etc.) — ignore
      break
  }
})
