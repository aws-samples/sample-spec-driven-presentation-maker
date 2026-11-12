// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Styles page and the style chat: a new style's chat follows the agent's first save to the
 * style's preview without starting over, and the panel stays as the user left it on every
 * save after that.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { renderWithIntl } from "@/test/renderWithIntl"
import type { StyleEntry } from "@/services/deckService"

type ShellProps = {
  open: boolean
  onClose: () => void
  styleId: string
  onStyleSaved?: (saved: { title?: string; filename: string }) => Promise<void> | void
}

const { shell, listed } = vi.hoisted(() => ({
  shell: { mounts: 0, props: null as null | ShellProps },
  listed: { styles: [] as StyleEntry[] },
}))

vi.mock("@/hooks/useAuth", () => {
  const auth = { isAuthenticated: true, user: { id_token: "tok", profile: { sub: "u1" } } }
  return { useAuth: () => auth }
})
vi.mock("@/hooks/UseMobile", () => ({ useIsMobile: () => false }))
vi.mock("@/services/deckService", () => ({
  createReview: vi.fn(),
  fetchStyles: vi.fn(async () => listed.styles),
  fetchStylePreviewHtml: vi.fn(async () => ""),
  fetchStyleHtml: vi.fn(async () => ""),
  pinStyle: vi.fn(),
  saveUserStyle: vi.fn(async () => ({})),
  deleteUserStyle: vi.fn(async () => ({})),
  renameUserStyle: vi.fn(async () => ({})),
}))
vi.mock("@/components/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock("@/components/StyleSlidePreview", () => ({
  StyleSlidePreview: () => null,
  buildCoverDoc: () => "",
  splitStyleSlides: () => null,
}))
vi.mock("@/components/chat/StyleChatShell", async () => {
  const { useEffect } = await import("react")
  return {
    StyleChatShell: function StyleChatShell(props: ShellProps) {
      useEffect(() => { shell.mounts += 1 }, [])
      shell.props = props
      return (
        <div data-testid="chat" data-open={String(props.open)}>
          <button onClick={props.onClose}>close chat</button>
        </div>
      )
    },
  }
})

import StylesPage from "./page"
import { parseHash } from "@/hooks/useStyleWorkspace"

const chat = () => screen.getByTestId("chat")
const save = async (filename: string) => {
  await act(async () => { await shell.props?.onStyleSaved?.({ filename, title: "Calm review — For quiet reviews" }) })
}

describe("Styles page chat", () => {
  beforeEach(() => {
    window.location.hash = ""
    shell.mounts = 0
    shell.props = null
    listed.styles = []
  })
  afterEach(() => { cleanup() })

  it("follows a new style's first save with the same chat, even before the list has the style", async () => {
    renderWithIntl(<StylesPage />)
    fireEvent.click(await screen.findByRole("button", { name: "Create with AI" }))
    await waitFor(() => expect(chat().dataset.open).toBe("true"))
    expect(shell.props?.styleId).toBe("")

    await save("calm-review.html")

    await waitFor(() => expect(window.location.hash).toBe("#calm-review"))
    await waitFor(() => expect(shell.props?.styleId).toBe("calm-review"))
    expect(screen.getByRole("heading", { name: "calm-review" })).toBeTruthy()
    expect(chat().dataset.open).toBe("true")
    expect(shell.mounts).toBe(1)

    fireEvent.click(screen.getByRole("button", { name: "close chat" }))
    await save("calm-review.html")
    expect(chat().dataset.open).toBe("false")
    expect(window.location.hash).toBe("#calm-review")
    expect(screen.getByRole("button", { name: "Edit with AI" })).toBeTruthy()
  })

  it("leaves a closed panel closed when the agent saves the style being edited", async () => {
    listed.styles = [{ name: "brand-blue", source: "user", pinned: false } as StyleEntry]
    window.location.hash = "#brand-blue"
    renderWithIntl(<StylesPage />)
    fireEvent.click(await screen.findByRole("button", { name: "Edit with AI" }))
    expect(chat().dataset.open).toBe("true")
    fireEvent.click(screen.getByRole("button", { name: "close chat" }))

    await save("brand-blue.html")

    expect(chat().dataset.open).toBe("false")
    expect(window.location.hash).toBe("#brand-blue")
  })

  it("hides a new style's chat on close and keeps the session to reopen", async () => {
    window.location.hash = "#/create"
    renderWithIntl(<StylesPage />)
    await waitFor(() => expect(chat().dataset.open).toBe("true"))

    fireEvent.click(screen.getByRole("button", { name: "close chat" }))
    expect(chat().dataset.open).toBe("false")
    expect(window.location.hash).toBe("#/create")

    fireEvent.click(screen.getByRole("button", { name: "Open chat" }))
    expect(chat().dataset.open).toBe("true")
    expect(shell.mounts).toBe(1)
  })

  it("gives a style named create its own preview hash", () => {
    expect(parseHash("#create")).toEqual({ mode: "preview", name: "create" })
    expect(parseHash("#/create")).toEqual({ mode: "create" })
  })
})
