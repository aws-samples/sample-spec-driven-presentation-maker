// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A kiro-cli's process tree: `ps` output parses on macOS and Linux; the walk gives V3's {P, K}
 * and V2's {P, U1, U2} and never the Local server's group, whose processes are signalled by pid;
 * a KAS is still walked from its recorded pid once its kiro-cli is gone; a reused pid (another
 * start time) is neither walked nor signalled; ESRCH is ignored and EPERM falls back to per-pid
 * kills; a failing ps keeps the recorded groups; g ≤ 1 is never signalled; Windows ends the tree
 * with taskkill. With real processes: a grandchild in a group of its own is recorded and ended.
 */
import { spawn, spawnSync, type ChildProcess } from "child_process"
import { afterEach, describe, expect, it, vi } from "vitest"

import { parsePs, ProcessTree, treeOf, type ProcessDeps, type ProcRow } from "./process-tree"

const T = "Sat Nov  8 21:00:00 2026"
const T2 = "Sat Nov  8 21:05:00 2026"
const OWN = 100
const row = (pid: number, pgid: number, ppid: number, lstart = T): ProcRow => ({ pid, pgid, ppid, lstart })

/** The Local server (pid 100, group 100) and a kiro-cli P=200 in a group of its own. */
const V3_TABLE = [
  row(OWN, OWN, 1), row(200, 200, OWN),
  row(210, 210, 200), row(211, 210, 210), row(212, 210, 211), // KAS K, uv, python
  row(999, 999, 1), // unrelated
]
const V2_TABLE = [
  row(OWN, OWN, 1), row(300, 300, OWN),
  row(310, 310, 300), row(311, 310, 310), // MCP server U1: uv, python
  row(320, 320, 300), row(321, 320, 320), // U2
]

function deps(table: ProcRow[] | (() => ProcRow[]), extra: Partial<ProcessDeps> = {}) {
  const signals: [number, NodeJS.Signals | 0][] = []
  const read = typeof table === "function" ? table : () => table
  const d: Partial<ProcessDeps> = {
    table: async () => read(),
    tableSync: () => read(),
    kill: (pid, signal) => { signals.push([pid, signal]) },
    platform: "darwin",
    ownPid: OWN,
    taskkill: vi.fn(),
    ...extra,
  }
  return { d, signals }
}

const sent = (signals: [number, NodeJS.Signals | 0][], signal: NodeJS.Signals) => signals.filter(([, s]) => s === signal).map(([p]) => p).sort((a, b) => a - b)

describe("parsePs", () => {
  it("reads macOS and Linux lines: leading spaces, a start time with spaces, malformed lines skipped", () => {
    const text = [
      "  100   100     1 Sat Nov  8 21:00:00 2026",
      "12345 12345 100 Sat Nov 8 21:00:00 2026   ",
      "not a row",
      "",
      "  7  7  1",
    ].join("\n")
    expect(parsePs(text)).toEqual([
      { pid: 100, pgid: 100, ppid: 1, lstart: "Sat Nov  8 21:00:00 2026" },
      { pid: 12345, pgid: 12345, ppid: 100, lstart: "Sat Nov 8 21:00:00 2026" },
      { pid: 7, pgid: 7, ppid: 1, lstart: "" },
    ])
  })
})

describe("treeOf", () => {
  it("V3: kiro-cli's group and the KAS group, no unrelated process", () => {
    const tree = treeOf(V3_TABLE, new Map([[200, null]]), OWN)
    expect([...tree.groups.keys()].sort()).toEqual([200, 210])
    expect([...tree.pids.keys()].sort()).toEqual([200, 210, 211, 212])
  })

  it("V2: kiro-cli's group and one group per MCP server", () => {
    const tree = treeOf(V2_TABLE, new Map([[300, null]]), OWN)
    expect([...tree.groups.keys()].sort()).toEqual([300, 310, 320])
  })

  it("never puts the Local server's group in the groups; its members are kept by pid", () => {
    // A chat's kiro-cli runs in the Local server's group.
    const table = [row(OWN, OWN, 1), row(400, OWN, OWN), row(410, 410, 400), row(420, OWN, 400)]
    const tree = treeOf(table, new Map([[400, null]]), OWN)
    expect([...tree.groups.keys()]).toEqual([410])
    expect([...tree.ownGroup].sort()).toEqual([400, 420])
  })

  it("skips a root whose start time does not match", () => {
    const tree = treeOf(V3_TABLE, new Map([[210, T2]]), OWN)
    expect(tree.pids.size).toBe(0)
  })
})

