import { afterEach, beforeEach, describe, expect, it } from "vitest"
import fs from "fs"
import os from "os"
import path from "path"

import { forkSession, isCandidate, listSessions, type SessionMeta } from "./kiro-sessions"

const IDS = {
  recent: "11111111-1111-4111-8111-111111111111",
  older: "22222222-2222-4222-8222-222222222222",
  child: "33333333-3333-4333-8333-333333333333",
  sdpm: "44444444-4444-4444-8444-444444444444",
  local: "55555555-5555-4555-8555-555555555555",
  missingParent: "66666666-6666-4666-8666-666666666666",
}

let tmp: string

function prompt(text: string): string {
  return JSON.stringify({ version: "v1", kind: "Prompt", data: { content: [{ kind: "text", data: text }] } })
}

function writeSession(id: string, meta: SessionMeta, lines: string[] = []): void {
  fs.writeFileSync(path.join(tmp, `${id}.json`), JSON.stringify({ session_id: id, ...meta }, null, 2))
  fs.writeFileSync(path.join(tmp, `${id}.jsonl`), lines.join("\n") + (lines.length ? "\n" : ""))
}

beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "kiro-sessions-"))
})

afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true })
})

describe("isCandidate", () => {
  it("accepts a missing parent_session_id as top-level", () => {
    expect(isCandidate({ cwd: "/work/project", session_state: { agent_name: "kiro_default" } })).toBe(true)
  })

  it("excludes child, SDPM-agent, and servers/local sessions", () => {
    expect(isCandidate({ cwd: "/work/project", parent_session_id: IDS.recent })).toBe(false)
    expect(isCandidate({ cwd: "/work/project", parent_session_id: null, session_state: { agent_name: "sdpm-orchestrator" } })).toBe(false)
    expect(isCandidate({ cwd: "/work/repo/servers/local", parent_session_id: null })).toBe(false)
    expect(isCandidate({ cwd: "/work/repo/servers/local/fixtures", parent_session_id: null })).toBe(false)
  })
})

describe("listSessions", () => {
  it("filters candidates, groups by cwd, sorts newest first, and returns recent three", async () => {
    const now = Date.now()
    writeSession(IDS.recent, {
      cwd: "/work/alpha",
      updated_at: new Date(now - 1_000).toISOString(),
      title: "",
      parent_session_id: null,
      session_state: { agent_name: "kiro_default" },
    }, [prompt("A title recovered from the first prompt that is deliberately longer than sixty characters total"), prompt("second")])
    writeSession(IDS.older, {
      cwd: "/work/alpha",
      updated_at: new Date(now - 2_000).toISOString(),
      title: "Older",
      parent_session_id: null,
    }, [prompt("one")])
    writeSession(IDS.missingParent, {
      cwd: "/work/beta",
      updated_at: new Date(now - 3_000).toISOString(),
      title: "Missing parent key",
    }, [prompt("one"), JSON.stringify({ kind: "Prompt", data: { content: [] } }), JSON.stringify({ kind: "AssistantMessage", data: {} })])
    writeSession(IDS.child, {
      cwd: "/work/alpha",
      updated_at: new Date(now - 500).toISOString(),
      title: "Child",
      parent_session_id: IDS.recent,
    })
    writeSession(IDS.sdpm, {
      cwd: "/work/alpha",
      updated_at: new Date(now - 400).toISOString(),
      title: "SDPM",
      parent_session_id: null,
      session_state: { agent_name: "sdpm-style" },
    })
    writeSession(IDS.local, {
      cwd: "/work/repo/servers/local",
      updated_at: new Date(now - 300).toISOString(),
      title: "Local server",
      parent_session_id: null,
    })

    const result = await listSessions({ includeAll: false, dir: tmp })

    expect(result.groups.map((group) => group.cwd)).toEqual(["/work/alpha", "/work/beta"])
    expect(result.groups[0].sessions.map((session) => session.sessionId)).toEqual([IDS.recent, IDS.older])
    expect(result.groups[0].sessions[0]).toMatchObject({
      project: "alpha",
      messageCount: 2,
      title: "A title recovered from the first prompt that is deliberately",
    })
    expect(result.groups[1].sessions[0].messageCount).toBe(2)
    expect(result.recent.map((session) => session.sessionId)).toEqual([IDS.recent, IDS.older, IDS.missingParent])

    const all = await listSessions({ includeAll: true, dir: tmp })
    expect(all.groups.flatMap((group) => group.sessions)).toHaveLength(6)
    expect(all.recent).toHaveLength(3)
  })
})

describe("forkSession", () => {
  it("rewrites only fork metadata and byte-copies the log without changing the source", async () => {
    const meta: SessionMeta = {
      cwd: "/work/source",
      updated_at: "2026-09-22T12:00:00.000Z",
      title: "Source session",
      parent_session_id: null,
      session_state: { agent_name: "sa-dev" },
      custom_field: { keep: true },
    }
    writeSession(IDS.recent, meta, [prompt("first"), "{malformed", prompt("second")])
    const sourceJsonBefore = fs.readFileSync(path.join(tmp, `${IDS.recent}.json`))
    const sourceJsonlBefore = fs.readFileSync(path.join(tmp, `${IDS.recent}.jsonl`))

    const { newId, origin } = await forkSession(IDS.recent, { dir: tmp })
    const forkMeta = JSON.parse(fs.readFileSync(path.join(tmp, `${newId}.json`), "utf-8"))

    expect(forkMeta).toMatchObject({
      ...meta,
      session_id: newId,
      imported_from: { session_id: IDS.recent, forked_by: "sdpm-web-ui" },
    })
    expect(fs.readFileSync(path.join(tmp, `${newId}.jsonl`))).toEqual(sourceJsonlBefore)
    expect(fs.readFileSync(path.join(tmp, `${IDS.recent}.json`))).toEqual(sourceJsonBefore)
    expect(fs.readFileSync(path.join(tmp, `${IDS.recent}.jsonl`))).toEqual(sourceJsonlBefore)
    expect(origin).toMatchObject({
      sourceSessionId: IDS.recent,
      title: "Source session",
      cwd: "/work/source",
      updatedAt: "2026-09-22T12:00:00.000Z",
    })
    expect(Date.parse(origin.forkedAt)).not.toBeNaN()
    expect(fs.existsSync(path.join(tmp, `${newId}.history`))).toBe(false)
  })

  it("rejects non-UUID source IDs before filesystem access", async () => {
    await expect(forkSession("../escape", { dir: tmp })).rejects.toThrow("invalid kiro session ID")
    expect(fs.readdirSync(tmp)).toEqual([])
  })
})
