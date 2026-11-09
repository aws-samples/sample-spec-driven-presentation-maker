// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: the deck chat's next turn names the deck files changed outside it since its last turn.
 *
 * The stub agent makes a deck through the chat. Once the work period has ended (the deck's
 * `.session-turn` is written), the test changes deck files as another client would: a spec, and
 * the Web UI's own `.chat.json` and a preview, which do not count. The next turn's prompt (the
 * stub's trace) starts with `Changed outside since your last turn:` and lists only the spec; the
 * chat shows the user's text alone; the turn after it has no note. Runs on V2, then V3.
 */
import fs from "fs"
import path from "path"
import { test, expect, type Page } from "@playwright/test"

const TMP = path.resolve(__dirname, ".tmp")
const DECKS = path.join(TMP, "decks")
const TRACE = path.join(TMP, "stub-trace.jsonl")
const NOTE = "Changed outside since your last turn:"

interface TraceLine { sessionId: string; role: string; event: string; text?: string }

const readTrace = (): TraceLine[] => (fs.existsSync(TRACE) ? fs.readFileSync(TRACE, "utf-8").split("\n").filter(Boolean).map((l) => JSON.parse(l)) : [])
const deckDir = (deckId: string) => path.join(DECKS, deckId) // nosemgrep: path-join-resolve-traversal — constant deck ids in the sandbox

/** The orchestrator prompt of `engine` whose text contains `marker`. */
const promptWith = (engine: "v2" | "v3", marker: string) => readTrace()
  .findLast((l) => l.role === "orchestrator" && l.event === "prompt" && l.sessionId.startsWith(`stub-${engine}-`) && l.text?.includes(marker))

async function send(page: Page, message: string) {
  await page.getByRole("textbox", { name: "Chat message input" }).fill(message)
  await page.getByRole("button", { name: "Send message" }).click()
}

/** Set `file`'s mtime 2 s ahead: changed after the period's end mark. */
function touchAhead(file: string) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  if (!fs.existsSync(file)) fs.writeFileSync(file, "changed outside")
  const at = (Date.now() + 2000) / 1000
  fs.utimesSync(file, at, at)
}

for (const engine of ["v2", "v3"] as const) {
  test.describe(`deck changed outside the chat (${engine})`, () => {
    const deckId = `e2e-${engine}-c6`
    test.afterAll(async ({ request, baseURL }) => {
      fs.rmSync(deckDir(deckId), { recursive: true, force: true })
      if (engine === "v2") await request.put("/api/agent/engine", { data: { engine: "v3" }, headers: { Origin: baseURL! } })
    })

    test("the next turn lists the changed deck files, once, and the chat shows only the user's text", async ({ page, baseURL }) => {
      const switched = await page.request.put("/api/agent/engine", { data: { engine }, headers: { Origin: baseURL! } })
      expect(switched.status()).toBe(200)

      await page.goto("/decks")
      await page.getByRole("button", { name: "New Deck" }).click()
      await send(page, "deck=c6 Create a deck")
      const chatLog = page.getByRole("log", { name: "Chat messages" })
      await expect(chatLog).toContainText("Done! Your deck is ready.", { timeout: 30_000 })
      await expect(page).toHaveURL(new RegExp(`#${deckId}$`), { timeout: 15_000 })
      const mark = path.join(deckDir(deckId), ".session-turn")
      await expect.poll(() => fs.existsSync(mark), { timeout: 15_000 }).toBe(true)
      // The chat is saved when the turn ends; its .chat.json exists before it is touched below.
      await expect.poll(async () => (await page.request.get(`/api/agent/chat?deckId=${deckId}`)).text(), { timeout: 15_000 })
        .toContain("Done! Your deck is ready.")

      touchAhead(path.join(deckDir(deckId), "specs", "outline.md"))
      touchAhead(path.join(deckDir(deckId), ".chat.json"))
      touchAhead(path.join(deckDir(deckId), "preview", "x.png"))
      await page.waitForTimeout(2100)

      const sentAt = Date.now()
      await send(page, `[chat] c6-second-${engine}`)
      await expect(chatLog).toContainText("51", { timeout: 15_000 })
      const second = promptWith(engine, `c6-second-${engine}`)!
      expect(second.text!.startsWith(`${NOTE} `)).toBe(true)
      expect(second.text).toContain("\n- specs/outline.md\n")
      expect(second.text).not.toContain(".chat.json")
      expect(second.text).not.toContain("preview/")
      await expect(chatLog).not.toContainText(NOTE)
      await expect(chatLog).toContainText(`[chat] c6-second-${engine}`)

      // The second period has ended: its mark is newer than the edits.
      await expect.poll(() => (JSON.parse(fs.readFileSync(mark, "utf-8")) as { endedAt: number }).endedAt, { timeout: 15_000 }).toBeGreaterThan(sentAt)
      await send(page, `[chat] c6-third-${engine}`)
      await expect.poll(() => promptWith(engine, `c6-third-${engine}`)?.text, { timeout: 15_000 }).toBe(`[chat] c6-third-${engine}`)
    })
  })
}
