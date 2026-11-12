// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: the Local chat's model and effort, on each agent engine (stub-agent.mjs's models).
 *
 * New Deck → send → the pill shows the session's model once the turn ended → choose a model
 * (and on V3 an effort) → the next message runs on it (the stub says which in its reply) → a
 * reload still shows it (the session keeps it). V2 offers no effort. Each test sets the engine
 * first: the one an earlier spec left is not known. A cross-site PUT is refused.
 */
import { test, expect, type Page } from "@playwright/test"

async function useEngine(page: Page, baseURL: string, engine: "v2" | "v3") {
  const res = await page.request.put("/api/agent/engine", { data: { engine }, headers: { Origin: baseURL } })
  expect(res.status()).toBe(200)
}

async function send(page: Page, text: string) {
  const input = page.getByRole("textbox", { name: "Chat message input" })
  await input.fill(text)
  await page.getByRole("button", { name: "Send message" }).click()
}

/** The workspace URL the stub's deck-created result navigates to (hash routing). */
const DECK_URL = { v2: /#e2e-v2-deck$/, v3: /#e2e-v3-deck$/ } as const

const pill = (page: Page) => page.getByRole("button", { name: /^Model:/ })

async function firstTurn(page: Page, engine: "v2" | "v3") {
  await page.goto("/decks")
  await page.getByRole("button", { name: "New Deck" }).click()
  await send(page, `A deck about models on ${engine}`)
  const chatLog = page.getByRole("log", { name: "Chat messages" })
  await expect(chatLog).toContainText("Done! Your deck is ready.", { timeout: 30_000 })
  await expect(page).toHaveURL(DECK_URL[engine], { timeout: 15_000 })
  return chatLog
}

test("chooses the model and effort of a V3 chat; the next message and a reload keep them", async ({ page, baseURL }) => {
  await useEngine(page, baseURL!, "v3")
  const chatLog = await firstTurn(page, "v3")
  await expect(pill(page)).toHaveText("Auto", { timeout: 15_000 })

  await pill(page).click()
  await expect(page.getByText("Applies from your next message.")).toBeVisible()
  await page.getByRole("menuitemradio", { name: /Stub Effort/ }).click()
  await expect(pill(page)).toHaveText("Stub Effort · Medium")
  await pill(page).click()
  await expect(page.getByText("Effort", { exact: true })).toBeVisible()
  await page.getByRole("menuitemradio", { name: "High" }).click()
  await expect(pill(page)).toHaveText("Stub Effort · High")

  await send(page, "One more slide, please")
  await expect(chatLog).toContainText("model: stub-effort, effort: high", { timeout: 30_000 })
  // The chat is saved when the turn ends; reload only once it is
  await expect.poll(async () => (await page.request.get("/api/agent/chat?deckId=e2e-v3-deck")).text(), { timeout: 15_000 })
    .toContain("model: stub-effort, effort: high")

  await page.reload()
  // The reloaded page reopens the deck's own chat.
  await expect(page.getByRole("log", { name: "Chat messages" })).toContainText("model: stub-effort, effort: high", { timeout: 30_000 })
  await expect(pill(page)).toHaveText("Stub Effort · High", { timeout: 15_000 })
})

test("chooses the model of a V2 chat, which offers no effort", async ({ page, baseURL }) => {
  await useEngine(page, baseURL!, "v2")
  const chatLog = await firstTurn(page, "v2")
  await expect(pill(page)).toHaveText("auto", { timeout: 15_000 })

  await pill(page).click()
  await expect(page.getByText("Applies from your next message.")).toBeVisible()
  await expect(page.getByText("Effort", { exact: true })).toHaveCount(0)
  await page.getByRole("menuitemradio", { name: "stub-plain" }).click()
  await expect(pill(page)).toHaveText("stub-plain")

  await send(page, "One more slide, please")
  await expect(chatLog).toContainText("model: stub-plain", { timeout: 30_000 })
  await useEngine(page, baseURL!, "v3")
})

test("refuses a cross-site model change", async ({ page }) => {
  const res = await page.request.put("/api/agent/models", {
    data: { sessionId: "x", model: "auto" },
    headers: { Origin: "https://evil.example" },
  })
  expect(res.status()).toBe(403)
})
