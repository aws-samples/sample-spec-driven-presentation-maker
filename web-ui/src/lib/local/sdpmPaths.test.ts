// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Guard against directory renames breaking the local-mode path anchors.
 *
 * These anchors point outside web-ui/ into the repo's sdpm/ distribution.
 * Cloud builds exclude the API routes and other tests mock the API, so a
 * stale path here ships silently — this test resolves the real filesystem.
 * (vitest runs with cwd = web-ui/, same as `next dev`.)
 */
import fs from "fs"
import path from "path"
import { describe, expect, it } from "vitest"

import { BUNDLED_STYLES_DIR, BUNDLED_TEMPLATES_DIR, SDPM_ROOT } from "./sdpmPaths"

describe("sdpm path anchors", () => {
  it("SDPM_ROOT points at the skill distribution", () => {
    expect(fs.existsSync(path.join(SDPM_ROOT, "SKILL.md"))).toBe(true)
  })

  it("bundled templates dir exists and contains .pptx templates", () => {
    expect(fs.existsSync(BUNDLED_TEMPLATES_DIR)).toBe(true)
    const pptx = fs.readdirSync(BUNDLED_TEMPLATES_DIR).filter((f) => f.endsWith(".pptx"))
    expect(pptx.length).toBeGreaterThan(0)
  })

  it("bundled styles dir exists", () => {
    expect(fs.existsSync(BUNDLED_STYLES_DIR)).toBe(true)
  })
})
