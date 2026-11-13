// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * HearingCard shows one question at a time: header chips, option rows with an automatic
 * "Other", single select moving on by itself, keys once the card has focus, and an
 * answered summary after submit or when the user replied in chat. ChatMessage renders it
 * for current and older `hearing` inputs.
 */

import { act, cleanup, fireEvent, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { renderWithIntl } from "@/test/renderWithIntl"

vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { dismiss: vi.fn() }) }))
vi.mock("@/services/deckService", () => ({ batchGetSlidePreviewUrls: vi.fn(async () => new Map()) }))

import { HearingCard } from "./HearingCard"
import { ChatMessage } from "./ChatMessage"
import { normalizeHearingInput, type HearingQuestion } from "./hearingQuestions"

const QUESTIONS: HearingQuestion[] = normalizeHearingInput({
  q0: {
    header: "Audience", type: "single_select", text: "Who is it for?",
    options: [
      { label: "Executives", description: "Key numbers first", recommended: true },
      { label: "Engineers", description: "Implementation detail" },
    ],
  },
  q1: {
    header: "Elements", type: "multi_select", text: "What goes in?",
    options: [
      { label: "Diagram", description: "One-page overview", recommended: true },
      { label: "Costs", description: "Monthly estimate" },
    ],
  },
  q2: { header: "Must cover", type: "free_text", text: "Anything to cover?", placeholder: "e.g. migration cost" },
})

const card = () => screen.getByRole("form", { name: "Agent questions" })
const advanceTimers = () => act(() => { vi.advanceTimersByTime(300) })

function renderCard(props: Partial<Parameters<typeof HearingCard>[0]> = {}) {
  const onSubmit = vi.fn()
  const view = renderWithIntl(<HearingCard questions={QUESTIONS} onSubmit={onSubmit} {...props} />)
  return { onSubmit, ...view }
}

