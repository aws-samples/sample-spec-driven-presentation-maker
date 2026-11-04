// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AgentCore Service - the agent connection.
 *
 * Cloud: one WebSocket per session work period (services/sessionSocket.ts) to the agent's
 * `/ws` entry. `invokeAgentCore` sends a prompt and follows the session until it goes idle;
 * `steerAgentCore` sends a message into the running work; `cancelAgentCore` is the stop
 * button (StopRuntimeSession when the cancel is not acknowledged); `resumeAgentCore`
 * follows a session that is working after a reload; `prepareAgentCore` builds the session
 * early on the new deck screen. Events go through the same parser as before.
 *
 * Local: Server-Sent Events from the Next.js API Route (unchanged).
 */

import * as parser from './strandsParser.js';
import { SessionSocket } from './sessionSocket';
import { getAllowedModels } from "@/lib/allowedModels";
import { IS_LOCAL } from "@/lib/mode";
import { newSessionId } from "@/lib/sessionId";

// Read the user's selected chat model from localStorage, validated against the allowed list.
function readSelectedChatModelId() {
  try {
    const allowed = getAllowedModels();
    if (allowed.length === 0) return undefined;
    const prefs = JSON.parse(localStorage.getItem("sdpm-prefs") || "{}");
    if (prefs.chatModelId && allowed.some((m) => m.modelId === prefs.chatModelId)) {
      return prefs.chatModelId;
    }
  } catch { /* ignore */ }
  return undefined;
}

function readSelectedCreateModelId() {
  try {
    const allowed = getAllowedModels();
    if (allowed.length === 0) return undefined;
    const prefs = JSON.parse(localStorage.getItem("sdpm-prefs") || "{}");
    if (prefs.createModelId) {
      const model = allowed.find((m) => m.modelId === prefs.createModelId);
      if (model && model.composable !== false) return prefs.createModelId;
    }
  } catch { /* ignore */ }
  return undefined;
}

// Generate a UUID
const generateId = () => {
  return crypto.randomUUID();
}

// Configuration - will be populated from aws-exports.json
const AGENT_CONFIG = {
  AGENT_RUNTIME_ARN: "",
  AWS_REGION: "us-east-1",
}

// Set configuration from environment or aws-exports
export const setAgentConfig = (runtimeArn, region = "us-east-1") => {
  AGENT_CONFIG.AGENT_RUNTIME_ARN = runtimeArn
  AGENT_CONFIG.AWS_REGION = region
}

/**
 * Invokes the agent. Cloud: sends a prompt over the session's WebSocket and follows the
 * session until it goes idle (steers and the turns they start included); resolves the
 * accumulated text. `onSession` (Cloud) gets `onEvent(ev, {own})` for the session's
 * `work` / `turn` / `turnEnd` / `steer` events and `onReconnecting(active)`.
 */
export const invokeAgentCore = async (query, sessionId, onStreamUpdate, accessToken, userId, onToolUse, signal, mode, deckId, continuedFrom, translateError, onSession) => {
  // Local mode: proxy through Next.js API Route → kiro-cli acp
  if (IS_LOCAL) {
    return invokeLocalAgent(query, sessionId, onStreamUpdate, onToolUse, signal, mode, deckId, continuedFrom);
  }

  if (!userId) {
    throw new Error("No valid user ID found in session. Please ensure you are authenticated.")
  }
  if (!accessToken) {
    throw new Error("No valid access token found. Please ensure you are authenticated.")
  }
  if (!AGENT_CONFIG.AGENT_RUNTIME_ARN) {
    throw new Error("Agent Runtime ARN not configured")
  }

  const entry = sessionEntry(sessionId, accessToken)
  if (entry.follower) finish(entry, new Error("Superseded by a newer request"))
  if (parser.resetParserState) parser.resetParserState();
  const id = generateId()
  entry.ownIds.add(id)
  const done = follow(entry, { onStreamUpdate, onToolUse, onSession, translateError }, signal, { promptId: id })
  entry.socket.send({ type: "prompt", id, prompt: query, mode: mode || "spec", ...selectedModels() })
  return done
}

// --- Cloud session connection (WebSocket) -------------------------------------------

