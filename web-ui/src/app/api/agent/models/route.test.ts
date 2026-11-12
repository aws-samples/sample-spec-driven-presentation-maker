// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * GET / PUT /api/agent/models: GET answers a chat's models (or the list alone without an id);
 * PUT takes exactly `{sessionId, model?, effort?}` with one of the two, as JSON from the same
 * site, and answers the chat's models after the choice; a choice the chat is not offered is 400
 * with its code, one kiro-cli refused 502. The process manager's rules are acp-process.test.ts's.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"

import { ModelChoiceError } from "@/lib/local/sessionErrors"

const { getSessionModels, chooseSessionModel } = vi.hoisted(() => ({ getSessionModels: vi.fn(), chooseSessionModel: vi.fn() }))
vi.mock("@/lib/local/acp-process", () => ({ getSessionModels, chooseSessionModel }))

import { GET, PUT } from "./route"

const VIEW = { engine: "v3", available: [{ modelId: "auto", name: "Auto" }], current: null, pending: null }

beforeEach(() => {
  getSessionModels.mockReset().mockReturnValue(VIEW)
  chooseSessionModel.mockReset().mockResolvedValue({ ...VIEW, pending: { model: "auto" } })
})

const get = (query = "") => GET(new Request(`http://127.0.0.1:3000/api/agent/models${query}`))

function put(body: unknown, headers: Record<string, string> = {}) {
  return PUT(new Request("http://127.0.0.1:3000/api/agent/models", {
    method: "PUT",
    headers: { "content-type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  }))
}

describe("GET /api/agent/models", () => {
  it("answers the list without an id and a chat's models with one", async () => {
    expect(await (await get()).json()).toEqual(VIEW)
    expect(getSessionModels).toHaveBeenLastCalledWith(undefined)
    await get("?sessionId=C1_a-b")
    expect(getSessionModels).toHaveBeenLastCalledWith("C1_a-b")
  })

  it("refuses an id that is not one", async () => {
    expect((await get("?sessionId=../x")).status).toBe(400)
    expect((await get("?sessionId=")).status).toBe(400)
    expect(getSessionModels).not.toHaveBeenCalled()
  })
})

describe("PUT /api/agent/models", () => {
  it("passes a valid choice on and answers the chat's models", async () => {
    const res = await put({ sessionId: "C1", model: "claude-haiku-5.5", effort: "low" })
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ...VIEW, pending: { model: "auto" } })
    expect(chooseSessionModel).toHaveBeenCalledWith("C1", { model: "claude-haiku-5.5", effort: "low" })
    await put({ sessionId: "C1", effort: "high" })
    expect(chooseSessionModel).toHaveBeenLastCalledWith("C1", { effort: "high" })
  })

  it.each([
    ["another key", { sessionId: "C1", model: "auto", modelId: "auto" }],
    ["neither model nor effort", { sessionId: "C1" }],
    ["no sessionId", { model: "auto" }],
    ["a model id with spaces", { sessionId: "C1", model: "a b" }],
    ["an effort that is not a word", { sessionId: "C1", effort: "HIGH!" }],
    ["a number", { sessionId: "C1", model: 3 }],
    ["an array", [{ sessionId: "C1" }]],
    ["invalid JSON", "{"],
  ])("refuses %s with 400", async (_case, body) => {
    expect((await put(body)).status).toBe(400)
    expect(chooseSessionModel).not.toHaveBeenCalled()
  })

  it.each([
    ["unknown_model", 400],
    ["effort_not_supported", 400],
    ["unknown_effort", 400],
    ["models_unknown", 400],
    ["model_not_changed", 502],
  ] as const)("answers %s with %d and its code", async (code, status) => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      chooseSessionModel.mockRejectedValue(new ModelChoiceError(code, "detail"))
      const res = await put({ sessionId: "C1", model: "auto" })
      expect(res.status).toBe(status)
      expect(await res.json()).toEqual({ error: "detail", code })
    } finally {
      warn.mockRestore()
    }
  })

  it("refuses a cross-site request and a body that is not JSON", async () => {
    expect((await put({ sessionId: "C1", model: "auto" }, { origin: "https://evil.example" })).status).toBe(403)
    expect((await put({ sessionId: "C1", model: "auto" }, { "content-type": "text/plain" })).status).toBe(415)
    expect(chooseSessionModel).not.toHaveBeenCalled()
  })
})
