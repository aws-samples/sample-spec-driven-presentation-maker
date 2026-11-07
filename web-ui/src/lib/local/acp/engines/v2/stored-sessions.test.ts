// @vitest-environment node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * V2's session store: where it is (SDPM_KIRO_SESSIONS_DIR, then kiro-cli's KIRO_HOME, then
 * ~/.kiro), what a listed session looks like (the title from the first prompt when the stored
 * one is empty, sub-agent sessions marked), and the fork's copy (only the fork's metadata
 * rewritten, the log byte-copied, the source unchanged, ids checked before any file access).
 */

import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it } from "vitest"

import { v2Adapter } from "."
import { copyStoredSession, listV2Sessions, removeStoredSession, v2SessionsDir, type V2SessionMeta } from "./stored-sessions"

const IDS = {
  recent: "11111111-1111-4111-8111-111111111111",
  older: "22222222-2222-4222-8222-222222222222",
  child: "33333333-3333-4333-8333-333333333333",
}

let tmp: string

function prompt(text: string): string {
  return JSON.stringify({ version: "v1", kind: "Prompt", data: { content: [{ kind: "text", data: text }] } })
}

function writeSession(id: string, meta: V2SessionMeta, lines: string[] = []): void {
  fs.writeFileSync(path.join(tmp, `${id}.json`), JSON.stringify({ session_id: id, ...meta }, null, 2)) // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
  fs.writeFileSync(path.join(tmp, `${id}.jsonl`), lines.join("\n") + (lines.length ? "\n" : "")) // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
}

beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "kiro-sessions-"))
})

afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true })
})

describe("v2SessionsDir", () => {
  it("prefers SDPM_KIRO_SESSIONS_DIR, then kiro-cli's KIRO_HOME, then ~/.kiro", () => {
    expect(v2SessionsDir({ SDPM_KIRO_SESSIONS_DIR: "/x/sessions", KIRO_HOME: "/kh" } as unknown as NodeJS.ProcessEnv)).toBe("/x/sessions")
    expect(v2SessionsDir({ KIRO_HOME: "/kh" } as unknown as NodeJS.ProcessEnv)).toBe(path.join("/kh", "sessions", "cli"))
    expect(v2SessionsDir({} as NodeJS.ProcessEnv)).toBe(path.join(os.homedir(), ".kiro", "sessions", "cli"))
  })
})

describe("listV2Sessions", () => {
  it("lists every session as V2, with the stored or first-prompt title and sub-agent sessions marked", async () => {
    writeSession(IDS.recent, {
      cwd: "/work/alpha",
      updated_at: "2026-11-07T10:00:00.000Z",
      title: "",
      parent_session_id: null,
      session_state: { agent_name: "kiro_default" },
    }, [prompt("A title recovered from the first prompt that is deliberately longer than sixty characters total"), prompt("second")])
    writeSession(IDS.older, { cwd: "/work/alpha", updated_at: "2026-11-07T09:00:00.000Z", title: "Older" }, [prompt("one")])
    writeSession(IDS.child, { cwd: "/work/alpha", updated_at: "2026-11-07T11:00:00.000Z", title: "Child", parent_session_id: IDS.recent })
    fs.writeFileSync(path.join(tmp, "not-a-session.json"), "{}") // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
    fs.writeFileSync(path.join(tmp, "44444444-4444-4444-8444-444444444444.json"), "{broken") // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir

    const sessions = (await listV2Sessions(tmp)).sort((a, b) => a.sessionId.localeCompare(b.sessionId))
    expect(sessions).toEqual([
      { sessionId: IDS.recent, engine: "v2", title: "A title recovered from the first prompt that is deliberately", cwd: "/work/alpha", updatedAt: "2026-11-07T10:00:00.000Z", agentName: "kiro_default" },
      { sessionId: IDS.older, engine: "v2", title: "Older", cwd: "/work/alpha", updatedAt: "2026-11-07T09:00:00.000Z", agentName: null },
      { sessionId: IDS.child, engine: "v2", title: "Child", cwd: "/work/alpha", updatedAt: "2026-11-07T11:00:00.000Z", agentName: null, subagent: true },
    ])
  })

  it("does not read the log when the stored title is present", async () => {
    writeSession(IDS.recent, { cwd: "/work/gamma", updated_at: new Date().toISOString(), title: "Stored" })
    // A directory where the log should be: reading it would throw EISDIR.
    fs.rmSync(path.join(tmp, `${IDS.recent}.jsonl`)) // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
    fs.mkdirSync(path.join(tmp, `${IDS.recent}.jsonl`)) // nosemgrep: path-join-resolve-traversal — test fixture in tmpdir
    expect((await listV2Sessions(tmp)).map((session) => session.title)).toEqual(["Stored"])
  })

  it("takes the title from the first prompt, skipping malformed and non-prompt lines", async () => {
    writeSession(IDS.recent, { cwd: "/work/delta", updated_at: new Date().toISOString(), title: "  " }, [
      "{malformed",
      JSON.stringify({ kind: "AssistantMessage", data: {} }),
      prompt("first"),
      prompt("second"),
    ])
    expect((await listV2Sessions(tmp))[0].title).toBe("first")
  })

  it("lists nothing when the store does not exist, and the adapter reads the store of kiro-cli's environment", async () => {
    expect(await listV2Sessions(path.join(tmp, "missing"))).toEqual([])
    writeSession(IDS.recent, { cwd: "/work/a", updated_at: "2026-11-07T10:00:00.000Z", title: "T" })
    const connect = () => { throw new Error("V2 lists its files without kiro-cli") }
    const env = { SDPM_KIRO_SESSIONS_DIR: tmp } as unknown as NodeJS.ProcessEnv
    expect((await v2Adapter.listStoredSessions({ env, connect })).map((s) => s.sessionId)).toEqual([IDS.recent])
    expect(v2Adapter.sessionsOpenableBy).toEqual(["v2", "v3"])
  })
})

describe("copyStoredSession", () => {
  it("rewrites only the fork's metadata and byte-copies the log without changing the source", async () => {
    const meta: V2SessionMeta = {
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

    const newId = await copyStoredSession(IDS.recent, tmp)
    const forkMeta = JSON.parse(fs.readFileSync(path.join(tmp, `${newId}.json`), "utf-8"))

    expect(forkMeta).toMatchObject({ ...meta, session_id: newId, imported_from: IDS.recent })
    expect(fs.readFileSync(path.join(tmp, `${newId}.jsonl`))).toEqual(sourceJsonlBefore)
    expect(fs.readFileSync(path.join(tmp, `${IDS.recent}.json`))).toEqual(sourceJsonBefore)
    expect(fs.readFileSync(path.join(tmp, `${IDS.recent}.jsonl`))).toEqual(sourceJsonlBefore)

    await removeStoredSession(newId, tmp)
    expect(fs.readdirSync(tmp).sort()).toEqual([`${IDS.recent}.json`, `${IDS.recent}.jsonl`])
  })

  it("rejects non-UUID ids before filesystem access", async () => {
    await expect(copyStoredSession("../escape", tmp)).rejects.toThrow("invalid kiro session ID")
    await expect(removeStoredSession("../escape", tmp)).rejects.toThrow("invalid kiro session ID")
    expect(fs.readdirSync(tmp)).toEqual([])
  })
})
