// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, expect, it } from "vitest"
import { buildOutlineEditMessage, type OutlineMessageCatalog } from "./outlineEditMessage"

const catalog: OutlineMessageCatalog = {
  edited: "EDITED",
  largeEdit: (count) => `LARGE ${count}`,
  placeholderSlugs: (slugs) => `SLUGS ${slugs}`,
  polish: "POLISH",
  overwritten: "OVERWRITTEN",
  display: (added, deleted) => `DISPLAY +${added} -${deleted}`,
}

describe("buildOutlineEditMessage", () => {
  it("builds a diff message with all conditional sentences in contract order", () => {
    const base = "# Deck\n\n## A\n\n- [first] Old\n"
    const text = "# Deck\n\n## A\n\n- [first] New\n- [slide-2] Added\n- [slide-3] Also added\n"
    const result = buildOutlineEditMessage({
      base,
      text,
      latestSeen: `${base}<!-- agent changed -->\n`,
      polish: true,
      catalog,
    })

    expect(result.body).toContain("EDITED\n\n```diff\n")
    expect(result.body).toContain("- [slide-2] Added")
    expect(result.body.indexOf("SLUGS `slide-2`, `slide-3`")).toBeLessThan(result.body.indexOf("POLISH"))
    expect(result.body.indexOf("POLISH")).toBeLessThan(result.body.indexOf("OVERWRITTEN"))
    expect(result.displayContent).toBe("DISPLAY +3 -1")
    expect(result.placeholderSlugs).toEqual(["slide-2", "slide-3"])
  })

  it("omits optional sentences when they do not apply", () => {
    const base = "- [first] Old\n"
    const result = buildOutlineEditMessage({ base, text: "- [first] New\n", latestSeen: base, polish: false, catalog })
    expect(result.body).not.toContain("SLUGS")
    expect(result.body).not.toContain("POLISH")
    expect(result.body).not.toContain("OVERWRITTEN")
  })

  it("uses the compact large-edit message when unified diff exceeds 150 lines", () => {
    const base = Array.from({ length: 170 }, (_, index) => `old ${index}`).join("\n")
    const text = Array.from({ length: 170 }, (_, index) => `new ${index}`).join("\n")
    const result = buildOutlineEditMessage({ base, text, latestSeen: base, polish: false, catalog })
    expect(result.body).toBe("LARGE 340")
    expect(result.body).not.toContain("```diff")
  })
})
