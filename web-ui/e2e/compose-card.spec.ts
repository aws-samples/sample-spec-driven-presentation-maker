// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: the Compose card on each agent engine.
 *
 * The stub agent composes the deck with two composer groups in parallel (V3: two delegations;
 * V2: one crew with two stages and its sub-agent sessions). The chat shows one Compose card with
 * both groups and their slugs; both finish and the card closes as composed, not failed. Each
 * test picks its engine through PUT /api/agent/engine, as Settings does; V3 runs last, so the
 * sandbox is left on its own engine for the specs after this one.
 */
import { test, expect, type Page } from "@playwright/test"

async function useEngine(page: Page, baseURL: string, engine: "v2" | "v3") {
  const switched = await page.request.put("/api/agent/engine", { data: { engine }, headers: { Origin: baseURL } })
  expect(switched.status()).toBe(200)
}

async function composeCard(page: Page, engine: "v2" | "v3") {
  await page.goto("/decks")
  await page.getByRole("button", { name: "New Deck" }).click()
  const input = page.getByRole("textbox", { name: "Chat message input" })
  await input.fill(`Compose a two-part deck on ${engine}`)
  await page.getByRole("button", { name: "Send message" }).click()

  const chatLog = page.getByRole("log", { name: "Chat messages" })
  await expect(chatLog).toContainText("Done! Your deck is ready.", { timeout: 30_000 })

  const cards = chatLog.getByRole("region", { name: "Composing slides" })
  await expect(cards).toHaveCount(1)
  const card = cards.first()
  // Both groups, with the slugs their delegation assigned, finished; the card closed as composed.
  await expect(card).toContainText("Composed 2 slides")
  await expect(card).toContainText("Ready for review")
  await expect(card).toContainText("intro")
  await expect(card).toContainText("outro")
  await expect(card).toContainText("2 / 2 created")
  await expect(card.getByLabel("Slide created")).toHaveCount(2)
  await expect(card).not.toContainText("Failed")
}

test("the Compose card shows both groups done and closes (V2)", async ({ page, baseURL }) => {
  await useEngine(page, baseURL!, "v2")
  await composeCard(page, "v2")
})

test("the Compose card shows both groups done and closes (V3)", async ({ page, baseURL }) => {
  await useEngine(page, baseURL!, "v3")
  await composeCard(page, "v3")
})
