// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Every Local POST route refuses a cross-site browser request before doing anything.
 * Local mode has no authentication; POST is the method another site can send without a
 * CORS preflight (text/plain or form bodies), so these routes check `Origin` first.
 * PUT / PATCH / DELETE always need a preflight, which these routes never grant.
 */

import { describe, expect, it, vi } from "vitest"

const sideEffect = vi.fn()
vi.mock("@/lib/local/acp-process", () => new Proxy({}, { get: (_t, key) => (key === "then" ? undefined : key === "pendingOrigins" ? new Map() : sideEffect) }))
vi.mock("@/lib/local/kiro-sessions", () => ({ forkSession: sideEffect, removeForkedSession: sideEffect }))
vi.mock("@/lib/local/sdpmPaths", () => ({ getState: sideEffect, updateState: sideEffect, getUserStylesDir: sideEffect, getUserConfigDir: sideEffect, SDPM_ROOT: "/nonexistent" }))
vi.mock("child_process", () => ({ execFile: sideEffect, execFileSync: sideEffect, default: { execFile: sideEffect, execFileSync: sideEffect } }))

const routes: [string, () => Promise<{ POST: (req: Request) => Promise<Response> | Response }>][] = [
  ["agent/chat", () => import("./agent/chat/route")],
  ["agent/invoke", () => import("./agent/invoke/route")],
  ["agent/load", () => import("./agent/load/route")],
  ["agent/sessions/fork", () => import("./agent/sessions/fork/route")],
  ["agent/stop", () => import("./agent/stop/route")],
  ["attachments", () => import("./attachments/route")],
  ["open", () => import("./open/route")],
  ["styles/pin", () => import("./styles/pin/route")],
  ["styles/user", () => import("./styles/user/route")],
  ["templates/user", () => import("./templates/user/route")],
]

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