describe("HearingCard", () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it("shows every header as a chip and only the current question", () => {
    renderCard()
    const chips = screen.getByRole("group", { name: "Questions" })
    expect(chips.textContent).toContain("Audience")
    expect(chips.textContent).toContain("Elements")
    expect(chips.textContent).toContain("Must cover")
    expect(screen.getByText("Who is it for?")).toBeTruthy()
    expect(screen.queryByText("What goes in?")).toBeNull()
    expect(screen.getByRole("button", { name: /Audience/ }).getAttribute("aria-current")).toBe("step")
    expect(screen.getByText("Pick one to go on")).toBeTruthy()
    expect(screen.getByText("1 / 3")).toBeTruthy()
  })

  it("does not take focus when it appears", () => {
    renderCard()
    expect(document.activeElement).toBe(document.body)
  })

  it("moves on after a single-select pick", () => {
    renderCard()
    fireEvent.click(screen.getByRole("radio", { name: /^Executives/ }))
    expect(screen.getByText("Who is it for?")).toBeTruthy()
    advanceTimers()
    expect(screen.getByText("What goes in?")).toBeTruthy()
    expect(screen.getByRole("button", { name: /Audience/ }).hasAttribute("data-done")).toBe(true)
  })

  it("stays on a multi-select question until Next", () => {
    renderCard()
    fireEvent.click(screen.getByRole("button", { name: /Elements/ }))
    expect(screen.getByText("Select any · Enter for next")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Skip" })).toBeTruthy()
    fireEvent.click(screen.getByRole("checkbox", { name: /^Diagram/ }))
    fireEvent.click(screen.getByRole("checkbox", { name: /^Costs/ }))
    advanceTimers()
    expect(screen.getByText("What goes in?")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Next" }))
    expect(screen.getByText("Anything to cover?")).toBeTruthy()
  })

  it("skips an unanswered question and goes back", () => {
    renderCard()
    expect(screen.getByRole("button", { name: "Back" })).toHaveProperty("disabled", true)
    fireEvent.click(screen.getByRole("button", { name: "Skip" }))
    expect(screen.getByText("What goes in?")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Back" }))
    expect(screen.getByText("Who is it for?")).toBeTruthy()
  })

  it("opens a focused field for Other, exclusive in single select", () => {
    renderCard()
    fireEvent.click(screen.getByRole("radio", { name: /^Executives/ }))
    fireEvent.click(screen.getByRole("radio", { name: /^Other/ }))
    advanceTimers()
    expect(screen.getByText("Who is it for?")).toBeTruthy()
    const field = screen.getByRole("textbox", { name: "Who is it for? — Other" })
    expect(document.activeElement).toBe(field)
    expect(screen.getByRole("radio", { name: /^Executives/ }).getAttribute("aria-checked")).toBe("false")
    expect(screen.getByRole("radio", { name: /^Other/ }).getAttribute("aria-checked")).toBe("true")
  })

  it("combines Other with options in multi select", () => {
    const { onSubmit } = renderCard({ questions: [QUESTIONS[1]] })
    fireEvent.click(screen.getByRole("checkbox", { name: /^Costs/ }))
    fireEvent.click(screen.getByRole("checkbox", { name: /^Other/ }))
    fireEvent.change(screen.getByRole("textbox", { name: "What goes in? — Other" }), { target: { value: "Timeline" } })
    expect(screen.getByRole("checkbox", { name: /^Costs/ }).getAttribute("aria-checked")).toBe("true")
    fireEvent.click(screen.getByRole("button", { name: "Submit" }))
    expect(onSubmit).toHaveBeenCalledWith("What goes in?: Costs, Timeline")
  })

  it("picks with number keys once the card has focus, not inside the Other field", () => {
    renderCard()
    card().focus()
    fireEvent.keyDown(card(), { key: "2" })
    expect(screen.getByRole("radio", { name: /^Engineers/ }).getAttribute("aria-checked")).toBe("true")
    fireEvent.keyDown(card(), { key: "3" })
    const field = screen.getByRole("textbox", { name: "Who is it for? — Other" })
    fireEvent.keyDown(field, { key: "1" })
    expect(screen.getByRole("radio", { name: /^Executives/ }).getAttribute("aria-checked")).toBe("false")
    fireEvent.change(field, { target: { value: "Partners" } })
    fireEvent.keyDown(field, { key: "Enter" })
    expect(screen.getByText("What goes in?")).toBeTruthy()
  })

  it("moves on with Enter on the card", () => {
    renderCard()
    card().focus()
    fireEvent.keyDown(card(), { key: "Enter" })
    expect(screen.getByText("What goes in?")).toBeTruthy()
  })

  it("keeps focus in the card when a picked row moves on, so keys still work", () => {
    renderCard()
    const row = screen.getByRole("radio", { name: /^Engineers/ })
    row.focus()
    fireEvent.click(row)
    advanceTimers()
    expect(screen.getByText("What goes in?")).toBeTruthy()
    expect(document.activeElement).toBe(card())
    fireEvent.keyDown(card(), { key: "1" })
    expect(screen.getByRole("checkbox", { name: /^Diagram/ }).getAttribute("aria-checked")).toBe("true")
  })

  it("keeps focus in the card when Enter in the Other field moves on", () => {
    renderCard()
    card().focus()
    fireEvent.keyDown(card(), { key: "3" })
    const field = screen.getByRole("textbox", { name: "Who is it for? — Other" })
    fireEvent.change(field, { target: { value: "Partners" } })
    fireEvent.keyDown(field, { key: "Enter" })
    expect(document.activeElement).toBe(card())
    fireEvent.keyDown(card(), { key: "2" })
    expect(screen.getByRole("checkbox", { name: /^Costs/ }).getAttribute("aria-checked")).toBe("true")
  })

  it("does not take focus on a step change when focus was outside the card", () => {
    renderCard()
    fireEvent.click(screen.getByRole("radio", { name: /^Engineers/ }))
    advanceTimers()
    expect(screen.getByText("What goes in?")).toBeTruthy()
    expect(document.activeElement).toBe(document.body)
  })

  it("cannot submit with no answers", () => {
    const { onSubmit } = renderCard({ questions: [QUESTIONS[2]] })
    expect(screen.getByRole("button", { name: "Submit" })).toHaveProperty("disabled", true)
    fireEvent.keyDown(card(), { key: "Enter", ctrlKey: true })
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it("submits with the button and collapses to the summary with — for skipped", () => {
    const { onSubmit } = renderCard()
    fireEvent.click(screen.getByRole("radio", { name: /^Engineers/ }))
    advanceTimers()
    fireEvent.click(screen.getByRole("checkbox", { name: /^Diagram/ }))
    fireEvent.click(screen.getByRole("checkbox", { name: /^Other/ }))
    fireEvent.change(screen.getByRole("textbox", { name: "What goes in? — Other" }), { target: { value: "other text" } })
    fireEvent.click(screen.getByRole("button", { name: "Next" }))
    fireEvent.click(screen.getByRole("button", { name: "Submit" }))
    expect(onSubmit).toHaveBeenCalledWith("Who is it for?: Engineers\nWhat goes in?: Diagram, other text")
    const summary = screen.getByRole("group", { name: "Answered" })
    expect(summary.textContent).toContain("2 / 3 answered")
    const values = [...summary.querySelectorAll("dd")].map((d) => d.textContent)
    expect(values).toEqual(["Engineers", "Diagram, other text", "—"])
    expect(screen.queryByRole("form")).toBeNull()
  })

  it("submits with Ctrl+Enter from the free-text field", () => {
    const { onSubmit } = renderCard()
    fireEvent.click(screen.getByRole("button", { name: /Must cover/ }))
    const textarea = screen.getByRole("textbox", { name: "Anything to cover?" })
    fireEvent.change(textarea, { target: { value: "Migration" } })
    fireEvent.keyDown(textarea, { key: "Enter" })
    expect(onSubmit).not.toHaveBeenCalled()
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true })
    expect(onSubmit).toHaveBeenCalledWith("Anything to cover?: Migration")
  })

  it("collapses with every answer — when the user replied in chat instead", () => {
    renderCard({ disabled: true })
    const summary = screen.getByRole("group", { name: "Answered" })
    expect(summary.textContent).toContain("0 / 3 answered")
    expect([...summary.querySelectorAll("dd")].map((d) => d.textContent)).toEqual(["—", "—", "—"])
    expect([...summary.querySelectorAll("dt")].map((d) => d.textContent)).toEqual(["Audience", "Elements", "Must cover"])
  })

  it("while streaming, offers no submit and shows a skeleton for a question still arriving", () => {
    const partial = normalizeHearingInput({ q0: { header: "Audience", type: "single_select", text: "Who is it for?", options: [{ label: "A" }] }, q1: { header: "Ele" } })
    renderCard({ questions: [partial[0]], streaming: true })
    expect(screen.queryByRole("button", { name: "Submit" })).toBeNull()
    expect(screen.getByRole("button", { name: "Skip" })).toHaveProperty("disabled", true)
    cleanup()
    renderCard({ questions: partial, streaming: true })
    fireEvent.click(screen.getByRole("button", { name: "Skip" }))
    expect(screen.getByRole("status", { name: "Loading question…" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Submit" })).toBeNull()
  })

  it("renders older questions with the badge and a fallback header", () => {
    renderCard({ questions: normalizeHearingInput({ inference: "Old hypothesis", q0: { type: "single_select", text: "Pick one", options: ["A", "B"], recommended: "A" } }) })
    expect(screen.getByRole("radio", { name: /^A/ }).querySelector(".hearing-rec")?.textContent).toBe("Recommended")
    expect(screen.getByRole("group", { name: "Questions" }).textContent).toContain("Pick one")
    expect(document.body.textContent).not.toContain("Old hypothesis")
  })

  it("speaks Japanese", () => {
    renderWithIntl(<HearingCard questions={QUESTIONS} onSubmit={vi.fn()} />, { locale: "ja" })
    expect(screen.getByText("1 つ選ぶと次へ進みます")).toBeTruthy()
    expect(screen.getByRole("radio", { name: /^Executives/ }).querySelector(".hearing-rec")?.textContent).toBe("おすすめ")
    expect(screen.getByRole("radio", { name: /^その他/ })).toBeTruthy()
  })
})

describe("ChatMessage renders hearing cards", () => {
  afterEach(cleanup)

  const hearingBlock = (input: Record<string, unknown>) => [{ type: "tool" as const, tool: { toolUseId: "t1", name: "hearing", input, status: "success" as const } }]

  it("shows the card for the current input, without inference", () => {
    renderWithIntl(
      <ChatMessage role="assistant" content="" blocks={hearingBlock({ q0: { header: "H", type: "single_select", text: "Q?", options: [{ label: "Yes" }, { label: "No" }] } })} />,
    )
    expect(screen.getByRole("form", { name: "Agent questions" })).toBeTruthy()
    expect(screen.getAllByRole("radio")).toHaveLength(3)
  })

  it("shows older history without its inference", () => {
    renderWithIntl(
      <ChatMessage role="assistant" content="" blocks={hearingBlock({ inference: "Old hypothesis", q0: { type: "single_select", text: "Q?", options: ["Yes", "No"] } })} />,
    )
    expect(screen.getByRole("form", { name: "Agent questions" })).toBeTruthy()
    expect(document.body.textContent).not.toContain("Old hypothesis")
  })
})
