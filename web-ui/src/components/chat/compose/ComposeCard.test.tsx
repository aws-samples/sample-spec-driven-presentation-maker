// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it } from "vitest"
import { cleanup, fireEvent, screen, within } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { ComposeCard } from "./ComposeCard"
import { ChatMessage } from "../ChatMessage"
import { parseComposeState } from "./parseComposeState"
import { activityCategory } from "./activityLabel"

afterEach(cleanup)

const twoGroups = {
  slide_groups: [
    { slugs: ["intro"], instruction: "Make an intro" },
    { slugs: ["body"], instruction: "Make the body" },
  ],
}

const twoStarted = [
  { group: 1, status: "starting", total_groups: 2, slugs: "intro" },
  { group: 2, status: "starting", total_groups: 2, slugs: "body" },
]

describe("ComposeCard production board", () => {
  it("renders the team curtain and observable production heading", () => {
    const { container } = renderWithIntl(
      <ComposeCard input={twoGroups} isActive streamMessages={twoStarted} />
    )
    const curtain = container.querySelector(".compose-curtain") as HTMLElement
    expect(curtain.style.background).toContain("var(--team-gradient)")
    expect(container.textContent).toContain("2 slides in production")
    expect(container.textContent).toContain("2 parallel lanes")
  })

  it("shows preparing state before agents are known", () => {
    const { container } = renderWithIntl(<ComposeCard input={{}} isActive />)
    expect(container.textContent).toContain("Preparing")
  })

  it("measures slide creation by composer completion, not tool completion", () => {
    renderWithIntl(
      <ComposeCard
        input={twoGroups}
        isActive
        streamMessages={[...twoStarted, { group: 1, status: "done", slugs: "intro" }]}
      />
    )
    const progress = screen.getByRole("progressbar", { name: "Slide creation" })
    expect(progress.getAttribute("aria-valuenow")).toBe("1")
    expect(progress.getAttribute("aria-valuemax")).toBe("2")
    expect(screen.getByText("1 / 2 created")).toBeTruthy()
  })

  it("shows finishing status when all composers are done but the tool is active", () => {
    renderWithIntl(
      <ComposeCard
        input={twoGroups}
        isActive
        streamMessages={[
          ...twoStarted,
          { group: 1, status: "done", slugs: "intro" },
          { group: 2, status: "done", slugs: "body" },
        ]}
      />
    )
    expect(screen.getByText("Finishing presentation…")).toBeTruthy()
  })

  it("ignores pre-existing slide files: nothing is created until a composer finishes", () => {
    renderWithIntl(<ComposeCard input={twoGroups} isActive streamMessages={twoStarted} />)
    const progress = screen.getByRole("progressbar", { name: "Slide creation" })
    expect(progress.getAttribute("aria-valuenow")).toBe("0")
    expect(screen.queryAllByLabelText("Slide created")).toHaveLength(0)
  })

  it("settles every lane when the tool completes without stream updates", () => {
    renderWithIntl(<ComposeCard input={twoGroups} status="success" isActive={false} />)
    expect(screen.queryByText("Queued")).toBeNull()
    expect(screen.getAllByText("1/1 created")).toHaveLength(2)
  })

  it("has no stop control of its own: only lane toggles are buttons", () => {
    renderWithIntl(<ComposeCard input={twoGroups} isActive streamMessages={twoStarted} />)
    const buttons = screen.getAllByRole("button")
    expect(buttons).toHaveLength(2)
    buttons.forEach((button) => expect(button.getAttribute("aria-label")).toBe("Expand details"))
  })

  it("shows real error state", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "test" }] }}
        status="error"
        isActive={false}
        streamMessages={[
          { group: 1, status: "starting", total_groups: 1, slugs: "intro" },
          { group: 1, status: "error", error: "API timeout", slugs: "intro" },
        ]}
      />
    )
    expect(container.textContent).toContain("Failed")
    expect((container.querySelector("section") as HTMLElement).style.background).toContain("--state-error")
  })

  it("keeps lane order neutral and does not expose invented roles", () => {
    const { container } = renderWithIntl(
      <ComposeCard input={twoGroups} isActive streamMessages={twoStarted} />
    )
    expect(screen.getByText("01")).toBeTruthy()
    expect(screen.getByText("02")).toBeTruthy()
    expect(container.textContent).not.toContain("Layout")
    expect(container.textContent).not.toContain("Content")
  })

  it("allows exactly one manually expanded history", () => {
    renderWithIntl(<ComposeCard input={twoGroups} isActive streamMessages={twoStarted} />)
    const expand = screen.getAllByLabelText("Expand details")
    fireEvent.click(expand[0])
    expect(expand[0].getAttribute("aria-expanded")).toBe("true")

    fireEvent.click(expand[1])
    expect(expand[0].getAttribute("aria-expanded")).toBe("false")
    expect(expand[1].getAttribute("aria-expanded")).toBe("true")
  })

  it("marks each slug of a finished composer with a neutral created check", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={twoGroups}
        isActive
        streamMessages={[...twoStarted, { group: 1, status: "done", slugs: "intro" }]}
      />
    )
    expect(container.querySelectorAll("[aria-label='Slide created']")).toHaveLength(1)
    expect(screen.getByText("intro").className).toContain("font-semibold")
  })

  it("shows latest tool icon and semantic category color while collapsed", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["intro"], instruction: "test" }] }}
        isActive
        streamMessages={[
          { group: 1, status: "starting", total_groups: 1, slugs: "intro" },
          { group: 1, tool: "write_slide", toolUseId: "t1", input: { slide_id: "intro" } },
        ]}
      />
    )
    expect(container.textContent).toContain("Writing slide · intro")
    const lane = screen.getByLabelText("Expand details")
    const latest = within(lane).getByText("Writing slide · intro").parentElement as HTMLElement
    expect(latest.querySelector("svg")).toBeTruthy()
    expect(latest.style.color).toContain("--agent-content")
  })

  it("shows compact previous failure and current retry history", () => {
    renderWithIntl(
      <ComposeCard
        input={{ slide_groups: [{ slugs: ["forecast"], instruction: "test" }] }}
        isActive
        streamMessages={[
          { group: 1, status: "starting", total_groups: 1, slugs: "forecast" },
          { group: 1, tool: "run_python", toolUseId: "t1", input: {} },
          { group: 1, status: "retrying", attempt: 2, error: "Merged heading", slugs: "forecast" },
          { group: 1, tool: "read_reference", toolUseId: "t2", input: { path: "forecast.csv" } },
        ]}
      />
    )
    fireEvent.click(screen.getByLabelText("Expand details"))
    expect(screen.getByText("Previous attempt failed")).toBeTruthy()
    expect(screen.getByText("Merged heading")).toBeTruthy()
    expect(screen.getByText("Current attempt · Retry 2")).toBeTruthy()
    expect(screen.getAllByText("Reading reference").length).toBeGreaterThan(0)
  })

  it("announces created slide progress", () => {
    const { container } = renderWithIntl(
      <ComposeCard
        input={twoGroups}
        isActive
        streamMessages={[...twoStarted, { group: 1, status: "done", slugs: "intro" }]}
      />
    )
    const live = container.querySelector(".sr-only[aria-live='polite']") as HTMLElement
    expect(live.textContent).toContain("1 of 2 slides created")
  })
})