describe("ProcessTree", () => {
  it("signals P and K for a V3 tree, never the Local server's group", async () => {
    const { d, signals } = deps(V3_TABLE)
    const tree = new ProcessTree(200, d)
    await tree.end("SIGTERM")
    expect(sent(signals, "SIGTERM")).toEqual([-210, -200, 200])
    expect(signals.some(([p]) => p === -OWN || p === OWN)).toBe(false)
  })

  it("signals P, U1 and U2 for a V2 tree", async () => {
    const { d, signals } = deps(V2_TABLE)
    await new ProcessTree(300, d).end("SIGTERM")
    expect(sent(signals, "SIGTERM")).toEqual([-320, -310, -300, 300])
  })

  it("signals a chat host's descendants in the Local server's group by pid, never the server", async () => {
    const table = [row(OWN, OWN, 1), row(400, OWN, OWN), row(410, 410, 400), row(420, OWN, 400), row(500, OWN, OWN)]
    const { d, signals } = deps(table)
    await new ProcessTree(400, d).end("SIGTERM")
    expect(sent(signals, "SIGTERM")).toEqual([-410, 400, 420])
  })

  it("walks a KAS from its recorded pid after its kiro-cli is gone", async () => {
    let table = V3_TABLE
    const { d, signals } = deps(() => table)
    const tree = new ProcessTree(200, d)
    await tree.snapshot()
    tree.markExited()
    // kiro-cli gone; the KAS reparented to launchd.
    table = [row(OWN, OWN, 1), row(210, 210, 1), row(211, 210, 210), row(212, 210, 211)]
    await tree.end("SIGKILL")
    expect(sent(signals, "SIGKILL")).toEqual([-210])
  })

  it("does not signal a group whose recorded pid now has another start time", async () => {
    let table = V3_TABLE
    const { d, signals } = deps(() => table)
    const tree = new ProcessTree(200, d)
    await tree.snapshot()
    tree.markExited()
    table = [row(OWN, OWN, 1), row(210, 210, 1, T2)]
    await tree.end("SIGTERM")
    expect(signals).toEqual([])
  })

  it("ignores ESRCH, and falls back to per-pid kills on EPERM", async () => {
    const signals: [number, NodeJS.Signals | 0][] = []
    const kill = (pid: number, signal: NodeJS.Signals | 0) => {
      signals.push([pid, signal])
      if (pid === -200) throw Object.assign(new Error("no such process"), { code: "ESRCH" })
      if (pid === -210) throw Object.assign(new Error("not permitted"), { code: "EPERM" })
    }
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    await new ProcessTree(200, { ...deps(V3_TABLE).d, kill }).end("SIGTERM")
    expect(sent(signals, "SIGTERM")).toEqual([-210, -200, 200, 210, 211, 212])
    expect(warn).toHaveBeenCalledTimes(1)
  })

  it("keeps the recorded groups when ps fails, and warns once", async () => {
    let fail = false
    const { d, signals } = deps(V3_TABLE)
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    const tree = new ProcessTree(200, { ...d, table: async () => { if (fail) throw new Error("ps: timed out"); return V3_TABLE } })
    await tree.snapshot()
    fail = true
    await tree.end("SIGTERM")
    await tree.end("SIGKILL")
    expect(sent(signals, "SIGTERM")).toEqual([-210, -200, 200])
    expect(sent(signals, "SIGKILL")).toEqual([-210, -200, 200])
    expect(warn).toHaveBeenCalledTimes(1)
  })

  it("signals only kiro-cli's pid when the Local server's own row is missing", async () => {
    const { d, signals } = deps(V3_TABLE.filter((r) => r.pid !== OWN))
    await new ProcessTree(200, d).end("SIGTERM")
    expect(sent(signals, "SIGTERM")).toEqual([200, 210, 211, 212])
  })

  it("never signals a group ≤ 1", async () => {
    const { d, signals } = deps([row(OWN, OWN, 1), row(200, 200, OWN), row(210, 1, 200), row(220, 0, 200)])
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    await new ProcessTree(200, d).end("SIGTERM")
    expect(sent(signals, "SIGTERM")).toEqual([-200, 200])
    expect(warn).toHaveBeenCalledTimes(2)
  })

  it("is gone once kiro-cli exited and every recorded group answers ESRCH", async () => {
    const alive = new Set([-200, -210])
    const kill = (pid: number, signal: NodeJS.Signals | 0) => {
      if (signal === 0 && !alive.has(pid)) throw Object.assign(new Error("no such process"), { code: "ESRCH" })
    }
    const tree = new ProcessTree(200, { ...deps(V3_TABLE).d, kill })
    await tree.snapshot()
    expect(tree.gone()).toBe(false)
    tree.markExited()
    alive.delete(-200)
    expect(tree.gone()).toBe(false)
    alive.delete(-210)
    expect(tree.gone()).toBe(true)
    expect(tree.groups().sort()).toEqual([200, 210])
  })

  it("Windows: ends the tree with taskkill once, and is gone when kiro-cli exited", async () => {
    const taskkill = vi.fn()
    const { d, signals } = deps(V3_TABLE, { platform: "win32", taskkill })
    const tree = new ProcessTree(200, d)
    await tree.end("SIGTERM")
    await tree.end("SIGKILL")
    tree.signal("SIGKILL")
    expect(taskkill).toHaveBeenCalledTimes(1)
    expect(taskkill).toHaveBeenCalledWith(200)
    expect(signals).toEqual([])
    expect(tree.gone()).toBe(false)
    tree.markExited()
    expect(tree.gone()).toBe(true)
  })
})