/** How long a steer or a cancel waits for its acknowledgement. */
export const STEER_ACK_MS = 3000
export const CANCEL_ACK_MS = 3000
/** After a cancel is acknowledged, how long the stop waits for the session to go idle. */
export const STOP_SETTLE_MS = 2000
const PREPARE_LIMIT_MS = 60_000

const SESSION_EVENT_KEYS = ["work", "turn", "turnEnd", "steer"]

/** sessionId → { socket, token, follower, ownIds, waiters } */
const sessions = new Map()

function selectedModels() {
  const chatModelId = readSelectedChatModelId();
  const createModelId = readSelectedCreateModelId();
  return {
    ...(chatModelId ? { chatModelId } : {}),
    ...(createModelId ? { createModelId } : {}),
  }
}

function sessionWsUrl(sessionId) {
  const endpoint = `wss://bedrock-agentcore.${AGENT_CONFIG.AWS_REGION}.amazonaws.com`
  const arn = encodeURIComponent(AGENT_CONFIG.AGENT_RUNTIME_ARN)
  return `${endpoint}/runtimes/${arn}/ws?qualifier=DEFAULT&X-Amzn-Bedrock-AgentCore-Runtime-Session-Id=${encodeURIComponent(sessionId)}`
}

function sessionEntry(sessionId, accessToken) {
  let entry = sessions.get(sessionId)
  if (!entry) {
    entry = { token: accessToken, follower: null, ownIds: new Set(), waiters: new Map(), socket: null }
    const current = entry
    entry.socket = new SessionSocket({
      url: sessionWsUrl(sessionId),
      sessionId,
      getToken: () => current.token,
      listener: sessionListener(current),
    })
    sessions.set(sessionId, entry)
  }
  if (accessToken) entry.token = accessToken
  return entry
}

/** Follow the session's events until it goes idle with nothing unanswered. */
function follow(entry, handlers, signal, extra) {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  const follower = {
    handlers, completion: "", accepted: false, idleSeen: false, resuming: false, wasWorking: false,
    promptId: undefined, resolve, reject, promise, onAbort: undefined, ...extra,
  }
  if (signal) {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"))
      return promise
    }
    // Detach only: leaving never cancels the session's work.
    follower.onAbort = () => { if (entry.follower === follower) finish(entry, new DOMException("Aborted", "AbortError")) }
    signal.addEventListener("abort", follower.onAbort, { once: true })
    follower.signal = signal
  }
  entry.follower = follower
  return promise
}

function finish(entry, error) {
  const follower = entry.follower
  if (!follower) return
  entry.follower = null
  if (follower.signal && follower.onAbort) follower.signal.removeEventListener("abort", follower.onAbort)
  if (error) follower.reject(error)
  else follower.resolve(follower.completion)
}

function settle(entry) {
  const follower = entry.follower
  if (follower && follower.idleSeen && !follower.resuming && entry.socket.pendingCount === 0) finish(entry, null)
}

function takeWaiter(entry, key) {
  if (key === undefined) return undefined
  const waiter = entry.waiters.get(key)
  if (waiter) {
    entry.waiters.delete(key)
    clearTimeout(waiter.timer)
  }
  return waiter
}

/** Send a message and wait for its answer (rejects after `ms`). */
function waitFor(entry, key, ms, send) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      entry.waiters.delete(key)
      entry.socket.forget(key)
      reject(new Error("The agent did not answer in time"))
    }, ms)
    entry.waiters.set(key, { resolve, reject, timer })
    send()
  })
}

function agentError(ctl) {
  return Object.assign(new Error(ctl.error || "Agent error"), { code: ctl.code })
}