describe("background compose card in a chat message", () => {
  const tool = {
    toolUseId: "c1", name: "compose_slides", input: twoGroups, streamMessages: twoStarted,
    task: { id: "t-1", state: "running" as const },
  }
  const message = (props: { sessionWorking: boolean; isStreaming?: boolean }) => (
    <ChatMessage role="assistant" content="Composing." toolUses={[tool]}
      blocks={[{ type: "text", text: "Composing." }, { type: "tool", tool }]} {...props} />
  )

  it("is active while the session works, even when its message no longer streams", () => {
    renderWithIntl(message({ sessionWorking: true }))
    expect(screen.getByText("2 slides in production")).toBeTruthy()
    expect(screen.queryByText("Stopped")).toBeNull()
  })

  it("shows stopped when the session went idle without a task end", () => {
    renderWithIntl(message({ sessionWorking: false }))
    expect(screen.getAllByText("Stopped").length).toBeGreaterThan(0)
    expect(screen.queryByText("2 slides in production")).toBeNull()
  })
})

describe("observable compose state", () => {
  it("counts repeated done events once per terminal lane", () => {
    const state = parseComposeState([
      { group: 1, status: "starting", total_groups: 1, slugs: "intro" },
      { group: 1, status: "done", slugs: "intro" },
      { group: 1, status: "done", slugs: "intro" },
    ])
    expect(state.doneGroupCount).toBe(1)
  })

  it("retains only the previous retry failure summary", () => {
    const state = parseComposeState([
      { group: 1, status: "starting", total_groups: 1, slugs: "intro" },
      { group: 1, tool: "run_python", toolUseId: "old", input: {} },
      { group: 1, status: "retrying", attempt: 2, error: "First attempt failed", slugs: "intro" },
      { group: 1, tool: "read_reference", toolUseId: "current", input: {} },
    ])
    expect(state.agents[0].previousAttemptError).toBe("First attempt failed")
    expect(state.agents[0].activity.map((activity) => activity.toolUseId)).toEqual(["current"])
  })

  it("maps actual tools to semantic history colors", () => {
    expect(activityCategory("write_slide")).toBe("build")
    expect(activityCategory("read_reference")).toBe("explore")
    expect(activityCategory("grid")).toBe("compute")
    expect(activityCategory("generate_pptx")).toBe("produce")
  })
})
