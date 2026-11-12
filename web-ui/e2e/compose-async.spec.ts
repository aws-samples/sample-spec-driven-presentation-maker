// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: compose in the background, on each agent engine (the stub agent's `[groups N]`,
 * `[message N]`, `[chat]` and `<compose_result>` handling, e2e/stub-agent.mjs).
 *
 * - The groups overlap on composer processes of their own (from the stub's trace), and a user
 *   turn during compose is answered before either composer finished.
 * - `[message 1]` during compose reaches group 1's composer (its slide file has the text); after
 *   the task, a message to its group is "Not delivered".
 * - When both groups finish, the orchestrator is woken exactly once with `<compose_result>`.
 * - Stop ends the composers: no composer prompt after Stop, and the next message starts with the
 *   cancelled `<compose_result>`.
 * - A closed tab does not stop it: the wake turn rebuilds the stale output, and the reopened deck
 *   shows the report reply.
 * Runs on V2, then V3 (the sandbox's engine).
 */
import fs from "fs"
import path from "path"
import { test, expect, type Page } from "@playwright/test"

const TMP = path.resolve(__dirname, ".tmp")
const DECKS = path.join(TMP, "decks")
const TRACE = path.join(TMP, "stub-trace.jsonl")

interface TraceLine { pid: number; sessionId: string; role: "orchestrator" | "composer"; event: "prompt" | "answer"; wake?: boolean; text?: string; t: number }

const readTrace = (): TraceLine[] => (fs.existsSync(TRACE) ? fs.readFileSync(TRACE, "utf-8").split("\n").filter(Boolean).map((l) => JSON.parse(l)) : [])
const deckDir = (deckId: string) => path.join(DECKS, deckId) // nosemgrep: path-join-resolve-traversal — constant deck ids in the sandbox

async function useEngine(page: Page, baseURL: string, engine: "v2" | "v3") {
  const switched = await page.request.put("/api/agent/engine", { data: { engine }, headers: { Origin: baseURL } })
  expect(switched.status()).toBe(200)
}

async function send(page: Page, message: string) {
  await page.getByRole("textbox", { name: "Chat message input" }).fill(message)
  await page.getByRole("button", { name: "Send message" }).click()
}

/** New Deck, then a dispatching prompt; resolves once the deck's chat opened and the compose card shows. */
async function startCompose(page: Page, prompt: string, deckId: string) {
  await page.goto("/decks")
  await page.getByRole("button", { name: "New Deck" }).click()
  await send(page, prompt)
  const chatLog = page.getByRole("log", { name: "Chat messages" })
  await expect(chatLog).toContainText("The composers are on it.", { timeout: 20_000 })
  await expect(page).toHaveURL((url) => url.hash === `#${deckId}`, { timeout: 15_000 })
  await expect(chatLog.getByRole("region", { name: "Composing slides" })).toHaveCount(1)
  return chatLog
}

/** The trace lines of `engine`'s orchestrator session whose prompt named `deck=<slug>`, and of the composers of that deck. */
function linesOf(engine: "v2" | "v3", slug: string) {
  const all = readTrace()
  const first = all.findLast((l) => l.role === "orchestrator" && l.event === "prompt" && l.sessionId.startsWith(`stub-${engine}-`) && l.text?.includes(`deck=${slug}`))
  if (!first) return { orchestrator: [], composers: [], first: undefined }
  const orchestrator = all.filter((l) => l.sessionId === first.sessionId)
  const sessions = new Set(all.filter((l) => l.role === "composer" && l.event === "prompt" && l.text?.includes(`/e2e-${engine}-${slug}\n`)).map((l) => l.sessionId))
  const composers = all.filter((l) => l.role === "composer" && sessions.has(l.sessionId))
  return { orchestrator, composers, first }
}

for (const engine of ["v2", "v3"] as const) {
  test.describe(`compose in the background (${engine})`, () => {
    test.beforeEach(async ({ page, baseURL }) => { await useEngine(page, baseURL!, engine) })
    test.afterAll(async ({ request, baseURL }) => {
      await request.post("/api/agent/stop", { data: {}, headers: { Origin: baseURL! } })
      for (const slug of ["async-overlap", "async-steer", "async-stop", "async-closed"]) fs.rmSync(deckDir(`e2e-${engine}-${slug}`), { recursive: true, force: true })
      if (engine === "v2") await request.put("/api/agent/engine", { data: { engine: "v3" }, headers: { Origin: baseURL! } })
    })

    test("groups overlap on their own processes, a turn during compose is answered first, and one wake follows", async ({ page }) => {
      const chatLog = await startCompose(page, "[groups 2] [hold=6000] deck=async-overlap", `e2e-${engine}-async-overlap`)
      await send(page, "[chat] What is 17 × 3?")
      await expect(chatLog).toContainText("51", { timeout: 15_000 })
      const { orchestrator, composers, first } = linesOf(engine, "async-overlap")
      const chatAnswer = orchestrator.find((l, i) => l.event === "answer" && orchestrator[i - 1]?.text?.includes("[chat]"))!
      const prompted = composers.filter((l) => l.event === "prompt")
      expect(prompted).toHaveLength(2)
      expect(new Set(prompted.map((l) => l.pid)).size).toBe(2)
      expect(prompted.every((l) => l.pid !== first!.pid)).toBe(true)
      // The chat's answer came while both composers still ran.
      expect(composers.filter((l) => l.event === "answer" && l.t <= chatAnswer.t)).toHaveLength(0)

      await expect(chatLog).toContainText("Report seen: completed.", { timeout: 20_000 })
      const after = linesOf(engine, "async-overlap")
      const answers = after.composers.filter((l) => l.event === "answer")
      expect(Math.max(...after.composers.filter((l) => l.event === "prompt").map((l) => l.t))).toBeLessThan(Math.min(...answers.map((l) => l.t)))
      expect(after.orchestrator.filter((l) => l.event === "prompt" && l.wake)).toHaveLength(1)
    })

    test("a message reaches a running composer; after the task it is not delivered", async ({ page }) => {
      const deckId = `e2e-${engine}-async-steer`
      const chatLog = await startCompose(page, "[groups 2] [hold=8000] deck=async-steer", deckId)
      await send(page, "[message 1] Tell composer 1 to use the steered title.")
      await expect(chatLog.getByRole("note", { name: "Message with composer 1" }).first()).toContainText("Steered title", { timeout: 15_000 })
      const slide = path.join(deckDir(deckId), "slides", "s1.json")
      await expect.poll(() => fs.readFileSync(slide, "utf-8"), { timeout: 15_000 }).toContain("Steered title")
      await expect(chatLog).toContainText("Report seen: completed.", { timeout: 30_000 })
      await send(page, "[message 1] Once more.")
      await expect(chatLog.getByRole("note", { name: "Message with composer 1" }).last()).toContainText("Not delivered", { timeout: 15_000 })
    })

    test("Stop ends the composers, and the next message starts with the cancelled report", async ({ page }) => {
      const chatLog = await startCompose(page, "[groups 2] [hold=20000] deck=async-stop", `e2e-${engine}-async-stop`)
      await expect.poll(() => linesOf(engine, "async-stop").composers.filter((l) => l.event === "prompt").length, { timeout: 15_000 }).toBe(2)
      const stop = page.getByRole("button", { name: "Stop generation" })
      await expect(stop).toBeVisible()
      const stoppedAt = Date.now()
      await stop.click()
      await expect(chatLog.getByRole("region", { name: "Composing slides" })).toContainText("Stopped", { timeout: 10_000 })
      await expect.poll(() => linesOf(engine, "async-stop").composers.filter((l) => l.event === "answer").length, { timeout: 10_000 }).toBe(2)
      expect(linesOf(engine, "async-stop").composers.filter((l) => l.event === "prompt" && l.t > stoppedAt)).toHaveLength(0)
      await send(page, "[chat] Still there?")
      await expect(chatLog).toContainText("51", { timeout: 15_000 })
      const prompts = linesOf(engine, "async-stop").orchestrator.filter((l) => l.event === "prompt")
      expect(prompts.at(-1)!.text).toMatch(/^<compose_result task="[0-9a-f]{12}" status="cancelled">/)
    })

    test("a closed tab does not stop it: the wake turn rebuilds and the reopened deck shows the report", async ({ context }) => {
      const deckId = `e2e-${engine}-async-closed`
      const page = await context.newPage()
      await startCompose(page, "[groups 2] [hold=3000] [stale] deck=async-closed", deckId)
      await page.close()
      const output = path.join(deckDir(deckId), "output.pptx")
      const rebuilt = () => {
        if (!fs.existsSync(output)) return false
        const slides = ["s1.json", "s2.json"]
        return slides.every((name) => fs.existsSync(path.join(deckDir(deckId), "slides", name))) && slides.every((name) => fs.statSync(path.join(deckDir(deckId), "slides", name)).mtimeMs <= fs.statSync(output).mtimeMs) // nosemgrep: path-join-resolve-traversal — readdir names in the sandbox
      }
      await expect.poll(rebuilt, { timeout: 30_000 }).toBe(true)
      const reopened = await context.newPage()
      await reopened.goto(`/decks/#${deckId}`)
      const chatLog = reopened.getByRole("log", { name: "Chat messages" })
      await expect(chatLog).toContainText("Report seen: completed.", { timeout: 20_000 })
      await expect(chatLog.getByRole("region", { name: "Composing slides" })).toContainText("Composed 2 slides")
      await reopened.close()
    })
  })
}
