// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * /api/agent/models: GET only reads the known list; POST starts a process first when no process
 * has reported models yet (the list comes from a kiro-cli session), and not when one has.
 */

import { beforeEach, describe, expect, it, vi } from "vitest"

const acp = vi.hoisted(() => ({
  models: { current: "", available: [] as { modelId: string; name: string }[] },
  createNewProcess: vi.fn(),
}))
vi.mock("@/lib/local/acp-process", () => ({
  getModels: () => acp.models,
  createNewProcess: acp.createNewProcess,
  setConfigOption: vi.fn(),
}))

import { GET, POST } from "./route"

const KNOWN = { current: "m1", available: [{ modelId: "m1", name: "Model 1" }] }

function post() {
  return POST(new Request("http://127.0.0.1:3000/api/agent/models", {
    method: "POST", headers: { "content-type": "application/json" }, body: "{}",
  }))
}

beforeEach(() => {
  acp.models = { current: "", available: [] }
  acp.createNewProcess.mockReset().mockImplementation(async () => { acp.models = KNOWN })
})

describe("/api/agent/models", () => {
  it("GET answers the known list without starting a process", async () => {
    expect(await (await GET()).json()).toEqual({ current: "", available: [] })
    expect(acp.createNewProcess).not.toHaveBeenCalled()
  })

  it("POST starts a process when no models are known, and answers its list", async () => {
    expect(await (await post()).json()).toEqual(KNOWN)
    expect(acp.createNewProcess).toHaveBeenCalledTimes(1)
  })

  it("POST answers the known list without starting another process", async () => {
    acp.models = KNOWN
    expect(await (await post()).json()).toEqual(KNOWN)
    expect(acp.createNewProcess).not.toHaveBeenCalled()
  })
})
