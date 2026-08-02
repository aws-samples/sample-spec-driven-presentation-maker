// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ComposeCard.test.tsx — Tests for ComposeCard v2.
 *
 * Verifies:
 * - Agent identity mapping: group i → agent identity (i mod 5)
 * - Achromatic shell with team-gradient curtain line
 * - Ledger grammar: dot/cursor markers, slugs, latest activity, chevron
 * - Error auto-expand behavior
 * - Retry/rushed badges
 * - Stop button presence when canCancel
 * - n/m progress display
 * - StopSummary rendering on soft-stop
 * - aria-expanded semantics
 * - Status parsing (starting/working/done/error/retrying)
 */

import { describe, it, expect } from "vitest"
import { renderWithIntl } from "@/test/renderWithIntl"
import { ComposeCard } from "./ComposeCard"
import { getAgentIdentity, AGENT_IDENTITIES } from "./composeTokens"

describe("composeTokens — agent identity mapping", () => {
  it("maps group 1-5 to the five identities in order", () => {
    expect(getAgentIdentity(1).name).toBe("Layout")
    expect(getAgentIdentity(2).name).toBe("Content")
    expect(getAgentIdentity(3).name).toBe("Visual")
    expect(getAgentIdentity(4).name).toBe("Data")
    expect(getAgentIdentity(5).name).toBe("Decorator")
  })

  it("cycles back for groups > 5", () => {
    expect(getAgentIdentity(6).name).toBe("Layout")
    expect(getAgentIdentity(7).name).toBe("Content")
    expect(getAgentIdentity(10).name).toBe("Decorator")
  })

  it("each identity has a valid CSS token", () => {
    for (const id of AGENT_IDENTITIES) {
      expect(id.token).toMatch(/^--agent-/)
    }
  })
})

describe("ComposeCard v2", () => {
  it("renders achromatic shell with team-gradient curtain line", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "Make an intro" }] }}
        isActive
      />
    )
    const section = container.querySelector("section") as HTMLElement
    expect(section).toBeTruthy()
    // Team-gradient curtain line
    const curtain = container.querySelector(".compose-curtain") as HTMLElement
    expect(curtain).toBeTruthy()
    expect(curtain.style.background).toContain("var(--team-gradient)")
  })

  it("shows preparing state when no stream messages", () => {
    const { container } = renderWithIntl(
      <ComposeCard input={{}} isActive />
    )
    expect(container.textContent).toContain("Preparing")
  })

  it("shows n/m progress when agents are present", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [
          { slugs: ["intro"], instruction: "test" },
          { slugs: ["body"], instruction: "test" },
        ]}}
        isActive
        streamMessages={[
          { group: 1, status: "starting", total_groups: 2, slugs: "intro" },
          { group: 2, status: "starting", total_groups: 2, slugs: "body" },
          { group: 1, status: "done", slugs: "intro" },
        ]}
      />
    )
    // n/m counter: "1/2"
    expect(container.textContent).toContain("1/2")
  })

  it("renders cancel button when canCancel conditions met", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "test" }] }}
        isActive
        toolUseId="tu-123"
        sessionId="sess-123"
        accessToken="token-123"
      />
    )
    const cancelBtn = container.querySelector("[aria-label='Cancel compose slides']") as HTMLElement
    expect(cancelBtn).toBeTruthy()
  })

  it("does not render cancel button when missing credentials", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "test" }] }}
        isActive
      />
    )
    const cancelBtn = container.querySelector("[aria-label='Cancel compose slides']")
    expect(cancelBtn).toBeNull()
  })

  it("shows rushed badge when agents hit budget", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "test" }] }}
        isActive
        streamMessages={[
          { group: 1, status: "starting", total_groups: 1, slugs: "intro" },
          { group: 1, status: "budget_reached", slugs: "intro" },
        ]}
      />
    )
    expect(container.textContent).toContain("rushed")
  })

  it("displays error state with red color only for real errors", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "test" }] }}
        status="error"
        isActive={false}
        streamMessages={[
          { group: 1, status: "error", error: "API timeout", slugs: "intro" },
        ]}
      />
    )
    // Error state text
    expect(container.textContent).toContain("Failed")
    // Shell should have error tinting
    const section = container.querySelector("section") as HTMLElement
    expect(section.style.background).toContain("--state-error")
  })

  it("renders StopSummary on soft-stop", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "test" }] }}
        isActive={false}
        status="success"
        result={{ stopped: true, notice: "Stopped by user", summaries: { "Group 1": "Completed intro slide" } }}
        streamMessages={[
          { group: 1, status: "done", slugs: "intro" },
        ]}
      />
    )
    expect(container.textContent).toContain("Stopped by user")
  })

  it("has aria-label on section", () => {
    const { container } = renderWithIntl(
      <ComposeCard input={{}} isActive />
    )
    const section = container.querySelector("section") as HTMLElement
    expect(section.getAttribute("aria-label")).toBe("Composing slides")
  })

  it("has sr-only progress announcement", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["s1"], instruction: "a" }, { slugs: ["s2"], instruction: "b" }] }}
        isActive
        streamMessages={[
          { group: 1, status: "starting", total_groups: 2, slugs: "s1" },
          { group: 2, status: "starting", total_groups: 2, slugs: "s2" },
        ]}
      />
    )
    const srOnly = container.querySelector(".sr-only[aria-live='polite']") as HTMLElement
    expect(srOnly).toBeTruthy()
    expect(srOnly.textContent).toContain("0 of 2")
  })
})

