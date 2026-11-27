// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: one conversation per screen, and several Local chats at once.
 *
 * One conversation per screen (V3; the layout does not depend on the engine):
 * - The home screen is the composer at the stage; a message makes the conversation fill the
 *   first screenful, with the deck list below it.
 * - The home conversation stays when a deck is opened and the list is shown again; only the home
 *   screen's New chat clears it.
 * - A deck's sheet holds only that deck's conversation, without tabs or New chat; closed, it opens
 *   again from Chat in the deck's bar.
 * - A deck the home conversation makes keeps that conversation (the same element, still
 *   streaming), and the home screen is blank again.
 *
 * Several chats at once, on each engine: two decks are made at once from two pages, one of them
 * in a long turn: both decks appear, and their `.session` files show where the chats run (the
 * stub's session ids are `stub-<engine>-<pid>-<n>`): one stub process each, on both engines
 * (kiro-cli's V3 agent server runs one turn at a time per process, so chats do not share one).
 * Stop for a chat while its kiro-cli starts, sent alone (`POST /api/agent/stop`, as another tab
 * would): the invoke answers a stream that ends with no data, and no prompt ran (its deck is never
 * made). Runs on V3, then V2; ends on V3, the sandbox's engine.
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

/** The home composer, ready to type into: it takes the focus once the page has hydrated. */
async function homeComposer(page: Page) {
  await page.goto("/decks")
  const input = page.getByRole("textbox", { name: "Chat message input" })
  await expect(input).toBeFocused({ timeout: 30_000 })
  return input
}

async function send(page: Page, message: string) {
  await page.getByRole("textbox", { name: "Chat message input" }).fill(message)
  await page.getByRole("button", { name: "Send message" }).click()
}

/** A new chat on its own page, with `message` sent from the home composer. */
async function startChat(page: Page, message: string) {
  await (await homeComposer(page)).fill(message)
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

/** The rail's Decks item, or the logo: both go back to the list in place. */
async function backToList(page: Page, via: "rail" | "logo" = "rail") {
  const decks = page.getByRole("link", { name: "Decks", exact: true })
  await (via === "rail" ? decks.filter({ hasText: "Decks" }) : decks.filter({ hasNotText: "Decks" })).click()
  await expect(page).toHaveURL((url) => url.hash === "")
}

/** A deck with no conversation yet, under a name of its own (the stub names all of its decks alike). */
function seedDeck(deckId: string, name: string) {
  const dir = deckDir(deckId)
  fs.rmSync(dir, { recursive: true, force: true })
  fs.mkdirSync(path.join(dir, "slides"), { recursive: true }) // nosemgrep: path-join-resolve-traversal — constant deck ids in the sandbox
  fs.writeFileSync(path.join(dir, "deck.json"), JSON.stringify({ name })) // nosemgrep: path-join-resolve-traversal — constant deck ids in the sandbox
}

test.describe("one conversation per screen", () => {
  const SEEDED = { id: "e2e-single-seeded", name: "Single chat seeded deck" }
  const MADE = "e2e-v3-single-made"
  test.beforeEach(async ({ page, baseURL }) => { await useEngine(page, baseURL!, "v3") })
  test.afterAll(async ({ request, baseURL }) => {
    await request.post("/api/agent/stop", { data: {}, headers: { Origin: baseURL! } })
    for (const deckId of [SEEDED.id, MADE]) fs.rmSync(deckDir(deckId), { recursive: true, force: true })
  })

  test("the home conversation stays across a deck and back, and only New chat clears it; a deck's sheet is its own", async ({ page }) => {
    seedDeck(SEEDED.id, SEEDED.name)
    const chatLog = page.getByRole("log", { name: "Chat messages" })
    const stageTitle = page.getByRole("heading", { name: "What are we presenting?" })
    const newChat = page.getByRole("button", { name: "New chat" })

    // The stage: the composer and its title, the deck list below, no New Deck and no New chat.
    await homeComposer(page)
    await expect(stageTitle).toBeVisible()
    await expect(page.getByRole("heading", { name: "Decks" })).toBeVisible()
    await expect(page.getByRole("button", { name: "New Deck" })).toHaveCount(0)
    await expect(newChat).toHaveCount(0)

    // A message: the conversation takes the screen, New chat shows, the deck list follows below.
    await send(page, "[chat] What is 17 × 3?")
    await expect(chatLog).toContainText("51", { timeout: 15_000 })
    await expect(stageTitle).toBeHidden()
    await expect(newChat).toBeVisible()
    await expect(page.getByRole("heading", { name: "Decks" })).toBeAttached()

    // Open a deck: its sheet has only its own (empty) conversation, no tabs and no New chat.
    await page.getByText(SEEDED.name).first().click()
    await expect(page).toHaveURL(new RegExp(`#${SEEDED.id}$`))
    const sheet = page.locator("aside", { has: chatLog })
    await expect(chatLog).toBeVisible()
    await expect(chatLog).not.toContainText("What is 17 × 3?")
    await expect(newChat).toHaveCount(0)
    await expect(sheet.getByRole("tab")).toHaveCount(0)

    // Closed, the sheet opens again from Chat in the deck's bar.
    const openChat = page.getByRole("button", { name: "Open chat" })
    await expect(openChat).toHaveCount(0)
    await page.getByRole("button", { name: "Close chat panel" }).click()
    await expect(sheet).toHaveAttribute("data-open", "false")
    await openChat.click()
    await expect(sheet).toHaveAttribute("data-open", "true")
    await expect(openChat).toHaveCount(0)
    await expect(chatLog).toBeVisible()
    await expect(chatLog).not.toContainText("What is 17 × 3?")

    // Back to the list: the home conversation is still there.
    await backToList(page)
    await expect(chatLog).toContainText("What is 17 × 3?")
    await expect(chatLog).toContainText("51")

    // The logo goes back in place too: no reload, the conversation stays.
    await page.evaluate(() => { (window as unknown as { __noReload: boolean }).__noReload = true })
    await page.getByText(SEEDED.name).first().click()
    await expect(page).toHaveURL(new RegExp(`#${SEEDED.id}$`))
    await backToList(page, "logo")
    expect(await page.evaluate(() => (window as unknown as { __noReload?: boolean }).__noReload)).toBe(true)
    await expect(chatLog).toContainText("What is 17 × 3?")

    // New chat clears it: the stage again.
    await newChat.click()
    await expect(stageTitle).toBeVisible()
    await expect(page.getByText("What is 17 × 3?")).toHaveCount(0)
    await expect(newChat).toHaveCount(0)
  })

  test("a deck the home conversation makes keeps that conversation, and the home screen is blank again", async ({ page }) => {
    const prompt = `[slow=10] deck=${MADE.replace("e2e-v3-", "")}`
    const chatLog = page.getByRole("log", { name: "Chat messages" })
    await startChat(page, prompt)
    // Mark the conversation's element: the deck's sheet must show this same one, not a new mount.
    await chatLog.evaluate((el) => { el.setAttribute("data-e2e-home-chat", "") })

    await expect(page).toHaveURL(new RegExp(`#${MADE}$`), { timeout: 15_000 })
    await expect(chatLog).toHaveAttribute("data-e2e-home-chat", "")
    // Still streaming the same turn, the prompt shown once.
    await expect(chatLog).toContainText(" 10", { timeout: 30_000 })
    await expect(chatLog.getByText(prompt, { exact: true })).toHaveCount(1)
    await expect(page.getByRole("button", { name: "Stop generation" })).toHaveCount(0, { timeout: 15_000 })
    await expect(chatLog).toHaveAttribute("data-e2e-home-chat", "")

    // The home screen is blank again.
    await backToList(page)
    await expect(page.getByRole("heading", { name: "What are we presenting?" })).toBeVisible()
    await expect(page.getByRole("textbox", { name: "Chat message input" })).toHaveValue("")
    await expect(page.getByText(prompt, { exact: true })).toHaveCount(0)
  })
})

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