function sessionListener(entry) {
  return {
    onItem({ ev }) {
      const follower = entry.follower
      if (!follower) return
      if (SESSION_EVENT_KEYS.some((k) => k in ev)) {
        const id = ev.turn?.id ?? ev.steer?.id
        follower.handlers.onSession?.onEvent?.(ev, { own: !!id && entry.ownIds.has(id) })
        if (ev.work?.state === "idle") {
          follower.idleSeen = true
          settle(entry)
        } else if (ev.work?.state === "busy") {
          follower.idleSeen = false
        }
        return
      }
      const { onStreamUpdate, onToolUse, translateError } = follower.handlers
      follower.completion = parser.parseEvent(ev, follower.completion, onStreamUpdate, onToolUse, translateError)
    },
    onCtl(ctl, answered) {
      const follower = entry.follower
      switch (ctl.ctl) {
        case "accepted":
          takeWaiter(entry, answered)?.resolve({ id: ctl.id, as: ctl.as })
          if (follower) {
            if (answered && answered === follower.promptId) follower.accepted = true
            if (ctl.as === "turn") follower.idleSeen = false
          }
          break
        case "resumeAck":
          if (follower && follower.resuming) {
            follower.resuming = false
            follower.wasWorking = ctl.working === true
            follower.handlers.onResumeAck?.(ctl)
            if (!follower.wasWorking) follower.idleSeen = true
          }
          break
        case "cancelAck":
          takeWaiter(entry, answered)?.resolve(ctl.result)
          break
        case "ready":
          takeWaiter(entry, "prepare")?.resolve(ctl.mcp_status)
          break
        case "error": {
          const error = agentError(ctl)
          if (answered === undefined) {
            takeWaiter(entry, "prepare")?.reject(error)
          } else if (follower && ((answered === follower.promptId && !follower.accepted) || (answered === "resume" && follower.resuming))) {
            finish(entry, error)
          } else {
            takeWaiter(entry, answered)?.reject(error)
          }
          break
        }
        default:
          break
      }
      settle(entry)
    },
    onReconnecting(active) {
      entry.follower?.handlers.onSession?.onReconnecting?.(active)
    },
    onClosed({ lost, reconnecting, gaveUp }) {
      const error = new Error("The connection to the agent closed")
      for (const key of lost) takeWaiter(entry, key)?.reject(error)
      const follower = entry.follower
      if (!follower) return
      const promptLost = follower.promptId !== undefined && lost.includes(follower.promptId) && !follower.accepted
      if (gaveUp || promptLost || (!reconnecting && !follower.idleSeen)) finish(entry, error)
      else settle(entry)
    },
  }
}

/** Stop following a session: the page shows it stopped and forgets its work. */
function detach(entry) {
  finish(entry, null)
  entry.socket.markIdle()
  entry.socket.close()
}

/**
 * Send a message into the session's running work (a steer). Resolves `{id, as}` when the
 * agent accepted it (`as`: "steer", or "turn" when the work had just ended); rejects when
 * it was not acknowledged within STEER_ACK_MS.
 */
export const steerAgentCore = (sessionId, text, accessToken, id = generateId()) => {
  if (IS_LOCAL) return Promise.reject(new Error("Steer is a Cloud feature"))
  const entry = sessionEntry(sessionId, accessToken)
  entry.ownIds.add(id)
  return waitFor(entry, id, STEER_ACK_MS, () => entry.socket.send({ type: "steer", id, text }))
}

/**
 * The stop button. Sends `cancel`; with an acknowledgement, waits up to STOP_SETTLE_MS for
 * the session to go idle, then shows it stopped either way. Without one within
 * CANCEL_ACK_MS, falls back to StopRuntimeSession. Resolves "idle" | "stopped" | "fallback".
 */
export const cancelAgentCore = async (sessionId, accessToken) => {
  const entry = sessionEntry(sessionId, accessToken)
  const id = generateId()
  let result
  try {
    result = await waitFor(entry, `cancel:${id}`, CANCEL_ACK_MS, () => entry.socket.send({ type: "cancel", id }))
  } catch {
    detach(entry)
    void stopRuntimeSession(sessionId, accessToken)
    return "fallback"
  }
  const follower = entry.follower
  if (result === "cancelling" && follower) {
    let timer
    await Promise.race([
      follower.promise.catch(() => undefined),
      new Promise((resolve) => { timer = setTimeout(resolve, STOP_SETTLE_MS) }),
    ])
    clearTimeout(timer)
  }
  if (entry.follower === follower && follower) detach(entry)
  return result === "idle" ? "idle" : "stopped"
}

