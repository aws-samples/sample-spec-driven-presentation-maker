// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, expect, it } from "vitest"
import { deckSessionId, isOwnerPrefixed, newSessionId, ownerPrefix } from "./sessionId"

// runtimeSessionId accepts 33 to 256 characters.
const MIN = 33
const MAX = 256

describe("ownerPrefix", () => {
  it("matches the Python vector (tests/test_session_owner.py)", () => {
    expect(ownerPrefix("user-1")).toBe("c6c289e49e9c05b2")
    expect(ownerPrefix("user-2")).toBe("d92b69cfb82cecab")
  })
})

describe("newSessionId", () => {
  it("is <prefix>-<uuid v4>, 53 characters", () => {
    const id = newSessionId("user-1")
    expect(id).toMatch(/^[0-9a-f]{16}-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    expect(id.startsWith("c6c289e49e9c05b2-")).toBe(true)
    expect(id).toHaveLength(53)
    expect(id.length).toBeGreaterThanOrEqual(MIN)
    expect(id.length).toBeLessThanOrEqual(MAX)
  })

  it("is new every time", () => {
    expect(newSessionId("user-1")).not.toBe(newSessionId("user-1"))
  })
})

describe("deckSessionId", () => {
  it("is <prefix>-<padded deck id>, 53 characters, the same on every call", () => {
    const id = deckSessionId("user-1", "a1b2c3d4")
    expect(id).toBe("c6c289e49e9c05b2-" + "a1b2c3d4".padEnd(36, "0"))
    expect(id).toHaveLength(53)
    expect(id.length).toBeGreaterThanOrEqual(MIN)
    expect(id.length).toBeLessThanOrEqual(MAX)
    expect(deckSessionId("user-1", "a1b2c3d4")).toBe(id)
  })

  it("differs per user for the same deck, each with its own prefix", () => {
    const a = deckSessionId("u1", "d1")
    const b = deckSessionId("u2", "d1")
    expect(a).not.toBe(b)
    expect(a.slice(0, 16)).toBe(ownerPrefix("u1"))
    expect(b.slice(0, 16)).toBe(ownerPrefix("u2"))
  })
})

describe("isOwnerPrefixed", () => {
  it.each([
    [newSessionId("user-1"), true],
    [deckSessionId("user-1", "d1"), true],
    [`${newSessionId("user-1")}-g2`, true],
    [crypto.randomUUID(), false],
    ["a1b2c3d4".padEnd(36, "0"), false],
    ["s".repeat(36), false],
    ["C6C289E49E9C05B2-x", false],
  ])("%s → %s", (id, expected) => {
    expect(isOwnerPrefixed(id)).toBe(expected)
  })
})
