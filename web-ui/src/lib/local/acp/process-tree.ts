// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The process tree of one kiro-cli, and how it is ended. Engine-independent: the walk is the same
 * for every layout. kiro-cli's own children lead process groups of their own (V3's agent server,
 * with its uv and python; V2's MCP servers, one group each), outside kiro-cli's group, and can
 * outlive kiro-cli. Signalling kiro-cli alone, or its group alone, leaves them running.
 *
 * - **Snapshot.** `ps -A -o pid=,pgid=,ppid=,lstart=` (`LC_ALL=C`, no shell). The roots are
 *   kiro-cli's pid while it lives and every process recorded earlier that is still in the table;
 *   the tree is their transitive descendants by ppid. A process is known by its pid and start
 *   time (`lstart`): a pid reused by another process is neither walked nor signalled.
 * - **Groups.** Every process group of the tree is recorded, except the Local server's own (a
 *   chat's kiro-cli runs in it) and any g ≤ 1. A recorded process in the Local server's group is
 *   signalled by its pid, never the Local server itself.
 * - **Signal.** `kill(-g)` for every recorded group in which the snapshot taken for that signal
 *   shows a recorded process, `kill(pid)` to kiro-cli while it lives. ESRCH is ignored; any other
 *   error is logged and that group's processes get the signal by pid. A failing `ps` is logged
 *   once and the groups recorded so far are signalled. Without the Local server's own row in the
 *   table no group is signalled at all, only pids.
 * - **Gone.** kiro-cli exited and no recorded group (and no recorded process in the Local
 *   server's group) is left.
 * - **Windows.** `taskkill /PID <pid> /T /F` ends the tree; it is gone once kiro-cli exited.
 */
import { execFile, execFileSync } from "child_process"

export interface ProcRow {
  pid: number
  pgid: number
  ppid: number
  /** The start time as `ps` prints it (opaque; compared for equality). */
  lstart: string
}

/** What the tree reads and signals with (tests inject them). */
export interface ProcessDeps {
  table(): Promise<ProcRow[]>
  tableSync(): ProcRow[]
  kill(pid: number, signal: NodeJS.Signals | 0): void
  platform: NodeJS.Platform
  /** The Local server's pid (its row gives the group nothing may signal). */
  ownPid: number
  /** Windows: end the tree of `pid`. */
  taskkill(pid: number): void
}

const PS_ARGS = ["-A", "-o", "pid=,pgid=,ppid=,lstart="]
const PS_TIMEOUT_MS = 5000
const PS_SYNC_TIMEOUT_MS = 1000
const ROW = /^\s*(\d+)\s+(\d+)\s+(\d+)(?:\s+(.*?))?\s*$/

/** `ps -o pid=,pgid=,ppid=,lstart=` lines: three integers, then the rest of the line as `lstart`; other lines skipped. */
export function parsePs(text: string): ProcRow[] {
  const rows: ProcRow[] = []
  for (const line of text.split("\n")) {
    const m = ROW.exec(line)
    if (m) rows.push({ pid: Number(m[1]), pgid: Number(m[2]), ppid: Number(m[3]), lstart: m[4] ?? "" })
  }
  return rows
}

export function readProcessTable(): Promise<ProcRow[]> {
  return new Promise((resolve, reject) => {
    execFile("ps", PS_ARGS, { env: { ...process.env, LC_ALL: "C" }, timeout: PS_TIMEOUT_MS }, (error, stdout) => {
      if (error) reject(error)
      else resolve(parsePs(String(stdout)))
    })
  })
}

export function readProcessTableSync(): ProcRow[] {
  return parsePs(String(execFileSync("ps", PS_ARGS, { env: { ...process.env, LC_ALL: "C" }, timeout: PS_SYNC_TIMEOUT_MS, encoding: "utf-8" })))
}

export const defaultProcessDeps: ProcessDeps = {
  table: readProcessTable,
  tableSync: readProcessTableSync,
  kill: (pid, signal) => { process.kill(pid, signal) },
  platform: process.platform,
  ownPid: process.pid,
  taskkill: (pid) => {
    execFile("taskkill", ["/PID", String(pid), "/T", "/F"], (error) => {
      if (error) console.warn("[acp] taskkill %s: %s", pid, error.message)
    })
  },
}

export interface Tree {
  /** Every process of the tree, roots included, with its start time. */
  pids: Map<number, string>
  /** The tree's process groups (the Local server's and g ≤ 1 left out) and their processes. */
  groups: Map<number, Set<number>>
  /** Processes of the tree in the Local server's group (signalled by pid). */
  ownGroup: Set<number>
}

/**
 * The tree of `roots` in `rows`: a root counts when its pid is in the table with the same start
 * time (`null`: any), and the tree is every transitive descendant by ppid.
 */
export function treeOf(rows: ProcRow[], roots: Map<number, string | null>, ownPgid: number | null): Tree {
  const byParent = new Map<number, ProcRow[]>()
  const byPid = new Map<number, ProcRow>()
  for (const row of rows) {
    byPid.set(row.pid, row)
    const siblings = byParent.get(row.ppid) ?? []
    siblings.push(row)
    byParent.set(row.ppid, siblings)
  }
  const tree: Tree = { pids: new Map(), groups: new Map(), ownGroup: new Set() }
  const queue: ProcRow[] = []
  for (const [pid, lstart] of roots) {
    const row = byPid.get(pid)
    if (row && (lstart === null || row.lstart === lstart)) queue.push(row)
  }
  while (queue.length) {
    const row = queue.shift()!
    if (tree.pids.has(row.pid)) continue
    tree.pids.set(row.pid, row.lstart)
    if (ownPgid !== null && row.pgid === ownPgid) tree.ownGroup.add(row.pid)
    else if (row.pgid > 1) {
      const members = tree.groups.get(row.pgid) ?? new Set<number>()
      members.add(row.pid)
      tree.groups.set(row.pgid, members)
    }
    queue.push(...(byParent.get(row.pid) ?? []))
  }
  return tree
}

const codeOf = (error: unknown) => (error as NodeJS.ErrnoException | undefined)?.code
const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

/** The process tree of one kiro-cli (see the header). */
export class ProcessTree {
  private readonly deps: ProcessDeps
  private rootLstart: string | null = null
  private exited = false
  /** Every process recorded in the tree, with its start time. */
  private readonly recorded = new Map<number, string>()
  /** Every group recorded (the poll asks each of them). */
  private readonly recordedGroups = new Set<number>()
  /** Recorded processes in the Local server's group. */
  private readonly recordedOwn = new Set<number>()
  private lastTable: ProcRow[] | null = null
  private ownPgid: number | null = null
  private psWarned = false
  private taskkilled = false

  constructor(readonly rootPid: number | undefined, deps: Partial<ProcessDeps> = {}) {
    this.deps = { ...defaultProcessDeps, ...deps }
  }

  /** kiro-cli exited: it is no root any more. */
  markExited(): void {
    this.exited = true
  }

  /** The groups recorded so far (for log lines). */
  groups(): number[] {
    return [...this.recordedGroups]
  }

  /** Read the table and record the tree; a failing `ps` keeps what is recorded (one warning). */
  async snapshot(): Promise<void> {
    if (this.deps.platform === "win32" || this.rootPid === undefined) return
    let rows: ProcRow[]
    try {
      rows = await this.deps.table()
    } catch (error) {
      this.psFailed(error)
      return
    }
    this.record(rows)
  }

  /** Record from a table read elsewhere (`killAll`'s one table for every host). */
  record(rows: ProcRow[]): void {
    this.lastTable = rows
    const own = rows.find((row) => row.pid === this.deps.ownPid)
    this.ownPgid = own ? own.pgid : null
    const roots = new Map<number, string | null>(this.recorded)
    if (!this.exited && this.rootPid !== undefined) roots.set(this.rootPid, this.rootLstart)
    const tree = treeOf(rows, roots, this.ownPgid)
    if (this.rootPid !== undefined && tree.pids.has(this.rootPid) && this.rootLstart === null) this.rootLstart = tree.pids.get(this.rootPid)!
    for (const [pid, lstart] of tree.pids) this.recorded.set(pid, lstart)
    for (const g of tree.groups.keys()) this.recordedGroups.add(g)
    for (const pid of tree.ownGroup) this.recordedOwn.add(pid)
  }

  /** Snapshot, then signal (Windows: taskkill once). */
  async end(signal: NodeJS.Signals): Promise<void> {
    if (this.deps.platform === "win32") {
      if (this.rootPid !== undefined && !this.exited && !this.taskkilled) {
        this.taskkilled = true
        this.deps.taskkill(this.rootPid)
      }
      return
    }
    await this.snapshot()
    this.signal(signal)
  }

  /**
   * Send `signal` to the tree, synchronously, by the given table (else the last snapshot's): every
   * group in which it shows a recorded process, kiro-cli's pid while it lives, and the recorded
   * processes in the Local server's group by pid.
   */
  signal(signal: NodeJS.Signals, table?: ProcRow[]): void {
    if (this.deps.platform === "win32") {
      if (this.rootPid !== undefined && !this.exited && !this.taskkilled) {
        this.taskkilled = true
        this.deps.taskkill(this.rootPid)
      }
      return
    }
    const rows = table ?? this.lastTable
    if (table) {
      const own = table.find((row) => row.pid === this.deps.ownPid)
      if (own) this.ownPgid = own.pgid
    }
    const byGroup = new Map<number, number[]>()
    const byPid: number[] = []
    for (const row of rows ?? []) {
      if (this.recorded.get(row.pid) !== row.lstart || row.pid === this.deps.ownPid) continue
      if (this.ownPgid === null || row.pgid === this.ownPgid) byPid.push(row.pid)
      else if (row.pgid <= 1) console.warn("[acp] pid %s is in group %s; not signalling that group", row.pid, row.pgid)
      else byGroup.set(row.pgid, [...(byGroup.get(row.pgid) ?? []), row.pid])
    }
    for (const [g, members] of byGroup) {
      try {
        this.deps.kill(-g, signal)
      } catch (error) {
        if (codeOf(error) === "ESRCH") continue
        console.warn("[acp] %s to group %s: %s; signalling its processes", signal, g, errorText(error))
        for (const pid of members) this.killPid(pid, signal)
      }
    }
    for (const pid of byPid) if (pid !== this.rootPid) this.killPid(pid, signal)
    if (!this.exited && this.rootPid !== undefined) this.killPid(this.rootPid, signal)
  }

  /** kiro-cli exited and nothing recorded is left (Windows: kiro-cli exited). */
  gone(): boolean {
    if (!this.exited) return false
    if (this.deps.platform === "win32") return true
    for (const g of this.recordedGroups) if (this.alive(-g)) return false
    for (const pid of this.recordedOwn) if (pid !== this.deps.ownPid && this.alive(pid)) return false
    return true
  }

  private alive(target: number): boolean {
    try {
      this.deps.kill(target, 0)
      return true
    } catch (error) {
      return codeOf(error) !== "ESRCH"
    }
  }

  private killPid(pid: number, signal: NodeJS.Signals): void {
    if (pid === this.deps.ownPid || pid <= 1) return
    try {
      this.deps.kill(pid, signal)
    } catch (error) {
      if (codeOf(error) !== "ESRCH") console.warn("[acp] %s to pid %s: %s", signal, pid, errorText(error))
    }
  }

  private psFailed(error: unknown): void {
    if (this.psWarned) return
    this.psWarned = true
    console.warn("[acp] ps failed (%s); signalling the process groups recorded so far", errorText(error))
  }
}
