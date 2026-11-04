// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { afterEach, describe, expect, it, vi } from "vitest"

const mode = vi.hoisted(() => ({ local: false }))
vi.mock("@/lib/mode", () => ({
  get IS_LOCAL() { return mode.local },
}))

import { generateSessionId } from "./agentCoreService"

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

describe("generateSessionId", () => {
  afterEach(() => { mode.local = false })

  it("carries the owner prefix in Cloud mode", () => {
    const id = generateSessionId("user-1")
    expect(id.startsWith("c6c289e49e9c05b2-")).toBe(true)
    expect(id.slice(17)).toMatch(UUID)
  })

  it("stays a plain UUID in Local mode", () => {
    mode.local = true
    expect(generateSessionId("user-1")).toMatch(UUID)
  })
})
