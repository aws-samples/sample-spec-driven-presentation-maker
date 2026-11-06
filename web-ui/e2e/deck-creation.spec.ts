// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: deck creation happy path (roadmap 2-5b-4), on each agent engine.
 *
 * Deck list → New Deck → send a chat message → stub agent creates a deck
 * and streams tool events → UI navigates to the workspace and shows the
 * slide preview. Exercises the full Local-mode stack: React UI, Next.js
 * API routes, ACP process manager and engine adapters, SSE bridge, and
 * strandsParser. Runs on V3 (the sandbox's engine) first, then switches to
 * V2 through PUT /api/agent/engine, as Settings does. The first text must
 * arrive within 5 s of sending: a start that misses the sdpm server's
 * readiness would wait out its 120 s instead.
 */
import { test, expect, type Page } from "@playwright/test"

async function createDeck(page: Page, engine: "v2" | "v3") {
  await page.goto("/decks")
  await expect(page.getByRole("heading", { name: "Decks" })).toBeVisible()

  // Open the new-deck chat panel
  await page.getByRole("button", { name: "New Deck" }).click()
  const input = page.getByRole("textbox", { name: "Chat message input" })
  await expect(input).toBeVisible()

  // Send a message
  await input.fill(`Create a deck about end-to-end testing on ${engine}`)
  await page.getByRole("button", { name: "Send message" }).click()

  // User message and streamed assistant reply appear; the first text comes at once
  const chatLog = page.getByRole("log", { name: "Chat messages" })
  await expect(chatLog).toContainText(`Create a deck about end-to-end testing on ${engine}`)
  await expect(chatLog).toContainText("Creating your deck", { timeout: 5_000 })
  await expect(chatLog).toContainText("Done! Your deck is ready.", { timeout: 30_000 })

  // Deck-created tool result navigates to the workspace (hash routing)
  await expect(page).toHaveURL(new RegExp(`#e2e-${engine}-deck$`), { timeout: 15_000 })

  // Workspace polling picks up the slide — the Slides tab appears with a count
  const slidesTab = page.getByRole("tab", { name: /Slides/ })
  await expect(slidesTab).toBeVisible({ timeout: 30_000 })
  await slidesTab.click()

  // Slide preview renders from the deck the stub wrote to disk
  await expect(page.locator(`img[alt^="Slide 1"]`).first()).toBeVisible({ timeout: 30_000 })
}

test("create deck via chat and see slide preview (V3)", async ({ page }) => {
  await createDeck(page, "v3")
})

test("create deck via chat and see slide preview (V2, after switching the engine)", async ({ page, baseURL }) => {
  const switched = await page.request.put("/api/agent/engine", {
    data: { engine: "v2" },
    headers: { Origin: baseURL! },
  })
  expect(switched.status()).toBe(200)
  expect(await switched.json()).toEqual({ ok: true, engine: "v2" })
  await createDeck(page, "v2")
})