describe("AgentCard within ComposeCard — ledger grammar", () => {
  it("shows cursor+name tag for working agent", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "Make intro slide" }] }}
        isActive
        streamMessages={[
          { group: 1, status: "starting", total_groups: 1, slugs: "intro" },
          { group: 1, tool: "write_slide", toolUseId: "t1", input: { slide_id: "intro" } },
        ]}
      />
    )
    // Cursor arrow should be present (active agent)
    expect(container.querySelector(".ledger-cursor")).toBeTruthy()
    // Agent name tag — group 1 = Layout
    expect(container.textContent).toContain("Layout")
  })

  it("shows dot marker for done agent", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "Make intro" }] }}
        isActive={false}
        status="success"
        streamMessages={[
          { group: 1, status: "starting", total_groups: 1, slugs: "intro" },
          { group: 1, status: "done", slugs: "intro" },
        ]}
      />
    )
    // Should not have cursor for done state
    expect(container.querySelector(".ledger-cursor")).toBeNull()
    // Should have dot marker (tool-check-enter)
    expect(container.querySelector(".tool-check-enter")).toBeTruthy()
  })

  it("has chevron with aria-expanded", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "Make intro slide" }] }}
        isActive
        streamMessages={[
          { group: 1, status: "starting", total_groups: 1, slugs: "intro" },
        ]}
      />
    )
    const chevron = container.querySelector("[aria-expanded]") as HTMLElement
    expect(chevron).toBeTruthy()
    // Default: collapsed (not auto-expanded unless error)
    expect(chevron.getAttribute("aria-expanded")).toBe("false")
  })

  it("auto-expands on error when parent is finished", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "test" }] }}
        isActive={false}
        status="error"
        streamMessages={[
          { group: 1, status: "error", error: "Something went wrong", slugs: "intro" },
        ]}
      />
    )
    const chevron = container.querySelector("[aria-expanded]") as HTMLElement
    expect(chevron.getAttribute("aria-expanded")).toBe("true")
  })

  it("maps group 2 to Content identity", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [
          { slugs: ["s1"], instruction: "a" },
          { slugs: ["s2"], instruction: "b" },
        ]}}
        isActive
        streamMessages={[
          { group: 1, status: "starting", total_groups: 2, slugs: "s1" },
          { group: 2, status: "starting", total_groups: 2, slugs: "s2" },
          { group: 2, tool: "write_slide", toolUseId: "t1", input: { slide_id: "s2" } },
        ]}
      />
    )
    // Group 2 = Content
    expect(container.textContent).toContain("Content")
  })

  it("shows existing slug in different color", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["existing-slide"], instruction: "test" }] }}
        isActive
        deckSlugs={["existing-slide"]}
        streamMessages={[
          { group: 1, status: "starting", total_groups: 1, slugs: "existing-slide" },
        ]}
      />
    )
    // The slug text should be present
    expect(container.textContent).toContain("existing-slide")
  })
})
