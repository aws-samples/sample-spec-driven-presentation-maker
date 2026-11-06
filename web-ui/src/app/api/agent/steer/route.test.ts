// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * POST /api/agent/steer sends a message into the session's running turn: 200 once kiro-cli
 * queued it, 409 with the rejection's code when it did not, 504 agent_timeout when kiro-cli
 * did not answer, 400 for a body without sessionId / id / text, 403 for a cross-site request
 * and 415 for a body that is not JSON.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"
import { SteerRejectedError } from "@/lib/local/conversation/steer"
import { AgentTimeoutError } from "@/lib/local/turnErrors"

const acp = vi.hoisted(() => ({ steerSession: vi.fn() }))
vi.mock("@/lib/local/acp-process", () => acp)

import { POST } from "./route"

function steer(body: unknown, headers: Record<string, string> = {}) {
  return POST(new Request("http://127.0.0.1:3000/api/agent/steer", {
    method: "POST",
    headers: { "content-type": "application/json", host: "127.0.0.1:3000", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  }))
}

beforeEach(() => {
  acp.steerSession.mockReset()
})

describe("POST /api/agent/steer", () => {
  it("answers 200 once kiro-cli queued the message", async () => {
    acp.steerSession.mockResolvedValue(undefined)
    const res = await steer({ sessionId: "C1", id: "m1", text: "use blue" })
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ steer: { id: "m1", state: "accepted" } })
    expect(acp.steerSession).toHaveBeenCalledWith("C1", "m1", "use blue")
  })

  it.each(["session_idle", "steer_not_queued"] as const)("answers 409 %s when kiro-cli did not take it", async (code) => {
    acp.steerSession.mockRejectedValue(new SteerRejectedError(code, "epoch_changed"))
    const res = await steer({ sessionId: "C1", id: "m1", text: "use blue" })
    expect(res.status).toBe(409)
    expect(await res.json()).toMatchObject({ code })
  })

  it("answers 504 agent_timeout when kiro-cli does not answer", async () => {
    acp.steerSession.mockRejectedValue(new AgentTimeoutError("_session/steer", 10_000))
    const res = await steer({ sessionId: "C1", id: "m1", text: "use blue" })
    expect(res.status).toBe(504)
    expect(await res.json()).toMatchObject({ status: "error", code: "agent_timeout" })
  })

  it.each([
    ["no sessionId", { id: "m1", text: "x" }],
    ["no id", { sessionId: "C1", text: "x" }],
    ["an id that is not the chat's", { sessionId: "C1", id: "m".repeat(101), text: "x" }],
    ["blank text", { sessionId: "C1", id: "m1", text: "  " }],
    ["text that is not a string", { sessionId: "C1", id: "m1", text: 3 }],
  ])("answers 400 for %s", async (_name, body) => {
    const res = await steer(body)
    expect(res.status).toBe(400)
    expect(acp.steerSession).not.toHaveBeenCalled()
  })

  it("refuses a cross-site request and a body that is not JSON", async () => {
    expect((await steer({ sessionId: "C1", id: "m1", text: "x" }, { origin: "https://evil.example" })).status).toBe(403)
    expect((await steer("sessionId=C1", { "content-type": "application/x-www-form-urlencoded" })).status).toBe(415)
    expect((await steer("{not json")).status).toBe(400)
    expect(acp.steerSession).not.toHaveBeenCalled()
  })
})
