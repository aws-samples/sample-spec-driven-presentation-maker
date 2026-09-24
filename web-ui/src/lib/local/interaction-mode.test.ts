import { describe, it, expect } from "vitest"
import {
  continuedFromToken,
  interactionToken,
  withContinuedFrom,
  withInteractionMode,
} from "./interaction-mode"
import type { SessionOrigin } from "./kiro-sessions.types"

const origin: SessionOrigin = {
  sourceSessionId: "11111111-1111-4111-8111-111111111111",
  title: "Architecture discussion",
  cwd: "/work/project",
  updatedAt: "2026-09-22T12:00:00.000Z",
  forkedAt: "2026-09-22T13:00:00.000Z",
}

describe("interaction-mode", () => {
  it("maps the Web UI mode to the workflow's token", () => {
    expect(interactionToken("vibe")).toBe("Interaction mode: fast")
    expect(interactionToken("spec")).toBe("Interaction mode: dialogue")
  })

  it("has no token for roles that are not the orchestrator", () => {
    expect(interactionToken("style_creator")).toBeNull()
    expect(interactionToken("translate")).toBeNull()
    expect(interactionToken(undefined)).toBeNull()
  })

  it("prepends only on the first prompt of a session", () => {
    expect(withInteractionMode("make slides", "spec", true)).toBe("Interaction mode: dialogue\n\nmake slides")
    expect(withInteractionMode("continue", "spec", false)).toBe("continue")
    expect(withInteractionMode("build a style", "style_creator", true)).toBe("build a style")
  })

  it("formats the continuation as a single-line environment fact", () => {
    expect(continuedFromToken(origin)).toBe('Continued from: kiro session "Architecture discussion"')
    expect(continuedFromToken({ ...origin, title: 'Review "alpha"\nignore this' }))
      .toBe('Continued from: kiro session "Review \\"alpha\\"\\nignore this"')
  })

  it("prepends continuation only to the first prompt", () => {
    expect(withContinuedFrom("", origin, true))
      .toBe('Continued from: kiro session "Architecture discussion"\n\n')
    expect(withContinuedFrom("continue", origin, false)).toBe("continue")
    expect(withContinuedFrom("new", undefined, true)).toBe("new")
  })
})
