// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { describe, expect, it } from "vitest"
import {
  buildToken,
  detectSlashFragment,
  filterItems,
  parseTokens,
  SLASH_TOKEN_RE,
  SLASH_TOKEN_SOURCE,
  splitQuery,
  type PickerItem,
} from "./slashToken"

function item(overrides: Partial<PickerItem> & Pick<PickerItem, "kind" | "name">): PickerItem {
  return {
    description: "",
    source: "builtin",
    pinned: false,
    ...overrides,
  }
}

describe("detectSlashFragment", () => {
  it("opens for a `/` at the start of the line", () => {
    expect(detectSlashFragment("/lu", 3)).toEqual({ start: 0, query: "lu" })
  })

  it("opens for a `/` right after whitespace", () => {
    expect(detectSlashFragment("hello /lu", 9)).toEqual({ start: 6, query: "lu" })
  })

  it("opens for a `/` right after a newline", () => {
    expect(detectSlashFragment("first line\n/lu", 14)).toEqual({ start: 11, query: "lu" })
  })

  it("does not open when `/` directly follows a non-whitespace character (e.g. https://)", () => {
    expect(detectSlashFragment("see https://example.com", 24)).toBeNull()
  })

  it("does not open when the `/` fragment spans a newline up to the caret", () => {
    expect(detectSlashFragment("/lu\nmore text", 13)).toBeNull()
  })

  it("opens for the section-scoped form `/style lu`", () => {
    expect(detectSlashFragment("/style lu", 9)).toEqual({ start: 0, query: "style lu" })
  })

  it("closes (`null`) for a disallowed space like `/lu x`", () => {
    expect(detectSlashFragment("/lu x", 5)).toBeNull()
  })

  it("closes for a second space after a valid kind-scoped query (`/style lu na`)", () => {
    expect(detectSlashFragment("/style lu na", 12)).toBeNull()
  })

  it("stays open with an empty term right after the kind word (`/style `)", () => {
    expect(detectSlashFragment("/style ", 7)).toEqual({ start: 0, query: "style " })
  })

  it("rejects a tab as the kind/term separator", () => {
    expect(detectSlashFragment("/style\tlu", 9)).toBeNull()
  })

  it("returns null when there is no `/` before the caret", () => {
    expect(detectSlashFragment("no slash here", 5)).toBeNull()
  })
})

describe("splitQuery", () => {
  it("splits a section-scoped query into kind + term", () => {
    expect(splitQuery("style lu")).toEqual({ kind: "style", term: "lu" })
  })

  it("treats a bare kind word (no trailing space) as a term, not a scoped filter", () => {
    expect(splitQuery("style")).toEqual({ kind: null, term: "style" })
  })

  it("treats a non-kind word as a plain term", () => {
    expect(splitQuery("lu")).toEqual({ kind: null, term: "lu" })
  })
})

describe("filterItems", () => {
  const templateA = item({ kind: "template", name: "Alpha", description: "first template", source: "builtin" })
  const templateUser = item({ kind: "template", name: "Custom Alpha", description: "", source: "user" })
  const styleLumina = item({ kind: "style", name: "lumina", description: "bright style", source: "builtin" })
  const stylePinned = item({ kind: "style", name: "zeta", description: "", source: "builtin", pinned: true })
  const styleUser = item({ kind: "style", name: "beta", description: "", source: "user" })
  const styleBuiltin = item({ kind: "style", name: "gamma", description: "", source: "builtin" })
  const all = [templateA, templateUser, styleLumina, stylePinned, styleUser, styleBuiltin]

  it("keeps the whole section when the query matches a kind name", () => {
    const result = filterItems(all, "style")
    expect(result).toEqual([stylePinned, styleUser, styleLumina, styleBuiltin])
  })

  it("scopes to a section and filters by name/description with `style lu`", () => {
    const result = filterItems(all, "style lu")
    expect(result).toEqual([styleLumina])
  })

  it("orders sections template before style", () => {
    const result = filterItems(all, "")
    const kinds = result.map((r) => r.kind)
    const firstStyleIndex = kinds.indexOf("style")
    const lastTemplateIndex = kinds.lastIndexOf("template")
    expect(lastTemplateIndex).toBeLessThan(firstStyleIndex)
  })

  it("orders within a section as pinned -> user -> builtin, stable on ties", () => {
    const result = filterItems(all, "")
    const styleOrder = result.filter((r) => r.kind === "style").map((r) => r.name)
    expect(styleOrder).toEqual(["zeta", "beta", "lumina", "gamma"])
  })

  it("returns an empty array when nothing matches", () => {
    expect(filterItems(all, "zzz-no-match")).toEqual([])
  })

  it("matches partial, case-insensitive name/description text", () => {
    const result = filterItems(all, "BRIGHT")
    expect(result).toEqual([styleLumina])
  })

  it("returns all items for an empty query, respecting section+rank order", () => {
    const result = filterItems(all, "")
    expect(result).toEqual([templateUser, templateA, stylePinned, styleUser, styleLumina, styleBuiltin])
  })
})

