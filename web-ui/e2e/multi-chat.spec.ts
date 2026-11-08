// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: several Local chats at once, on each agent engine.
 *
 * Two decks are made at once from two pages, one of them in a long turn: both decks appear, and
 * their `.session` files show where the chats run (the stub's session ids are
 * `stub-<engine>-<pid>-<n>`): one stub process each, on both engines (kiro-cli's V3 agent server
 * runs one turn at a time per process, so chats do not share one). Stop for a chat while its kiro-cli starts, sent alone (`POST /api/agent/stop`, as
 * another tab would): the invoke answers a stream that ends with no data, and no prompt ran (its
 * deck is never made). Runs on V3, then V2; ends on V3, the sandbox's engine.
 */
import { randomUUID } from "crypto"
import fs from "fs"
import path from "path"
import { test, expect, type Page } from "@playwright/test"

const DECKS = path.resolve(__dirname, ".tmp", "decks")
const deckDir = (deckId: string) => path.join(DECKS, deckId) // nosemgrep: path-join-resolve-traversal — constant deck ids in the sandbox

async function useEngine(page: Page, baseURL: string, engine: "v2" | "v3") {
  const switched = await page.request.put("/api/agent/engine", { data: { engine }, headers: { Origin: baseURL } })
  expect(switched.status()).toBe(200)
}

/** A new chat on its own page, with `message` sent. */
async function startChat(page: Page, message: string) {
  await page.goto("/decks")
  await page.getByRole("button", { name: "New Deck" }).click()
  const input = page.getByRole("textbox", { name: "Chat message input" })
  await input.fill(message)
  await page.getByRole("button", { name: "Send message" }).click()
  await expect(page.getByRole("log", { name: "Chat messages" })).toContainText("Creating your deck", { timeout: 15_000 })
}

/** The stub process id in a deck's `.session` (`stub-<engine>-<pid>-<n>`). */
async function stubPid(deckId: string): Promise<string> {
  const file = path.join(deckDir(deckId), ".session") // nosemgrep: path-join-resolve-traversal — constant deck ids in the sandbox
  await expect.poll(() => fs.existsSync(file), { timeout: 15_000 }).toBe(true)
  const id = fs.readFileSync(file, "utf-8").trim()
  expect(id).toMatch(/^stub-v[23]-\d+-\d+$/)
  return id.split("-")[2]
}

for (const engine of ["v3", "v2"] as const) {
  test.describe(`several chats (${engine})`, () => {
    test.beforeEach(async ({ page, baseURL }) => { await useEngine(page, baseURL!, engine) })
    test.afterAll(async ({ request, baseURL }) => {
      await request.post("/api/agent/stop", { data: {}, headers: { Origin: baseURL! } })
      if (engine === "v2") await request.put("/api/agent/engine", { data: { engine: "v3" }, headers: { Origin: baseURL! } })
    })

    test("makes two decks at once, each in its own kiro-cli", async ({ context, baseURL }) => {
      const slow = await context.newPage()
      const quick = await context.newPage()
      await startChat(slow, "Make a deck deck=ma [slow]")
      await startChat(quick, "Make a deck deck=mb")
      await expect(quick.getByRole("log", { name: "Chat messages" })).toContainText("Done! Your deck is ready.", { timeout: 30_000 })
      const [a, b] = [await stubPid(`e2e-${engine}-ma`), await stubPid(`e2e-${engine}-mb`)]
      expect(a).not.toBe(b)
      // The long turn is still running in the other chat; Stop ends it.
      const stopped = await slow.request.post("/api/agent/stop", { data: {}, headers: { Origin: baseURL! } })
      expect(stopped.status()).toBe(200)
      await slow.close()
      await quick.close()
    })

    test("stops a chat while its kiro-cli starts, with POST /api/agent/stop alone", async ({ request, baseURL }) => {
      const marker = path.join(DECKS, ".stub-slow-start")
      fs.writeFileSync(marker, "")
      try {
        const sessionId = randomUUID()
        const invoked = request.post("/api/agent/invoke", {
          data: { query: "hi deck=mc", sessionId, mode: "vibe" },
          headers: { Origin: baseURL! },
          timeout: 5_000,
        })
        await new Promise((resolve) => setTimeout(resolve, 500))
        const stopped = await request.post("/api/agent/stop", { data: { sessionId }, headers: { Origin: baseURL! } })
        expect(stopped.status()).toBe(200)
        const response = await invoked
        expect(response.status()).toBe(200)
        expect(await response.text()).not.toContain("data:")
        expect(fs.existsSync(deckDir(`e2e-${engine}-mc`))).toBe(false)
      } finally {
        fs.rmSync(marker, { force: true })
      }
    })
  })
}
