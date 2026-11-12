// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The process table and signals of fake kiro-cli children (fakeKiro.ts), for tests whose host
 * pool reads `ps` and signals process trees (acp/process-tree.ts).
 *
 * - The children are what the test's `spawn` mock returned. A child spawned `detached` leads its
 *   own group, any other one sits in the Local server's group (`ownPgid`), unless it names its
 *   `pgid`. Its live `descendants` are listed under it.
 * - `execFile("ps", …)` / `execFileSync("ps", …)` print that table (the test's `child_process`
 *   mock provides the two functions).
 * - `process.kill` is spied: a pid or `-pgid` of a fake ends the matching children (`kill()`) and
 *   descendants (SIGTERM spares the descendants of a `surviveTerm` child), signal 0 probes; any
 *   other target throws ESRCH, so nothing real is ever signalled.
 */
import { vi, type Mock } from "vitest"

import type { FakeDescendant } from "./fakeKiro"

/** What a fake child must have (FakeChild, the contract test's ReplayChild). */
interface FakeProc {
  pid: number
  killed: boolean
  exited?: boolean
  pgid?: number
  descendants?: FakeDescendant[]
  surviveTerm?: boolean
  kill(): unknown
}

/** The Local server's process group in the fake table. */
export const FAKE_OWN_PGID = 4_999_999

interface Mocks {
  spawn: Mock
  execFile: Mock
  execFileSync: Mock
}

const esrch = () => Object.assign(new Error("kill ESRCH"), { code: "ESRCH" })

export function installFakeProcesses(mocks: Mocks, opts: { ownPgid?: number } = {}) {
  const ownPgid = opts.ownPgid ?? FAKE_OWN_PGID
  const signals: { target: number; signal: NodeJS.Signals | number | string | undefined }[] = []
  let psCalls = 0

  const children = (): { child: FakeProc; pgid: number }[] => mocks.spawn.mock.results.flatMap((result, i) => {
    if (result.type !== "return" || typeof (result.value as FakeProc | undefined)?.kill !== "function") return []
    const child = result.value as FakeProc
    const detached = (mocks.spawn.mock.calls[i]?.[2] as { detached?: boolean } | undefined)?.detached === true
    return [{ child, pgid: child.pgid ?? (detached ? child.pid : ownPgid) }]
  })
  const live = () => children().filter(({ child }) => !child.killed && !child.exited)

  function table(): string {
    const rows = [`${process.pid} ${ownPgid} 1 own`]
    for (const { child, pgid } of children()) {
      if (!child.killed && !child.exited) rows.push(`${child.pid} ${pgid} ${process.pid} fake`)
      for (const d of child.descendants ?? []) if (!d.dead) rows.push(`${d.pid} ${d.pgid} ${d.ppid} fake`)
    }
    return rows.join("\n") + "\n"
  }

  mocks.execFile.mockImplementation((command: string, _args: unknown, options: unknown, callback?: unknown) => {
    const cb = (typeof options === "function" ? options : callback) as ((error: Error | null, stdout: string, stderr: string) => void) | undefined
    if (command === "ps") psCalls++
    const out = command === "ps" ? table() : ""
    setImmediate(() => cb?.(null, out, ""))
    return {}
  })
  mocks.execFileSync.mockImplementation((command: string) => {
    if (command === "ps") psCalls++
    return command === "ps" ? table() : ""
  })

  const spy = vi.spyOn(process, "kill").mockImplementation(((target: number, signal?: NodeJS.Signals | number) => {
    signals.push({ target, signal })
    const probe = signal === 0
    const byGroup = target < 0
    const id = Math.abs(target)
    let hit = false
    for (const { child, pgid } of children()) {
      if (!child.killed && !child.exited && (byGroup ? pgid === id : child.pid === id)) {
        hit = true
        if (!probe) child.kill()
      }
      for (const d of child.descendants ?? []) {
        if (d.dead || (byGroup ? d.pgid !== id : d.pid !== id)) continue
        hit = true
        if (!probe && !(child.surviveTerm && signal === "SIGTERM")) d.dead = true
      }
    }
    if (!hit) throw esrch()
    return true
  }) as typeof process.kill)

  return {
    /** The table `ps` prints now. */
    table,
    /** Every `process.kill` call, signal 0 probes included. */
    signals,
    /** Signals other than probes, as `[target, signal]`. */
    sent: () => signals.filter((s) => s.signal !== 0).map((s) => [s.target, s.signal] as const),
    psCalls: () => psCalls,
    live,
    restore: () => spy.mockRestore(),
  }
}
