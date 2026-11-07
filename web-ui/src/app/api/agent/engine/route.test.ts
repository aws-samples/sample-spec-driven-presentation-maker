// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * GET / PUT /api/agent/engine: GET answers the configured engine and the default; PUT takes
 * exactly `{engine: "v2" | "v3"}` as JSON from the same site, saves it and asks the process
 * manager to end the idle deck processes of the other engine (acp-process.test.ts checks that a
 * process of the same engine stays); a file that cannot be written is 500 and changes nothing.
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const terminateIdleProcesses = vi.hoisted(() => vi.fn())
vi.mock("@/lib/local/acp-process", () => ({ terminateIdleProcesses }))

let dir: string
let route: typeof import("./route")

beforeEach(async () => {
  dir = fs.mkdtempSync(path.resolve(os.tmpdir(), "sdpm-engine-route-"))
  vi.stubEnv("SDPM_ACP_CONFIG_DIR", dir)
  terminateIdleProcesses.mockReset()
  vi.resetModules()
  route = await import("./route")
})

afterEach(() => {
  vi.unstubAllEnvs()
  fs.rmSync(dir, { recursive: true, force: true })
})

function put(body: unknown, headers: Record<string, string> = {}) {
  return route.PUT(new Request("http://127.0.0.1:3000/api/agent/engine", {
    method: "PUT",
    headers: { "content-type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  }))
}

describe("/api/agent/engine", () => {
  it("answers the configured engine and the default", async () => {
    expect(await (await route.GET()).json()).toEqual({ engine: "v2", default: "v2" })
    fs.writeFileSync(path.resolve(dir, "acp-config.json"), JSON.stringify({ version: 2, engine: "v3" }))
    expect(await (await route.GET()).json()).toEqual({ engine: "v3", default: "v2" })
  })

  it("saves the engine and ends the idle deck processes of the other one", async () => {
    const res = await put({ engine: "v3" })
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ok: true, engine: "v3" })
    expect(JSON.parse(fs.readFileSync(path.resolve(dir, "acp-config.json"), "utf-8"))).toMatchObject({ version: 2, engine: "v3" })
    expect(terminateIdleProcesses).toHaveBeenCalledWith("v3")
  })

  it.each([
    ["another engine", { engine: "v4" }],
    ["another key", { engine: "v3", command: "sh" }],
    ["no engine", {}],
    ["an array", ["v3"]],
    ["invalid JSON", "{"],
  ])("refuses %s with 400 and saves nothing", async (_case, body) => {
    const res = await put(body)
    expect(res.status).toBe(400)
    expect(fs.existsSync(path.resolve(dir, "acp-config.json"))).toBe(false)
    expect(terminateIdleProcesses).not.toHaveBeenCalled()
  })

  it("refuses a cross-site request and a body that is not JSON", async () => {
    expect((await put({ engine: "v3" }, { origin: "https://evil.example" })).status).toBe(403)
    expect((await put({ engine: "v3" }, { "content-type": "text/plain" })).status).toBe(415)
    expect(terminateIdleProcesses).not.toHaveBeenCalled()
  })

  it("answers 500 when the setting cannot be written", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {})
    try {
      fs.rmSync(dir, { recursive: true })
      fs.writeFileSync(dir, "a file where the directory should be")
      const res = await put({ engine: "v3" })
      expect(res.status).toBe(500)
      expect(await res.json()).toEqual({ error: expect.any(String) })
      expect(terminateIdleProcesses).not.toHaveBeenCalled()
    } finally {
      error.mockRestore()
      fs.rmSync(dir, { force: true })
      fs.mkdirSync(dir)
    }
  })
})
