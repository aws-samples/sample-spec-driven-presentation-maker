// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Layer rule of the Local ACP code: kiro-cli's own extension names (`_kiro…`) appear only in the
 * engine adapters (src/lib/local/acp/engines/), so dropping an engine is dropping its folder.
 * Checked over the web-ui sources, comments included; tests and src/test/ (fixtures, which are
 * kiro-cli's raw output) are left out. The import direction is ESLint's (eslint.config.mjs).
 */

import fs from "fs"
import path from "path"
import { describe, expect, it } from "vitest"

const SRC = path.resolve(__dirname, "../..")
const ENGINES = path.resolve(SRC, "lib/local/acp/engines")
const TEST_DIR = path.resolve(SRC, "test")

function sources(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.resolve(dir, entry.name) // nosemgrep: path-join-resolve-traversal — names from readdir of the source tree
    if (entry.isDirectory()) return full === TEST_DIR ? [] : sources(full)
    return /\.(ts|tsx|js)$/.test(entry.name) && !/\.test\./.test(entry.name) ? [full] : []
  })
}

describe("Local ACP layers", () => {
  it("names kiro-cli's _kiro extensions only inside acp/engines/", () => {
    const files = sources(SRC)
    expect(files.length).toBeGreaterThan(100)
    const outside = files
      .filter((file) => !file.startsWith(ENGINES + path.sep))
      .filter((file) => fs.readFileSync(file, "utf-8").includes("_kiro"))
      .map((file) => path.relative(SRC, file))
    expect(outside).toEqual([])
  })
})
