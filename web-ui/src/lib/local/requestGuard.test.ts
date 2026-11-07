// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"

import { allowedHosts, rejectForeignHost } from "./requestGuard"

function withHeaders(headers: Record<string, string>): Request {
  return new Request("http://127.0.0.1:3000/api/decks", { headers })
}

afterEach(() => {
  vi.unstubAllEnvs()
})

describe("rejectForeignHost", () => {
  it.each(["127.0.0.1:3000", "localhost:3000", "[::1]:3000", "LOCALHOST:3000"])("accepts %s", (host) => {
    expect(rejectForeignHost(withHeaders({ host }), "3000")).toBeNull()
  })

  it.each([
    ["another port", "127.0.0.1:3001"],
    ["no port", "localhost"],
    ["IPv6 without brackets", "::1:3000"],
    ["a domain that resolves to loopback", "evil.example:3000"],
    ["a loopback-looking subdomain", "localhost.evil.example:3000"],
    ["another loopback address", "127.0.0.2:3000"],
  ])("refuses %s", async (_label, host) => {
    const res = rejectForeignHost(withHeaders({ host }), "3000")
    expect(res?.status).toBe(403)
    await expect(res?.json()).resolves.toEqual({ error: "Host not allowed" })
  })

  it("refuses a request without a Host header", () => {
    expect(rejectForeignHost(withHeaders({}), "3000")?.status).toBe(403)
  })

  it("refuses a foreign Host even when Origin matches it", () => {
    const req = withHeaders({ host: "evil.example:3000", origin: "http://evil.example:3000" })
    expect(rejectForeignHost(req, "3000")?.status).toBe(403)
  })

  it("uses the port Next listens on, 3000 when PORT is unset", () => {
    vi.stubEnv("PORT", "3199")
    expect(rejectForeignHost(withHeaders({ host: "127.0.0.1:3199" }))).toBeNull()
    expect(rejectForeignHost(withHeaders({ host: "127.0.0.1:3000" }))?.status).toBe(403)
    vi.stubEnv("PORT", "")
    expect([...allowedHosts()]).toEqual(["127.0.0.1:3000", "localhost:3000", "[::1]:3000"])
  })
})
