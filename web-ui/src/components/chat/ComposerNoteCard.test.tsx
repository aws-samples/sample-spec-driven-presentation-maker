// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it } from "vitest"
import { cleanup, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { ComposerNoteCard } from "./ComposerNoteCard"

afterEach(cleanup)

describe("ComposerNoteCard", () => {
  it("shows a composer's report with its group and slides", () => {
    renderWithIntl(<ComposerNoteCard direction="from" group={2} slugs="intro, agenda" text="Applied the blue theme." />)
    const note = screen.getByRole("note", { name: "Message with composer 2" })
    expect(note.textContent).toContain("Composer 2")
    expect(note.textContent).toContain("intro, agenda")
    expect(note.textContent).toContain("Applied the blue theme.")
  })

  it("shows a message to a composer", () => {
    renderWithIntl(<ComposerNoteCard direction="to" group={1} text="Use blue." />)
    expect(screen.getByRole("note").textContent).toContain("To composer 1")
  })

  it.each([
    ["from" as const, "コンポーザー 3"],
    ["to" as const, "コンポーザー 3 へ"],
  ])("labels the %s direction in Japanese", (direction, label) => {
    renderWithIntl(<ComposerNoteCard direction={direction} group={3} text="x" />, { locale: "ja" })
    const note = screen.getByRole("note", { name: "コンポーザー 3 とのメッセージ" })
    expect(note.textContent).toContain(label)
  })
})
