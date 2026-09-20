import { describe, it, expect } from "vitest"
import { interactionToken, withInteractionMode } from "./interaction-mode"

describe("interaction-mode", () => {
  it("maps the Web UI mode to the workflow's token", () => {
    expect(interactionToken("vibe")).toBe("Interaction mode: fast")
    expect(interactionToken("spec")).toBe("Interaction mode: dialogue")
    expect(interactionToken("separated")).toBe("Interaction mode: dialogue")
    expect(interactionToken("single")).toBe("Interaction mode: dialogue")
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
})
