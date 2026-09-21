// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { cleanup, render, waitFor } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import { DeckDefs, type DeckDefsStatus } from "./DeckDefs"

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it("reports loaded only after defs are mounted and clears them when the URL changes", async () => {
  vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ version: 1, defs: `<defs id="${String(input)}" />` }),
  })))
  const statuses: DeckDefsStatus[] = []
  const rendered = render(<DeckDefs defsUrl="/first.json" onStatusChange={(status) => statuses.push(status)} />)

  await waitFor(() => expect(statuses.at(-1)).toBe("loaded"))
  expect(rendered.container.querySelector("svg")?.innerHTML).toContain("/first.json")

  rendered.rerender(<DeckDefs defsUrl="/second.json" onStatusChange={(status) => statuses.push(status)} />)
  await waitFor(() => expect(statuses.at(-1)).toBe("loaded"))
  expect(statuses).toContain("loading")
  expect(rendered.container.querySelector("svg")?.innerHTML).toContain("/second.json")
  expect(rendered.container.querySelector("svg")?.innerHTML).not.toContain("/first.json")
})

it("reports an error without claiming deck defs are ready", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: false })))
  const statuses: DeckDefsStatus[] = []
  render(<DeckDefs defsUrl="/missing.json" onStatusChange={(status) => statuses.push(status)} />)

  await waitFor(() => expect(statuses.at(-1)).toBe("error"))
  expect(statuses).not.toContain("loaded")
})
