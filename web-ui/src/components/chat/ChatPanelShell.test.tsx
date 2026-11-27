// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { afterEach, describe, expect, it, vi } from "vitest"
import { forwardRef, useState } from "react"
import { fireEvent, screen } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import { ChatPanelShell } from "./ChatPanelShell"

let instances = 0

// A stand-in ChatPanel: shows its deck and an instance number that survives re-renders,
// so a test can tell a kept conversation from a remounted one.
vi.mock("@/components/chat/ChatPanel", () => ({
  ChatPanel: forwardRef(function FakeChatPanel(
    props: { deckId: string; chatSessionId?: string; onDeckCreated?: (id: string) => void; onBlankChange?: (blank: boolean) => void },
    _ref,
  ) {
    const [id] = useState(() => ++instances)
    return (
      <div data-testid="panel" data-instance={id} data-deck={props.deckId} data-session={props.chatSessionId ?? ""}>
        <button type="button" onClick={() => props.onBlankChange?.(false)}>talk {id}</button>
        <button type="button" onClick={() => props.onDeckCreated?.(`made-by-${id}`)}>create {id}</button>
      </div>
    )
  }),
}))

vi.mock("@/lib/mode", () => ({ IS_LOCAL: false }))
vi.mock("@/services/localService", () => ({ stopLocalAgent: vi.fn() }))

afterEach(() => {
  instances = 0
})

function shown() {
  const panel = screen.getAllByTestId("panel").find((el) => !el.parentElement?.classList.contains("hidden"))
  if (!panel) throw new Error("no panel shown")
  return { instance: panel.dataset.instance, deck: panel.dataset.deck, session: panel.dataset.session }
}

function shell(deckId: string | null, extra: Partial<React.ComponentProps<typeof ChatPanelShell>> = {}) {
  return <ChatPanelShell open onClose={() => {}} deckId={deckId} {...extra} />
}

describe("ChatPanelShell", () => {
  it("keeps the home conversation while a deck is open and shows it again on the home screen", () => {
    const view = renderWithIntl(shell(null))
    const home = shown()
    expect(home.deck).toBe("new")

    view.rerender(shell("d1", { chatSessionId: "s1" }))
    expect(shown()).toMatchObject({ deck: "d1", session: "s1" })
    expect(screen.getAllByTestId("panel").some((el) => el.dataset.instance === home.instance)).toBe(true)

    view.rerender(shell(null))
    expect(shown().instance).toBe(home.instance)
  })

  it("turns the home conversation into the deck's chat when it creates a deck, before the page catches up", () => {
    const onDeckCreated = vi.fn()
    const view = renderWithIntl(shell(null, { onDeckCreated }))
    const home = shown()

    fireEvent.click(screen.getByRole("button", { name: `create ${home.instance}` }))
    const made = `made-by-${home.instance}`
    expect(onDeckCreated).toHaveBeenCalledWith(made)
    expect(shown()).toMatchObject({ instance: home.instance, deck: made })

    // The page opens the new deck; its stored session must not replace the running conversation.
    view.rerender(shell(made, { chatSessionId: "stored", onDeckCreated }))
    expect(shown()).toMatchObject({ instance: home.instance, deck: made, session: "" })

    // Home starts blank with a new conversation.
    view.rerender(shell(null, { onDeckCreated }))
    expect(shown().instance).not.toBe(home.instance)
    expect(shown().deck).toBe("new")
  })

  it("follows a deck its own conversation creates without remounting", () => {
    const view = renderWithIntl(shell("d1"))
    const deck = shown()
    fireEvent.click(screen.getByRole("button", { name: `create ${deck.instance}` }))
    expect(shown()).toMatchObject({ instance: deck.instance, deck: `made-by-${deck.instance}` })
    view.rerender(shell(`made-by-${deck.instance}`))
    expect(shown().instance).toBe(deck.instance)
  })

  it("loads a fresh conversation for each deck opened", () => {
    const view = renderWithIntl(shell("d1"))
    const first = shown()
    view.rerender(shell("d2"))
    expect(shown().deck).toBe("d2")
    expect(shown().instance).not.toBe(first.instance)
  })

  it("clears the home conversation only with New chat", () => {
    const view = renderWithIntl(shell(null, { stageAllowed: true }))
    const home = shown()
    fireEvent.click(screen.getByRole("button", { name: `talk ${home.instance}` }))
    expect(document.querySelector("[data-layout]")?.getAttribute("data-layout")).toBe("center")

    view.rerender(shell("d1"))
    view.rerender(shell(null, { stageAllowed: true }))
    expect(shown().instance).toBe(home.instance)

    fireEvent.click(screen.getByRole("button", { name: "New chat" }))
    expect(shown().instance).not.toBe(home.instance)
    expect(document.querySelector("[data-layout]")?.getAttribute("data-layout")).toBe("stage")
  })

  it("has no tabs or new chat button in the deck's sheet", () => {
    renderWithIntl(shell("d1"))
    expect(screen.queryByRole("button", { name: /New chat|New$|Start new chat/ })).toBeNull()
    expect(screen.getByRole("button", { name: "Close chat panel" })).toBeTruthy()
  })
})
