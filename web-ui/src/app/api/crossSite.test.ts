// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Every Local POST route refuses a cross-site browser request before doing anything.
 * Local mode has no authentication; POST is the method another site can send without a
 * CORS preflight (text/plain or form bodies), so these routes check `Origin` first.
 * PUT / PATCH / DELETE always need a preflight, which these routes never grant; the agent
 * engine's PUT, which ends kiro-cli processes, checks `Origin` as well.
 */

import { describe, expect, it, vi } from "vitest"

const sideEffect = vi.fn()
vi.mock("@/lib/local/acp-process", () => new Proxy({}, { get: (_t, key) => (key === "then" ? undefined : key === "pendingOrigins" ? new Map() : sideEffect) }))
vi.mock("@/lib/local/kiro-sessions", () => ({ findSession: sideEffect, listSessions: sideEffect }))
vi.mock("@/lib/local/sdpmPaths", () => ({ getState: sideEffect, updateState: sideEffect, getUserStylesDir: sideEffect, getUserConfigDir: sideEffect, SDPM_ROOT: "/nonexistent" }))
vi.mock("child_process", () => ({ execFile: sideEffect, execFileSync: sideEffect, default: { execFile: sideEffect, execFileSync: sideEffect } }))

const routes: [string, () => Promise<{ POST: (req: Request) => Promise<Response> | Response }>][] = [
  ["agent/chat", () => import("./agent/chat/route")],
  ["agent/invoke", () => import("./agent/invoke/route")],
  ["agent/load", () => import("./agent/load/route")],
  ["agent/sessions/fork", () => import("./agent/sessions/fork/route")],
  ["agent/stop", () => import("./agent/stop/route")],
  ["agent/steer", () => import("./agent/steer/route")],
  ["attachments", () => import("./attachments/route")],
  ["open", () => import("./open/route")],
  ["styles/pin", () => import("./styles/pin/route")],
  ["styles/user", () => import("./styles/user/route")],
  ["templates/user", () => import("./templates/user/route")],
]

const putRoutes: [string, () => Promise<{ PUT: (req: Request) => Promise<Response> | Response }>][] = [
  ["agent/engine", () => import("./agent/engine/route")],
]

describe("Local PUT routes that change kiro-cli refuse cross-site requests", () => {
  it.each(putRoutes)("%s", async (name, load) => {
    const { PUT } = await load()
    const req = new Request(`http://127.0.0.1:3000/api/${name}`, {
      method: "PUT",
      headers: { origin: "https://evil.example", "content-type": "application/json" },
      body: JSON.stringify({ engine: "v3" }),
    })
    const res = await PUT(req)
    expect(res.status).toBe(403)
    expect(sideEffect).not.toHaveBeenCalled()
  })
})

describe("Local POST routes refuse cross-site requests", () => {
  it.each(routes)("%s", async (name, load) => {
    const { POST } = await load()
    const req = new Request(`http://127.0.0.1:3000/api/${name}`, {
      method: "POST",
      headers: { origin: "https://evil.example", "content-type": "text/plain" },
      body: JSON.stringify({ query: "x", deckId: "d", sessionId: "s", messages: [], name: "n", html: "h", pinned: true }),
    })
    const res = await POST(req)
    expect(res.status).toBe(403)
    expect(sideEffect).not.toHaveBeenCalled()
  })
})