describe("buildToken", () => {
  it("renders a bare name unquoted with a trailing space", () => {
    expect(buildToken({ kind: "style", name: "lumina" })).toBe("@style:lumina ")
  })

  it("quotes a name containing characters outside [A-Za-z0-9._-]", () => {
    expect(buildToken({ kind: "template", name: "My Brand (2026)" })).toBe('@template:"My Brand (2026)" ')
  })

  it("always appends exactly one trailing space", () => {
    const token = buildToken({ kind: "style", name: "beta" })
    expect(token.endsWith(" ")).toBe(true)
    expect(token.endsWith("  ")).toBe(false)
  })

  it("quotes names with underscores mixed with spaces, but leaves pure dotted/dashed names bare", () => {
    expect(buildToken({ kind: "style", name: "my_style-v1.2" })).toBe("@style:my_style-v1.2 ")
    expect(buildToken({ kind: "template", name: "a b" })).toBe('@template:"a b" ')
  })
})

describe("parseTokens", () => {
  it("locates a bare token with its offsets", () => {
    const text = "Please use @style:lumina for this deck"
    const tokens = parseTokens(text)
    expect(tokens).toHaveLength(1)
    expect(text.slice(tokens[0].start, tokens[0].end)).toBe("@style:lumina")
    expect(tokens[0]).toEqual({ kind: "style", name: "lumina", start: 11, end: 24 })
  })

  it("locates a quoted token and unwraps the name without quotes", () => {
    const text = 'Use @template:"My Brand (2026)" please'
    const tokens = parseTokens(text)
    expect(text.slice(tokens[0].start, tokens[0].end)).toBe('@template:"My Brand (2026)"')
    expect(tokens).toEqual([{ kind: "template", name: "My Brand (2026)", start: 4, end: 31 }])
  })

  it("locates multiple tokens of mixed kinds", () => {
    const text = "@template:alpha then @style:beta"
    const tokens = parseTokens(text)
    expect(tokens.map((t) => [t.kind, t.name])).toEqual([
      ["template", "alpha"],
      ["style", "beta"],
    ])
  })

  it("returns an empty array when there are no tokens", () => {
    expect(parseTokens("no tokens here")).toEqual([])
  })
})

describe("SLASH_TOKEN_RE", () => {
  it("matches bare and quoted forms for both kinds", () => {
    expect("@template:foo".match(SLASH_TOKEN_RE)).not.toBeNull()
    expect('@style:"a b"'.match(SLASH_TOKEN_RE)).not.toBeNull()
  })

  it("is defined with the global flag so repeated use with matchAll does not lose state", () => {
    expect(SLASH_TOKEN_RE.global).toBe(true)
  })

  it("SLASH_TOKEN_SOURCE has no capturing groups, so String.split does not leak subcaptures", () => {
    const parts = 'use @style:lumina and @template:"My Brand (2026)" please'.split(new RegExp(`(${SLASH_TOKEN_SOURCE})`))
    expect(parts).toEqual(["use ", "@style:lumina", " and ", '@template:"My Brand (2026)"', " please"])
  })
})
