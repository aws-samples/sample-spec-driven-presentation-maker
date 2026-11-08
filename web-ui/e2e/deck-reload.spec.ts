// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: a deck keeps its conversation on a reload and a direct link.
 *
 * The stub agent creates a deck through the chat. Opening it from the deck list shows that
 * conversation in the deck's chat tab; so does reloading the page and opening `/decks/#<id>`
 * in a new tab (the hash is read after mount, so the first render matches the prerendered
 * page). Along the way it checks the Local wording: the search box searches decks by name,
 * and the deck header has no private / internal visibility chip (a Cloud feature).
 */
import { test, expect, type Page } from "@playwright/test"

const DECK_ID = "e2e-v3-deck"
const DECK_NAME = "E2E Test Deck (v3)"
const PROMPT = "Create a deck that survives a reload"

/** The deck's chat shows the earlier conversation. */
async function expectConversation(page: Page) {
  const chatLog = page.getByRole("log", { name: "Chat messages" })
  await expect(chatLog).toContainText(PROMPT, { timeout: 30_000 })
  await expect(chatLog).toContainText("Done! Your deck is ready.")
}

test("a deck opened from the list keeps its conversation on reload and on a direct link", async ({ page, baseURL }) => {
  const engine = await page.request.put("/api/agent/engine", { data: { engine: "v3" }, headers: { Origin: baseURL! } })
  expect(engine.status()).toBe(200)

  // A deck with a saved conversation
  await page.goto("/decks")
  await page.getByRole("button", { name: "New Deck" }).click()
  await page.getByRole("textbox", { name: "Chat message input" }).fill(PROMPT)
  await page.getByRole("button", { name: "Send message" }).click()
  await expect(page.getByRole("log", { name: "Chat messages" })).toContainText("Done! Your deck is ready.", { timeout: 30_000 })
  await expect(page).toHaveURL(new RegExp(`#${DECK_ID}$`), { timeout: 15_000 })
  // The chat is saved when the turn ends; leave the page only once it is
  await expect.poll(async () => (await page.request.get(`/api/agent/chat?deckId=${DECK_ID}`)).text(), { timeout: 15_000 })
    .toContain("Done! Your deck is ready.")

  // Open it from the list
  await page.goto("/decks")
  await expect(page.getByPlaceholder("Search decks…")).toBeVisible()
  await page.getByText(DECK_NAME).first().click()
  await expect(page).toHaveURL(new RegExp(`#${DECK_ID}$`))
  await expectConversation(page)
  // The deck header (Slides tab) has the favorite button but no visibility chip
  await page.getByRole("tab", { name: /Slides/ }).click()
  await expect(page.getByRole("button", { name: "Add to favorites" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Private" })).toHaveCount(0)

  // Reload
  await page.reload()
  await expectConversation(page)

  // Direct link in a new tab; its first render matches the prerendered page (no hydration error)
  const direct = await page.context().newPage()
  const hydrationErrors: string[] = []
  direct.on("pageerror", (err) => { if (/hydrat/i.test(err.message)) hydrationErrors.push(err.message) })
  await direct.goto(`/decks/#${DECK_ID}`)
  await expectConversation(direct)
  expect(hydrationErrors).toEqual([])
  await direct.close()
})
