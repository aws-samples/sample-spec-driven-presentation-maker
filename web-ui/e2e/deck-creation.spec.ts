// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: deck creation happy path (roadmap 2-5b-4).
 *
 * Deck list → New Deck → send a chat message → stub agent creates a deck
 * and streams tool events → UI navigates to the workspace and shows the
 * slide preview. Exercises the full Local-mode stack: React UI, Next.js
 * API routes, ACP process manager, SSE bridge, and strandsParser.
 */
import { test, expect } from "@playwright/test"

const DECK_ID = "e2e-test-deck"

test("create deck via chat and see slide preview", async ({ page }) => {
  await page.goto("/decks")

  // Deck list renders (empty sandbox)
  await expect(page.getByRole("heading", { name: "Decks" })).toBeVisible()

  // Open the new-deck chat panel
  await page.getByRole("button", { name: "New Deck" }).click()
  const input = page.getByRole("textbox", { name: "Chat message input" })
  await expect(input).toBeVisible()

  // Send a message
  await input.fill("Create a deck about end-to-end testing")
  await page.getByRole("button", { name: "Send message" }).click()

  // User message and streamed assistant reply appear
  const chatLog = page.getByRole("log", { name: "Chat messages" })
  await expect(chatLog).toContainText("Create a deck about end-to-end testing")
  await expect(chatLog).toContainText("Done! Your deck is ready.", { timeout: 30_000 })

  // Deck-created tool result navigates to the workspace (hash routing)
  await expect(page).toHaveURL(new RegExp(`#${DECK_ID}$`), { timeout: 15_000 })

  // Workspace polling picks up the slide — the Slides tab appears with a count
  const slidesTab = page.getByRole("tab", { name: /Slides/ })
  await expect(slidesTab).toBeVisible({ timeout: 30_000 })
  await slidesTab.click()

  // Slide preview renders from the deck the stub wrote to disk
  await expect(page.locator(`img[alt^="Slide 1"]`).first()).toBeVisible({ timeout: 30_000 })
})
