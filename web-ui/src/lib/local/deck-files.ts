// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * A deck's Local chat files, next to its slides: `.session` (the kiro session the deck's chat
 * continues), `.session-engine` (the engines that ran that session's turns), `.session-origin.json`
 * (a fork's source) and `.chat.json` (the chat as the UI shows it). Every path is resolved inside
 * the deck root (deck-paths.ts), and a file that is a symlink pointing out of the deck is neither
 * read nor written (contained.ts).
 */
import { isEngineId, type EngineId } from "./acp/engine-config"
import { resolveWithin } from "./contained"
import { resolveDeckDir } from "./deck-paths"
import type { SessionOrigin } from "./kiro-sessions.types"

/** What a deck's `.session` may hold: a kiro session id (V2 UUID, V3 `sess_<uuid>`). */
const SESSION_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error))

/** A deck's own file `name`, or null when there is no such deck or the file resolves outside it. */
function deckFile(deckId: string, name: string): string | null {
  const dir = resolveDeckDir(deckId)
  return dir ? resolveWithin(dir, name) : null
}


/** Save sessionId to deck's .session file. Returns whether it was written (the deck exists). */
export function saveSessionToDeck(deckId: string, sessionId: string): boolean {
  const fs = require("fs") as typeof import("fs")
  const file = deckFile(deckId, ".session")
  if (!file) return false
  fs.writeFileSync(file, sessionId, "utf-8")
  return true
}

/** The kiro session id saved in a deck's .session file, or null when the deck has none (or not a valid id). */
export function readSessionFromDeck(deckId: string): string | null {
  const fs = require("fs") as typeof import("fs")
  const file = deckFile(deckId, ".session")
  if (!file) return null
  let saved: string
  try { saved = fs.readFileSync(file, "utf-8").trim() } catch { return null }
  if (!saved) return null
  if (!SESSION_ID_PATTERN.test(saved)) {
    console.warn("[acp] deck %s: .session does not hold a kiro session id; treating the deck as having none", deckId)
    return null
  }
  return saved
}

/** The engines that ran turns of the session a deck's `.session` names (`.session-engine`). */
export interface EngineMark {
  /** The engine that started the session's last turn. */
  last: EngineId
  /** Every engine that started a turn of it. */
  engines: EngineId[]
}

/** A deck from before the mark existed: every session then ran on V2. */
const UNMARKED: EngineMark = { last: "v2", engines: ["v2"] }
const ENGINE_MARK_FILE = ".session-engine"
const brokenMarksWarned = new Set<string>()

/** A deck's engine mark; a deck without one (or with a broken one, warned once) counts as V2 only. */
export function readEngineMark(deckId: string): EngineMark {
  const fs = require("fs") as typeof import("fs")
  const file = deckFile(deckId, ENGINE_MARK_FILE)
  if (!file) return UNMARKED
  let text: string
  try { text = fs.readFileSync(file, "utf-8") } catch { return UNMARKED }
  try {
    const raw = JSON.parse(text) as { version?: unknown; last?: unknown; engines?: unknown }
    if (raw?.version === 1 && isEngineId(raw.last) && Array.isArray(raw.engines) && raw.engines.length && raw.engines.every(isEngineId)) {
      return { last: raw.last, engines: [...new Set(raw.engines as EngineId[])] }
    }
  } catch { /* reported below */ }
  if (!brokenMarksWarned.has(deckId)) {
    brokenMarksWarned.add(deckId)
    console.warn("[acp] deck %s: %s is not readable; treating the deck as unmarked", deckId, ENGINE_MARK_FILE)
  }
  return UNMARKED
}

/** Replace a deck's engine mark (temp file + rename). A failure is logged: only a later notice is lost. */
export function writeEngineMark(deckId: string, mark: EngineMark): void {
  const fs = require("fs") as typeof import("fs")
  const file = deckFile(deckId, ENGINE_MARK_FILE)
  if (!file) return
  const tmp = `${file}.tmp-${process.pid}`
  try {
    fs.writeFileSync(tmp, JSON.stringify({ version: 1, last: mark.last, engines: mark.engines }), "utf-8")
    fs.renameSync(tmp, file)
  } catch (error) {
    console.warn("[acp] deck %s: could not write %s: %s", deckId, ENGINE_MARK_FILE, errorText(error))
    try { fs.rmSync(tmp, { force: true }) } catch { /* nothing to clean */ }
  }
}

/** Save a fork's source metadata to the deck. */
export function saveOriginToDeck(deckId: string, origin: SessionOrigin): void {
  const fs = require("fs") as typeof import("fs")
  const file = deckFile(deckId, ".session-origin.json")
  if (!file) return
  fs.writeFileSync(file, JSON.stringify(origin), "utf-8")
}

/** Read a fork's source metadata from the deck. */
export function readOriginFromDeck(deckId: string): SessionOrigin | null {
  const fs = require("fs") as typeof import("fs")
  const file = deckFile(deckId, ".session-origin.json")
  if (!file) return null
  try { return JSON.parse(fs.readFileSync(file, "utf-8")) as SessionOrigin } catch { return null }
}

/** Save chat messages to deck's .chat.json file; false when there is no such deck. */
export function saveChatToDeck(deckId: string, messages: unknown[]): boolean {
  const fs = require("fs") as typeof import("fs")
  const file = deckFile(deckId, ".chat.json")
  if (!file) return false
  fs.writeFileSync(file, JSON.stringify(messages), "utf-8")
  return true
}

/** Read chat messages from deck's .chat.json file. */
export function readChatFromDeck(deckId: string): unknown[] {
  const fs = require("fs") as typeof import("fs")
  const file = deckFile(deckId, ".chat.json")
  if (!file) return []
  try { return JSON.parse(fs.readFileSync(file, "utf-8")) } catch { return [] }
}
