// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: a reopened deck follows its chat's work, on each agent engine.
 *
 * A deck is made from New Deck in a slow turn (`[slow=<n>]`), and its tab is closed once the deck
 * opens. When the turn ended while no tab was open, opening the deck again shows the prompt once
 * and the whole reply, with no Stop button; a reload shows the same (the server has nothing
 * running, and the history comes from `.chat.json`). When the turn still runs, the reopened deck
 * follows it: the reply grows, the Stop button shows, and Stop ends it. The stub writes
 * `.stub-prompt-done` into the deck when a slow turn answers. Runs on V3, then V2; ends on V3,
 * the sandbox's engine, without its decks.
 */
import fs from "fs"
import path from "path"
import { test, expect, type BrowserContext, type Page } from "@playwright/test"

const DECKS = path.resolve(__dirname, ".tmp", "decks")
const deckDir = (deckId: string) => path.join(DECKS, deckId) // nosemgrep: path-join-resolve-traversal — constant deck ids in the sandbox

async function useEngine(page: Page, baseURL: string, engine: "v2" | "v3") {
  const switched = await page.request.put("/api/agent/engine", { data: { engine }, headers: { Origin: baseURL } })
  expect(switched.status()).toBe(200)
}

/** Send `message` from New Deck on a new page, and wait until its deck opens. */
async function startDeck(context: BrowserContext, message: string, deckId: string): Promise<Page> {
  const page = await context.newPage()
  await page.goto("/decks")
  await page.getByRole("button", { name: "New Deck" }).click()
  await page.getByRole("textbox", { name: "Chat message input" }).fill(message)
  await page.getByRole("button", { name: "Send message" }).click()
  await expect(page.getByRole("log", { name: "Chat messages" })).toContainText("Creating your deck", { timeout: 15_000 })
  await expect(page).toHaveURL(new RegExp(`#${deckId}$`), { timeout: 15_000 })
  return page
}

for (const engine of ["v3", "v2"] as const) {
  test.describe(`reopening a deck (${engine})`, () => {
    test.beforeEach(async ({ page, baseURL }) => { await useEngine(page, baseURL!, engine) })
    test.afterAll(async ({ request, baseURL }) => {
      await request.post("/api/agent/stop", { data: {}, headers: { Origin: baseURL! } })
      if (engine === "v2") await request.put("/api/agent/engine", { data: { engine: "v3" }, headers: { Origin: baseURL! } })
      // The stub names every deck of an engine alike: later specs pick theirs from the list by name.
      for (const slug of ["reopen-closed", "reopen-live"]) fs.rmSync(deckDir(`e2e-${engine}-${slug}`), { recursive: true, force: true })
    })

    test("a reply that finished while the tab was closed shows on reopen", async ({ context }) => {
      const deckId = `e2e-${engine}-reopen-closed`
      const prompt = "[slow=10] deck=reopen-closed"
      const done = path.join(deckDir(deckId), ".stub-prompt-done") // nosemgrep: path-join-resolve-traversal — constant deck ids in the sandbox
      fs.rmSync(done, { force: true })
      const first = await startDeck(context, prompt, deckId)
      await first.close()
      await expect.poll(() => fs.existsSync(done), { timeout: 15_000 }).toBe(true)

      const page = await context.newPage()
      await page.goto(`/decks/#${deckId}`)
      const expectReply = async () => {
        const chatLog = page.getByRole("log", { name: "Chat messages" })
        await expect(chatLog).toContainText("Done! Your deck is ready.", { timeout: 30_000 })
        await expect(chatLog).toContainText(" 10")
        await expect(chatLog.getByText(prompt, { exact: true })).toHaveCount(1)
        await expect(page.getByRole("button", { name: "Stop generation" })).toHaveCount(0)
      }
      await expectReply()
      await page.reload()
      await expectReply()
      await page.close()
    })

    test("a reopened deck follows the running turn and Stop ends it", async ({ context }) => {
      const deckId = `e2e-${engine}-reopen-live`
      const first = await startDeck(context, "[slow] deck=reopen-live", deckId)
      await first.close()

      const page = await context.newPage()
      await page.goto(`/decks/#${deckId}`)
      const chatLog = page.getByRole("log", { name: "Chat messages" })
      await expect(chatLog).toContainText("Done! Your deck is ready.", { timeout: 30_000 })
      const stop = page.getByRole("button", { name: "Stop generation" })
      await expect(stop).toBeVisible({ timeout: 15_000 })
      await expect(chatLog).toContainText(" 5", { timeout: 15_000 })
      await stop.click()
      await expect(stop).toHaveCount(0, { timeout: 5_000 })
      await expect(chatLog).toContainText("Done! Your deck is ready.")
      await page.close()
    })
  })
}
