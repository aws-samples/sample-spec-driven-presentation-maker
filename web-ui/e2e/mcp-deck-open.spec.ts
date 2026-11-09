// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: a deck an MCP client made, opened by its direct link (`sdpm open <deck>` opens
 * `/decks/#<id>`), on each agent engine.
 *
 * The deck has deck.json and specs/ but no `.session`, as an MCP client leaves it. Its chat tab
 * opens empty; the first turn runs in a new session whose first prompt names the deck
 * (`Current deck: <dir>`, from the stub's trace) and shows no "no Kiro session" notice. The turn
 * saves `.session`, and a reload shows the conversation (it continues from then on).
 */
import fs from "fs"
import path from "path"
import { test, expect, type Page } from "@playwright/test"

const TMP = path.resolve(__dirname, ".tmp")
const DECKS = path.join(TMP, "decks")
const TRACE = path.join(TMP, "stub-trace.jsonl")
const NOTICE = "no Kiro session to continue"

interface TraceLine { sessionId: string; role: string; event: string; text?: string }

const readTrace = (): TraceLine[] => (fs.existsSync(TRACE) ? fs.readFileSync(TRACE, "utf-8").split("\n").filter(Boolean).map((l) => JSON.parse(l)) : [])

/** A deck as an MCP client leaves it: deck.json and specs/, no Web UI files. */
function seedMcpDeck(deckId: string): string {
  const dir = path.join(DECKS, deckId) // nosemgrep: path-join-resolve-traversal — constant deck ids in the sandbox
  fs.rmSync(dir, { recursive: true, force: true })
  fs.mkdirSync(path.join(dir, "specs"), { recursive: true })
  fs.mkdirSync(path.join(dir, "slides"), { recursive: true })
  fs.writeFileSync(path.join(dir, "deck.json"), JSON.stringify({ name: `MCP-made deck (${deckId})` }))
  fs.writeFileSync(path.join(dir, "specs", "brief.md"), "# Brief\n")
  fs.writeFileSync(path.join(dir, "specs", "outline.md"), "")
  return fs.realpathSync(dir)
}

async function send(page: Page, message: string) {
  await page.getByRole("textbox", { name: "Chat message input" }).fill(message)
  await page.getByRole("button", { name: "Send message" }).click()
}

for (const engine of ["v3", "v2"] as const) {
  test(`a deck made through MCP opens as a new chat on that deck, without a notice (${engine})`, async ({ page, baseURL }) => {
    const switched = await page.request.put("/api/agent/engine", { data: { engine }, headers: { Origin: baseURL! } })
    expect(switched.status()).toBe(200)
    const deckId = `e2e-mcp-deck-${engine}`
    const dir = seedMcpDeck(deckId)

    await page.goto(`/decks/#${deckId}`)
    const chatLog = page.getByRole("log", { name: "Chat messages" })
    await expect(page.getByRole("textbox", { name: "Chat message input" })).toBeVisible({ timeout: 30_000 })
    await expect(chatLog).not.toContainText("51")

    await send(page, "[chat] what is this deck?")
    await expect(chatLog).toContainText("51", { timeout: 30_000 })
    await expect(page.getByText(NOTICE)).toHaveCount(0)

    // The new session's first prompt named this deck's directory.
    const first = readTrace().findLast((l) => l.event === "prompt" && l.sessionId.startsWith(`stub-${engine}-`) && l.text?.includes("[chat] what is this deck?"))
    expect(first?.text).toContain(`Current deck: ${dir}`)

    // The turn saved the session to the deck, and a reload shows the conversation.
    await expect.poll(() => fs.existsSync(path.join(dir, ".session")), { timeout: 15_000 }).toBe(true)
    await expect.poll(async () => (await page.request.get(`/api/agent/chat?deckId=${deckId}`)).text(), { timeout: 15_000 })
      .toContain("51")
    await page.reload()
    await expect(chatLog).toContainText("what is this deck?", { timeout: 30_000 })
    await expect(chatLog).toContainText("51")
    await expect(page.getByText(NOTICE)).toHaveCount(0)

    if (engine === "v2") await page.request.put("/api/agent/engine", { data: { engine: "v3" }, headers: { Origin: baseURL! } })
  })
}
