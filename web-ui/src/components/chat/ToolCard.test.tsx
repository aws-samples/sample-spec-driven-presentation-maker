// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ToolCard.test.tsx — Tests for the work-ledger style ToolCard components.
 *
 * Verifies:
 * - 4 states: active, success, error, compact (muted)
 * - getDetail → getResultSummary transition
 * - Accessibility: role="status", aria-label, aria-live on completion
 * - Category→agent color mapping (marker presence)
 * - Active state shows cursor arrow + agent name tag
 * - Error state uses reserved red
 * - Compact shows small muted dot
 */

import { describe, it, expect } from "vitest"
import { renderWithIntl } from "@/test/renderWithIntl"
import { ToolCard, ToolCardCompact, TOOL_META, stripPrefix } from "./ToolCard"

describe("ToolCard", () => {
  it("renders active state with cursor marker and agent name tag", () => {
    const { container } = renderWithIntl(
      <ToolCard name="write_slide" input={{ slide_id: "intro" }} isActive />
    )
    const el = container.querySelector("[role='status']") as HTMLElement
    expect(el).toBeTruthy()
    // aria-label should mention "Running"
    expect(el.getAttribute("aria-label")).toContain("Running")
    expect(el.getAttribute("aria-label")).toContain("Writing slide")
    expect(el.getAttribute("aria-label")).toContain("intro")
    // Active state renders the cursor on the continuous ledger rail.
    expect(el.classList.contains("ledger-row")).toBe(true)
    expect(container.querySelector(".ledger-marker")).toBeTruthy()
    expect(container.querySelector(".ledger-cursor.ledger-cursor-active")).toBeTruthy()
    // Concrete tool action complements the semantic category color.
    expect(container.querySelector("svg.lucide-pencil")).toBeTruthy()
    // Agent name tag should show "Content" (build category → Content agent)
    expect(el.textContent).toContain("Content")
  })

  it("renders success state with done dot and result summary", () => {
    const { container } = renderWithIntl(
      <ToolCard
        name="generate_pptx"
        input={{ path: "/deck/my-prez.pptx" }}
        status="success"
        result={{ s3Key: "s3://bucket/key" }}
      />
    )
    const el = container.querySelector("[role='status']") as HTMLElement
    expect(el).toBeTruthy()
    // Completed state
    expect(el.getAttribute("aria-label")).toContain("Completed")
    expect(el.getAttribute("aria-label")).toContain("Ready")
    // aria-live polite on completion
    expect(el.getAttribute("aria-live")).toBe("polite")
    // Done dot exists, no cursor arrow
    expect(container.querySelector(".ledger-cursor")).toBeNull()
    expect(container.querySelector(".ledger-marker .tool-check-enter")).toBeTruthy()
  })

  it("renders error state with red marker and error text", () => {
    const { container } = renderWithIntl(
      <ToolCard
        name="run_python"
        input={{ code: "print('hello')" }}
        status="error"
        result={{ error: "SyntaxError: unexpected token" }}
      />
    )
    const el = container.querySelector("[role='status']") as HTMLElement
    expect(el).toBeTruthy()
    expect(el.getAttribute("aria-label")).toContain("Failed")
    expect(el.getAttribute("aria-label")).toContain("SyntaxError")
    expect(el.textContent).toContain("SyntaxError")
  })

  it("shows input detail when active", () => {
    const { container } = renderWithIntl(
      <ToolCard name="search_icons" input={{ keyword: "chart" }} isActive />
    )
    const el = container.querySelector("[role='status']") as HTMLElement
    expect(el.textContent).toContain('"chart"')
  })

  it("shows result summary when complete", () => {
    const { container } = renderWithIntl(
      <ToolCard name="search_icons" input={{ keyword: "chart" }} status="success" result={{ results: [{}, {}, {}] }} />
    )
    const el = container.querySelector("[role='status']") as HTMLElement
    expect(el.textContent).toContain("3 found")
    expect(el.textContent).toContain("→")
    expect(el.querySelector("p")).toBeNull()
  })

  it("dispatches compose_slides to ComposeCard", () => {
    const { container } = renderWithIntl(
      <ToolCard name="compose_slides" input={{ purpose: "test" }} isActive />
    )
    // ComposeCard does not render the ledger-marker
    expect(container.querySelector(".ledger-marker")).toBeNull()
  })

  it("does not set aria-live on active (not yet complete)", () => {
    const { container } = renderWithIntl(
      <ToolCard name="get_deck" input={{ deck_id: "x" }} isActive />
    )
    const el = container.querySelector("[role='status']") as HTMLElement
    expect(el.getAttribute("aria-live")).toBeNull()
  })
})

describe("ToolCardCompact", () => {
  it("renders with muted dot and label", () => {
    const { container } = renderWithIntl(
      <ToolCardCompact name="get_deck" input={{ deck_id: "abc123" }} />
    )
    const el = container.querySelector(".ledger-compact")
    expect(el).toBeTruthy()
    expect(el!.textContent).toContain("Loading deck")
  })

  it("shows truncated detail for long inputs", () => {
    const { container } = renderWithIntl(
      <ToolCardCompact name="read_reference" input={{ path: "/very/long/path/to/some/reference/file.md" }} />
    )
    const el = container.querySelector(".ledger-compact")
    expect(el!.textContent).toContain("file.md")
  })

  it("renders small muted dot marker with agent color", () => {
    const { container } = renderWithIntl(
      <ToolCardCompact name="run_python" input={{}} />
    )
    // The muted dot marker
    const dot = container.querySelector(".ledger-compact span[aria-hidden='true']") as HTMLElement
    expect(dot).toBeTruthy()
    // compute → Layout color
    expect(dot.style.background).toContain("--agent-layout")
  })
})

describe("stripPrefix", () => {
  it("strips spec_driven_presentation_maker_ prefix", () => {
    expect(stripPrefix("spec_driven_presentation_maker_run_python")).toBe("run_python")
  })
  it("leaves non-prefixed names unchanged", () => {
    expect(stripPrefix("write_slide")).toBe("write_slide")
  })
})

describe("TOOL_META", () => {
  it("maps all categories correctly to agents", () => {
    expect(TOOL_META.write_slide.category).toBe("build")
    expect(TOOL_META.search_icons.category).toBe("explore")
    expect(TOOL_META.generate_pptx.category).toBe("produce")
    expect(TOOL_META.run_python.category).toBe("compute")
    expect(TOOL_META.hearing.category).toBe("hearing")
  })
})
