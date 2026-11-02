// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const CONFIG = { apiBaseUrl: "https://api.example/prod/", agentRuntimeArn: "arn:runtime", awsRegion: "ap-northeast-1" }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

/** The cache is module state: load a fresh copy of the module per test. */
async function freshModule() {
  vi.resetModules()
  return import("./runtimeConfig")
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("loadRuntimeConfig", () => {
  it("fetches /aws-exports.json once for concurrent and later callers", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(CONFIG))
    const { loadRuntimeConfig } = await freshModule()

    const [a, b] = await Promise.all([loadRuntimeConfig(), loadRuntimeConfig()])
    const c = await loadRuntimeConfig()

    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith("/aws-exports.json")
    expect(a).toEqual(CONFIG)
    expect(b).toBe(a)
    expect(c).toBe(a)
  })

  it("shares the one fetch between deckService and other callers", async () => {
    vi.mocked(fetch).mockImplementation(async (input) =>
      String(input) === "/aws-exports.json" ? jsonResponse(CONFIG) : jsonResponse({ decks: [], favoriteIds: [] }))
    vi.resetModules()
    const { listDecks } = await import("@/services/deckService")
    const { loadRuntimeConfig } = await import("./runtimeConfig")

    await listDecks("token")
    await listDecks("token")
    await loadRuntimeConfig()

    const configFetches = vi.mocked(fetch).mock.calls.filter(([url]) => url === "/aws-exports.json")
    expect(configFetches).toHaveLength(1)
    expect(fetch).toHaveBeenCalledWith(`${CONFIG.apiBaseUrl}decks`, expect.anything())
  })

  it("does not cache a failed load, so the next call retries", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({}, 404))
      .mockResolvedValueOnce(jsonResponse(CONFIG))
    const { loadRuntimeConfig } = await freshModule()

    await expect(loadRuntimeConfig()).rejects.toThrow("404")
    await expect(loadRuntimeConfig()).resolves.toEqual(CONFIG)
    expect(fetch).toHaveBeenCalledTimes(2)
  })
})
