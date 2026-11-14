// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Attachment upload: stays inside the deck root's `.attachments`, refusing symlinked directories. */

import fs from "fs"
import os from "os"
import path from "path"
import { afterAll, beforeAll, describe, expect, it } from "vitest"

type Route = typeof import("./route")

let base: string
let root: string
let outside: string
let savedRoot: string | undefined
let POST: Route["POST"]

const upload = (sessionId: string) => {
  const form = new FormData()
  form.set("sessionId", sessionId)
  form.set("file", new File(["data"], "a.txt"))
  return POST(new Request("http://localhost/api/attachments", { method: "POST", body: form }))
}

beforeAll(async () => {
  base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-attach-")))
  root = path.join(base, "decks")
  outside = path.join(base, "outside")
  fs.mkdirSync(path.join(root, ".attachments"), { recursive: true })
  fs.mkdirSync(outside)
  fs.symlinkSync(outside, path.join(root, ".attachments", "linked"))
  savedRoot = process.env.SDPM_DECK_ROOT
  process.env.SDPM_DECK_ROOT = root
  POST = (await import("./route")).POST
})

afterAll(() => {
  if (savedRoot === undefined) delete process.env.SDPM_DECK_ROOT
  else process.env.SDPM_DECK_ROOT = savedRoot
  fs.rmSync(base, { recursive: true, force: true })
})

describe("POST /api/attachments", () => {
  it("stores a file under the session directory", async () => {
    const res = await upload("s1")
    expect(res.status).toBe(200)
    const { source } = await res.json() as { source: string }
    expect(source.startsWith(path.join(root, ".attachments", "s1") + path.sep)).toBe(true)
    expect(fs.readFileSync(source, "utf-8")).toBe("data")
  })

  it("refuses a session directory that is a symlink out of the root", async () => {
    expect((await upload("linked")).status).toBe(500)
    expect(fs.readdirSync(outside)).toEqual([])
  })
})