/**
 * Follow a session that may be working (after a reload): `resume {from_seq}`. The handlers
 * get `onResumeAck(ack)` first, then the replayed and live events as in invokeAgentCore.
 * Resolves `{working, completion}` when the session is idle (`working`: it was working).
 */
export const resumeAgentCore = async (sessionId, accessToken, fromSeq, handlers) => {
  if (IS_LOCAL) return { working: false, completion: "" }
  const entry = sessionEntry(sessionId, accessToken)
  if (entry.follower) finish(entry, new Error("Superseded by a resume"))
  if (parser.resetParserState) parser.resetParserState();
  const done = follow(entry, handlers || {}, undefined, { resuming: true })
  const follower = entry.follower
  entry.socket.send({ type: "resume", from_seq: fromSeq || 0 })
  const completion = await done
  return { working: follower.wasWorking, completion }
}

/**
 * Build the session early (the new deck screen): `prepare`, no turn and no Memory write.
 * The connection stays open until `ready`, so a send before then goes over it (the same VM).
 * Resolves the MCP status list.
 */
export const prepareAgentCore = async (sessionId, accessToken, mode) => {
  if (IS_LOCAL || !accessToken || !AGENT_CONFIG.AGENT_RUNTIME_ARN) return undefined
  const entry = sessionEntry(sessionId, accessToken)
  entry.socket.hold()
  try {
    return await waitFor(entry, "prepare", PREPARE_LIMIT_MS,
      () => entry.socket.send({ type: "prepare", mode: mode || "spec", ...selectedModels() }))
  } finally {
    entry.socket.release()
  }
}

/**
 * Stop a running AgentCore Runtime session.
 * Immediately terminates the specified session and stops any ongoing streaming responses,
 * including all ThreadPool-based composer agents inside the container.
 * Fire-and-forget: errors are logged but not thrown.
 */
export const stopRuntimeSession = async (sessionId, accessToken) => {
  try {
    if (!sessionId || !accessToken || !AGENT_CONFIG.AGENT_RUNTIME_ARN) return
    const endpoint = `https://bedrock-agentcore.${AGENT_CONFIG.AWS_REGION}.amazonaws.com`
    const escapedAgentArn = encodeURIComponent(AGENT_CONFIG.AGENT_RUNTIME_ARN)
    const url = `${endpoint}/runtimes/${escapedAgentArn}/stopruntimesession?qualifier=DEFAULT`
    await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sessionId,
      },
    })
  } catch (error) {
    console.error("Error stopping AgentCore session:", error)
  }
}

/**
 * Generate a new session ID. Cloud ids carry the owner prefix of `sub` (lib/sessionId.ts).
 */
export const generateSessionId = (sub) => {
  return IS_LOCAL || !sub ? generateId() : newSessionId(sub)
}

/**
 * Invoke the local ACP agent via API Route.
 * Reads SSE stream from /api/agent/invoke and feeds events through the same
 * strandsParser used by the cloud path, so ChatPanel works unchanged.
 */
const invokeLocalAgent = async (query, sessionId, onStreamUpdate, onToolUse, signal, mode, deckId, continuedFrom) => {
  const response = await fetch('/api/agent/invoke', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      sessionId,
      mode: mode || 'spec',
      deckId: deckId || undefined,
      continuedFrom: continuedFrom || undefined,
    }),
    signal,
  });

  if (!response.ok) {
    const errorText = await response.text();
    console.error('[invokeLocal] error:', errorText);
    const error = new Error(`Local agent error: ${response.status}: ${errorText}`);
    // 409 session conflicts carry a stable `code` (lib/local/sessionErrors.ts) the chat UI translates.
    try { error.code = JSON.parse(errorText).code; } catch { /* non-JSON body */ }
    throw error;
  }

  let completion = '';
  let buffer = '';

  if (parser.resetParserState) parser.resetParserState();

  if (response.body) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        buffer += chunk;
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.trim()) {
            if (line.startsWith('data: ')) {
              let event;
              try { event = JSON.parse(line.substring(6).trim()); } catch { /* parser handles malformed lines */ }
              if (event?.status === 'error' && event.error) throw new Error(event.error);
            }
            completion = parser.parseStreamingChunk(line, completion, onStreamUpdate, onToolUse);
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  return completion;
}
