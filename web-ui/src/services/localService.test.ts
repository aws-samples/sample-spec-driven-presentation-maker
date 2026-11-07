// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const mode = vi.hoisted(() => ({ local: true }))
vi.mock("@/lib/mode", () => ({ get IS_LOCAL() { return mode.local } }))

import {
  getAgentDefinitions, getAgentEngine, hasLocalStream, listLocalModels, localStreamUrl,
  openInOs, saveLocalChat, setAgentEngine, stopLocalAgent, updateAgentSelection,
} from "./localService"

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

/** The [url, init] of the n-th fetch call, with the JSON body parsed. */
function call(n = 0) {
  const [url, init] = vi.mocked(fetch).mock.calls[n]
  return { url, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined }
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ ok: true })))
})

afterEach(() => {
  vi.unstubAllGlobals()
  mode.local = true
})

describe("localService (local mode)", () => {
  it("openInOs posts the deck and the file to /api/open", async () => {
    await openInOs("d1", "output.pptx")
    await openInOs("d1")
    expect(call(0)).toEqual({ url: "/api/open", method: "POST", body: { deckId: "d1", file: "output.pptx" } })
    expect(call(1)).toEqual({ url: "/api/open", method: "POST", body: { deckId: "d1" } })
  })

  it("rejects when the route answers with an error status", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ error: "not found" }, 404))
    await expect(openInOs("d1", "output.html")).rejects.toThrow("HTTP 404")
  })

  it("saveLocalChat and stopLocalAgent post their payloads", async () => {
    await saveLocalChat("d1", [{ role: "user", content: "hi" }])
    await stopLocalAgent({ sessionId: "s1" })
    await stopLocalAgent({ newChat: true })
    expect(call(0)).toEqual({ url: "/api/agent/chat", method: "POST", body: { deckId: "d1", messages: [{ role: "user", content: "hi" }] } })
    expect(call(1)).toEqual({ url: "/api/agent/stop", method: "POST", body: { sessionId: "s1" } })
    expect(call(2)).toEqual({ url: "/api/agent/stop", method: "POST", body: { newChat: true } })
  })

  it("reads agent definitions and updates the selection with PUT", async () => {
    const agents = [{ fileName: "a.json", name: "A", description: "" }]
    const selection = { orchestrator: "a.json", composer: "", style: "", translate: "" }
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ agents, selection }))
    await expect(getAgentDefinitions()).resolves.toEqual({ agents, selection })
    await updateAgentSelection({ model: null })
    expect(call(0).url).toBe("/api/agent/definitions")
    expect(call(1)).toEqual({ url: "/api/agent/definitions", method: "PUT", body: { model: null } })
  })

  it("reads the agent engine and saves it with PUT", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ engine: "v2", default: "v2" }))
    await expect(getAgentEngine()).resolves.toEqual({ engine: "v2", default: "v2" })
    await setAgentEngine("v3")
    expect(call(0).url).toBe("/api/agent/engine")
    expect(call(1)).toEqual({ url: "/api/agent/engine", method: "PUT", body: { engine: "v3" } })
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ error: "x" }, 500))
    await expect(setAgentEngine("v2")).rejects.toThrow("HTTP 500")
  })

  it("maps the model list to the ModelPicker shape", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ available: [{ modelId: "m1", name: "Model 1", description: "d" }] }))
    await expect(listLocalModels()).resolves.toEqual([{ modelId: "m1", displayName: "Model 1", description: "d" }])
    expect(call(0)).toEqual({ url: "/api/agent/models", method: "POST", body: {} })
  })

  it("builds the stream URL and probes whether the session still streams", async () => {
    expect(localStreamUrl("a b")).toBe("/api/agent/stream?sessionId=a%20b")
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response("", { headers: { "Content-Type": "text/event-stream" } }))
      .mockResolvedValueOnce(jsonResponse({ running: false }))
      .mockRejectedValueOnce(new TypeError("network"))
    expect(await hasLocalStream("s1")).toBe(true)
    expect(await hasLocalStream("s1")).toBe(false)
    expect(await hasLocalStream("s1")).toBe(false)
    expect(call(0).url).toBe("/api/agent/stream?sessionId=s1")
  })
})

describe("localService (cloud mode)", () => {
  it("returns early without calling the Local API routes", async () => {
    mode.local = false
    await openInOs("d1", "output.pptx")
    await saveLocalChat("d1", [])
    await stopLocalAgent({ newChat: true })
    await updateAgentSelection({ model: "m1" })
    expect(await getAgentEngine()).toBeNull()
    await setAgentEngine("v3")
    expect(await getAgentDefinitions()).toEqual({ agents: [], selection: { orchestrator: "", composer: "", style: "", translate: "" } })
    expect(await listLocalModels()).toEqual([])
    expect(localStreamUrl("s1")).toBeNull()
    expect(await hasLocalStream("s1")).toBe(false)
    expect(fetch).not.toHaveBeenCalled()
  })
})
