// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The Local server refuses a foreign Host on every route. The proxy has no matcher, so Next runs
 * it before every request; this checks that and runs it against each route under src/app/api.
 */

import fs from "fs"
import path from "path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// A string path: `build:cloud` moves proxy.ts out (not this test), and its type check must not
// resolve the import.
const PROXY_MODULE = "./proxy"
type ProxyModule = { proxy: (request: Request) => Response | undefined, config?: unknown }
const proxyModule = (await import(/* @vite-ignore */ PROXY_MODULE)) as ProxyModule
const { proxy } = proxyModule

const API_DIR = path.resolve(__dirname, "app/api")

/** URL paths of every route.ts under src/app/api, dynamic segments filled in. */
function apiRoutes(dir = API_DIR): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.resolve(dir, entry.name) // nosemgrep: path-join-resolve-traversal — names from readdir of the source tree
    if (entry.isDirectory()) return apiRoutes(full)
    if (entry.name !== "route.ts") return []
    const rel = path.relative(API_DIR, dir).split(path.sep)
      .map((seg) => seg.replace(/^\[\.\.\..+\]$/, "a/b").replace(/^\[.+\]$/, "x"))
    return ["/api/" + rel.join("/")]
  })
}

function request(pathname: string, host: string | null, method = "GET"): Request {
  const headers: Record<string, string> = host ? { host, origin: `http://${host}` } : {}
  return new Request(`http://127.0.0.1:3000${pathname}`, { method, headers })
}

beforeEach(() => {
  vi.stubEnv("PORT", "3000")
})

afterEach(() => {
  vi.unstubAllEnvs()
})

describe("proxy", () => {
  const routes = apiRoutes()

  it("finds the API routes and runs on every request (no matcher)", () => {
    expect(routes.length).toBeGreaterThan(20)
    expect("config" in proxyModule).toBe(false)
  })

  it.each(routes)("refuses a foreign Host on %s", (pathname) => {
    for (const method of ["GET", "POST", "PUT", "PATCH", "DELETE"]) {
      expect(proxy(request(pathname, "evil.example:3000", method))?.status).toBe(403)
      expect(proxy(request(pathname, null, method))?.status).toBe(403)
    }
    expect(proxy(request(pathname, "127.0.0.1:3000"))).toBeUndefined()
    expect(proxy(request(pathname, "localhost:3000"))).toBeUndefined()
  })

  it("refuses a foreign Host with NEXT_PUBLIC_MODE unset (the API routes are still served)", () => {
    vi.stubEnv("NEXT_PUBLIC_MODE", undefined)
    expect(proxy(request("/api/decks", "evil.example:3000"))?.status).toBe(403)
    expect(proxy(request("/api/decks", "127.0.0.1:3000"))).toBeUndefined()
    expect(proxy(request("/api/decks", "localhost:3000"))).toBeUndefined()
  })

  it("is moved out of the cloud build together with the API routes", () => {
    const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../package.json"), "utf-8"))
    expect(pkg.scripts["build:cloud"]).toContain("mv src/app/api src/app/_api")
    expect(pkg.scripts["build:cloud"]).toContain("mv src/proxy.ts src/_proxy.ts")
  })
})
