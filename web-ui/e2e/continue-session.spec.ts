// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: "Continue from a kiro session" on each agent engine.
 *
 * The sandbox has one V2 session ("E2E V2 source", in V2's session store) and the stub's V3
 * lists one V3 session ("E2E V3 source"). On V3 the picker lists both, the V3 one first (newer),
 * each with its engine badge; picking either forks it (V3's session/fork, which also takes the
 * V2 one), the hidden first turn streams the stub's reply and the chat shows where it branched
 * from. On V2 only the V2 session is listed, with a line saying V3 sessions need the V3 engine;
 * picking it forks it as a V2 copy. The test ends on V3, so the specs after it keep the
 * sandbox's engine.
 */
import { test, expect, type Page } from "@playwright/test"

async function useEngine(page: Page, baseURL: string, engine: "v2" | "v3") {
  const switched = await page.request.put("/api/agent/engine", { data: { engine }, headers: { Origin: baseURL } })
  expect(switched.status()).toBe(200)
}

/** A new chat's picker, open. */
async function openPicker(page: Page) {
  await page.goto("/decks")
  await page.getByRole("button", { name: "New Deck" }).click()
  await page.getByRole("button", { name: "Attach file or snippet" }).click()
  await page.getByRole("button", { name: "Continue from a kiro session" }).click()
  const dialog = page.getByRole("dialog", { name: "Continue from a kiro session" })
  await expect(dialog.getByRole("option").first()).toBeVisible({ timeout: 30_000 })
  return dialog
}

async function continueFrom(page: Page, title: string) {
  const dialog = await openPicker(page)
  await dialog.getByRole("option", { name: title }).click()
  const chatLog = page.getByRole("log", { name: "Chat messages" })
  await expect(chatLog).toContainText("Done! Your deck is ready.", { timeout: 30_000 })
  await expect(page.getByText(`Branched from “${title}”`)).toBeVisible()
}

test("V3 lists its own and V2's sessions with their badges, and continues from either", async ({ page, baseURL }) => {
  await useEngine(page, baseURL!, "v3")
  const dialog = await openPicker(page)
  const options = dialog.getByRole("option")
  await expect(options).toHaveCount(2)
  await expect(options.nth(0)).toContainText("E2E V3 source")
  await expect(options.nth(0).getByRole("img", { name: "Saved by the V3 agent engine" })).toHaveText("V3")
  await expect(options.nth(1)).toContainText("E2E V2 source")
  await expect(options.nth(1).getByRole("img", { name: "Saved by the V2 agent engine" })).toHaveText("V2")
  await expect(dialog).not.toContainText("V3 sessions are listed when")

  await continueFrom(page, "E2E V3 source")
  await continueFrom(page, "E2E V2 source")
})

test("V2 lists only V2's sessions, says where V3's are, and continues from one", async ({ page, baseURL }) => {
  await useEngine(page, baseURL!, "v2")
  try {
    const dialog = await openPicker(page)
    await expect(dialog.getByRole("option", { name: "E2E V2 source" })).toBeVisible()
    await expect(dialog).not.toContainText("E2E V3 source")
    await expect(dialog).toContainText("V3 sessions are listed when the agent engine is V3 (Settings).")
    await page.keyboard.press("Escape")

    await continueFrom(page, "E2E V2 source")
  } finally {
    await useEngine(page, baseURL!, "v3")
  }
})
