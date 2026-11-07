// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** GET /api/agent/sessions: the session catalog's answer, with "Show all" as `?all=1`. */

import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({ listSessions: vi.fn() }))
vi.mock("@/lib/local/kiro-sessions", () => ({ listSessions: mocks.listSessions }))

import { GET } from "./route"

const LISTED = { engine: "v3", groups: [], recent: [], unavailable: ["v3"] }

beforeEach(() => {
  mocks.listSessions.mockReset()
  mocks.listSessions.mockResolvedValue(LISTED)
})

describe("GET /api/agent/sessions", () => {
  it.each([["", false], ["?all=1", true], ["?all=0", false]])("passes %j as includeAll %s and returns the catalog's JSON", async (query, includeAll) => {
    const res = await GET(new Request(`http://127.0.0.1:3000/api/agent/sessions${query}`))
    expect(mocks.listSessions).toHaveBeenCalledWith({ includeAll })
    expect(await res.json()).toEqual(LISTED)
  })
})
