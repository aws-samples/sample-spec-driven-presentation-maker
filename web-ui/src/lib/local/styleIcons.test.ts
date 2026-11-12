// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The Local routes' display copies: one engine process per batch, cached by content,
 * and the stored HTML whenever the engine cannot answer. The engine is a fake child.
 */

import { EventEmitter } from "events"
import { beforeEach, describe, expect, it, vi } from "vitest"

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }))
vi.mock("child_process", () => ({ spawn, default: { spawn } }))

import { inlineStyleIcons, resetStyleIconsCache } from "./styleIcons"

type Behaviour = "ok" | "exit1" | "error"

class FakeChild extends EventEmitter {
  stdout = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stderr = Object.assign(new EventEmitter(), { setEncoding: () => {} })
  stdin: EventEmitter & { end: (data: string) => void }
  kill = vi.fn()
  constructor(behaviour: Behaviour) {
    super()
    this.stdin = Object.assign(new EventEmitter(), {
      end: (data: string) => {
        setImmediate(() => {
          if (behaviour === "error") return this.emit("error", new Error("spawn uv ENOENT"))
          if (behaviour === "exit1") { this.stderr.emit("data", "boom"); return this.emit("close", 1) }
          const htmls: string[] = JSON.parse(data)
          this.stdout.emit("data", JSON.stringify(htmls.map(h => h.replace("<body>", "<body><svg data-sdpm-icons/>"))))
          this.emit("close", 0)
        })
      },
    })
  }
}

let behaviour: Behaviour = "ok"
const ref = (n: string) => `<html><body><svg><use href="#material/${n}"/></svg></body></html>`
const drawn = (n: string) => ref(n).replace("<body>", "<body><svg data-sdpm-icons/>")

beforeEach(() => {
  resetStyleIconsCache()
  behaviour = "ok"
  spawn.mockReset()
  spawn.mockImplementation(() => new FakeChild(behaviour))
  vi.spyOn(console, "warn").mockImplementation(() => {})
})

describe("inlineStyleIcons", () => {
  it("returns the engine's display copies, one process per batch", async () => {
    expect(await inlineStyleIcons([ref("a"), ref("b"), ref("a")])).toEqual([drawn("a"), drawn("b"), drawn("a")])
    expect(spawn).toHaveBeenCalledTimes(1)
    const [cmd, args] = spawn.mock.calls[0]
    expect(cmd).toBe("uv")
    expect(args.slice(0, 2)).toEqual(["run", "--directory"])
  })

  it("serves a repeat from the cache", async () => {
    await inlineStyleIcons([ref("a")])
    expect(await inlineStyleIcons([ref("a")])).toEqual([drawn("a")])
    expect(spawn).toHaveBeenCalledTimes(1)
  })

  it("does not spawn for HTML without icon references", async () => {
    const plain = "<html><body><div class=\"slide\">x</div></body></html>"
    expect(await inlineStyleIcons([plain])).toEqual([plain])
    expect(spawn).not.toHaveBeenCalled()
  })

  it.each<Behaviour>(["exit1", "error"])("returns the stored HTML when the engine fails (%s)", async (b) => {
    behaviour = b
    expect(await inlineStyleIcons([ref("a")])).toEqual([ref("a")])
    // a failure is not retried on the next (polled) request
    expect(await inlineStyleIcons([ref("a")])).toEqual([ref("a")])
    expect(spawn).toHaveBeenCalledTimes(1)
  })
})
