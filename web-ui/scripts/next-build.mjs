// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
//
// `next build`, leaving the tracked next-env.d.ts as it was.
//
// Next.js rewrites next-env.d.ts on every build (its route-type imports follow distDir,
// "build" here). In an installed checkout (~/.sdpm/checkout) a changed tracked file gets in
// the way of the next `sdpm update`, and committing Next's version instead would make the
// pull of every install whose build already rewrote it fail ("Your local changes … would be
// overwritten"). The route types are included through tsconfig.json either way.
import { readFileSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
import { spawnSync } from "node:child_process"

const file = new URL("../next-env.d.ts", import.meta.url)
let before = null
try {
  before = readFileSync(file)
} catch {
  // Not there: keep what Next writes.
}
const next = createRequire(import.meta.url).resolve("next/dist/bin/next")
const result = spawnSync(process.execPath, [next, "build"], { stdio: "inherit" })
let after = null
try {
  after = readFileSync(file)
} catch {
  // Removed by the build: put it back below.
}
if (before !== null && (after === null || !before.equals(after))) writeFileSync(file, before)
process.exit(result.status ?? 1)