const hasPython = process.platform !== "win32" && spawnSync("python3", ["-c", "pass"]).status === 0

describe.skipIf(!hasPython)("ProcessTree, real processes", () => {
  let child: ChildProcess | null = null
  afterEach(() => {
    try { if (child?.pid) process.kill(-child.pid, "SIGKILL") } catch { /* gone */ }
    child = null
  })

  /** sh in a group of its own, with a python grandchild that moves into another group. */
  async function start(script: string): Promise<ProcessTree> {
    child = spawn("sh", ["-c", script], { detached: true, stdio: "ignore" })
    const tree = new ProcessTree(child.pid!)
    child.on("exit", () => tree.markExited())
    const until = Date.now() + 3000
    while (tree.groups().length < 2 && Date.now() < until) {
      await tree.snapshot()
      await new Promise((r) => setTimeout(r, 50))
    }
    return tree
  }

  const waitGone = async (tree: ProcessTree, ms: number) => {
    const until = Date.now() + ms
    while (!tree.gone() && Date.now() < until) await new Promise((r) => setTimeout(r, 25))
    return tree.gone()
  }

  it("records the grandchild's group and ends both groups with SIGTERM", async () => {
    const tree = await start("python3 -c 'import os,time; os.setpgid(0,0); time.sleep(30)' & sleep 30")
    expect(tree.groups()).toHaveLength(2)
    expect(tree.groups()).toContain(child!.pid)
    // Only sh's group: the grandchild lives on, and the tree is not gone.
    process.kill(-child!.pid!, "SIGTERM")
    await new Promise((r) => setTimeout(r, 300))
    expect(tree.gone()).toBe(false)
    await tree.end("SIGTERM")
    expect(await waitGone(tree, 1000)).toBe(true)
  })

  it("a child that ignores SIGTERM is gone after SIGKILL", async () => {
    const tree = await start("python3 -c 'import os,signal,time; os.setpgid(0,0); signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)' & trap '' TERM; sleep 30")
    expect(tree.groups()).toHaveLength(2)
    await tree.end("SIGTERM")
    expect(await waitGone(tree, 500)).toBe(false)
    await tree.end("SIGKILL")
    expect(await waitGone(tree, 1000)).toBe(true)
  })
})
