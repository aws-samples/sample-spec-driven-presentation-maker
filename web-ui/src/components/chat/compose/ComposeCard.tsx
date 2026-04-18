// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ComposeCard — Quiet informant view of parallel composer agents.
 *
 * Role: side window during compose_slides execution. Surfaces:
 *   - per-agent state (working / done / retry / error)
 *   - per-agent slug existence (strong = written, muted = not yet)
 *   - per-agent instruction (inline expand)
 *   - per-agent activity log (natural verb phrases)
 *
 * Main-stage drama is handled elsewhere (AnimatedSlidePreview);
 * this card is intentionally restrained.
 */

"use client"

import { useState, useMemo, useEffect } from "react"
import { ChevronDown } from "lucide-react"
import { parseComposeState, type AgentState, type ComposeState } from "./parseComposeState"

// --- Color tokens (oklch for perceptual uniformity) ---
const C = {
  fgStrong: "oklch(0.92 0.005 85)",
  fgMuted: "oklch(0.45 0 0)",
  fgLabel: "oklch(0.82 0 0)",
  fgTime: "oklch(0.70 0 0)",
  fgActivity: "oklch(0.62 0 0)",
  fgActivityDim: "oklch(0.42 0 0)",
  chevron: "oklch(0.50 0 0)",
  heroFg: "oklch(0.92 0 0)",
  smallLabel: "oklch(0.55 0 0)",
  working: "oklch(0.78 0.10 200)",
  done: "oklch(0.80 0.08 85)",
  retry: "oklch(0.80 0.14 60)",
  error: "oklch(0.70 0.15 25)",
  hairline: "oklch(1 0 0 / 6%)",
  hairlineStrong: "oklch(1 0 0 / 10%)",
  rowHover: "oklch(1 0 0 / 2%)",
  instructionBg: "oklch(1 0 0 / 2%)",
}

function stateColor(s: AgentState["status"]): string {
  switch (s) {
    case "working": return C.working
    case "done": return C.done
    case "retrying": return C.retry
    case "error": return C.error
    default: return C.fgMuted
  }
}

function formatElapsed(ms: number): string {
  if (ms < 0) ms = 0
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, "0")}`
}

interface Timing { start: number; end: number | null }

/** Derive agent timings from stream events (group-scoped start/done). */
function useAgentTimings(stream: Record<string, unknown>[], totalGroups: number, now: number): Timing[] {
  return useMemo(() => {
    const timings: Timing[] = Array.from({ length: totalGroups }, () => ({ start: 0, end: null }))
    for (const ev of stream) {
      const g = typeof ev.group === "number" ? ev.group : 0
      if (g < 1 || g > totalGroups) continue
      const t = typeof ev._ts === "number" ? (ev._ts as number) : now
      const idx = g - 1
      if (ev.status === "starting" && !timings[idx].start) timings[idx].start = t
      else if (ev.status === "done" || ev.status === "error") timings[idx].end = t
      else if (ev.status === "retrying") {
        timings[idx].start = t
        timings[idx].end = null
      }
    }
    return timings
  }, [stream, totalGroups, now])
}

interface ComposeCardProps {
  input?: Record<string, unknown>
  status?: "success" | "error"
  result?: Record<string, unknown>
  isActive: boolean
  streamMessages?: Record<string, unknown>[]
  /** Slide IDs currently in the deck — used for strong/muted slug rendering. */
  deckSlideIds?: string[]
}

export function ComposeCard({ input, status, isActive, streamMessages = [], deckSlideIds = [] }: ComposeCardProps) {
  const state: ComposeState = useMemo(
    () => parseComposeState(streamMessages, input),
    [streamMessages, input],
  )

  // Ticker for live time display while working.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!isActive) return
    const id = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(id)
  }, [isActive])

  // Capture overall start time on first render (lazy init).
  const [startTime] = useState(() => Date.now())

  const timings = useAgentTimings(streamMessages, state.totalGroups, now)

  const isDone = !isActive && (status === "success" || state.phase === "done")
  const overallElapsed = isDone
    ? // prefer latest end time we have
      Math.max(...timings.map((t) => t.end || 0), now) - startTime
    : now - startTime

  const existingSlugs = new Set(deckSlideIds)

  return (
    <section
      aria-label="Composing slides"
      className="tool-card-enter relative rounded-2xl overflow-hidden"
      style={{ background: "oklch(0 0 0 / 20%)", boxShadow: `inset 0 0 0 1px ${C.hairline}` }}
    >
      <Header
        state={state}
        elapsed={overallElapsed}
        isDone={isDone}
      />
      <ul role="list" className="flex flex-col">
        {state.agents.map((a, i) => (
          <AgentRow
            key={a.groupIndex}
            agent={a}
            existingSlugs={existingSlugs}
            timing={timings[i]}
            now={now}
            isLast={i === state.agents.length - 1}
          />
        ))}
      </ul>
      <span className="sr-only" aria-live="polite">
        {state.doneGroupCount} of {state.totalGroups} agents completed
      </span>
    </section>
  )
}

// --- Header -----------------------------------------------------------------

function Header({ state, elapsed, isDone }: { state: ComposeState; elapsed: number; isDone: boolean }) {
  const label = isDone ? "Composed" : "Composing"
  const timeLabel = isDone ? `in ${formatElapsed(elapsed)}` : formatElapsed(elapsed)
  const heroNumber = isDone ? String(state.totalGroups) : `${state.doneGroupCount} / ${state.totalGroups}`
  const heroCaption = isDone ? "slides composed" : "agents"

  return (
    <header className="px-5 pt-5 pb-4" style={{ borderBottom: `1px solid ${C.hairline}` }}>
      <div className="flex items-baseline justify-between">
        <span
          className="text-[13px] font-medium tracking-[-0.01em] transition-colors duration-500"
          style={{ color: C.fgLabel }}
        >
          {label}
        </span>
        <span
          className="text-[12px] tabular-nums"
          style={{ color: C.fgTime, fontFamily: "var(--font-geist-mono, ui-monospace), monospace" }}
        >
          {timeLabel}
        </span>
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <span
          className="leading-none"
          style={{
            color: C.heroFg,
            fontFamily: "'Instrument Serif', 'Cambria', Georgia, serif",
            fontSize: "36px",
            letterSpacing: "-0.02em",
          }}
        >
          {heroNumber}
        </span>
      </div>
      <div
        className="mt-1 text-[10px] font-medium uppercase"
        style={{ color: C.smallLabel, letterSpacing: "0.12em" }}
      >
        {heroCaption}
      </div>
      {state.statusMessage && (
        <div className="mt-3 text-[11px]" style={{ color: C.fgTime }}>
          {state.statusMessage}
        </div>
      )}
    </header>
  )
}

// --- Agent Row --------------------------------------------------------------

interface AgentRowProps {
  agent: AgentState
  existingSlugs: Set<string>
  timing: Timing
  now: number
  isLast: boolean
}

function AgentRow({ agent, existingSlugs, timing, now, isLast }: AgentRowProps) {
  const [expanded, setExpanded] = useState(false)
  const barColor = stateColor(agent.status)
  const isWorking = agent.status === "working" || agent.status === "retrying"
  const isDone = agent.status === "done"

  const elapsedMs =
    timing.end !== null
      ? timing.end - timing.start
      : timing.start
      ? now - timing.start
      : 0
  const timeDisplay = isDone ? formatElapsed(elapsedMs) : formatElapsed(elapsedMs)

  const latestActivity = agent.activity.length
    ? agent.activity[agent.activity.length - 1]
    : null

  const panelId = `compose-agent-${agent.groupIndex}`

  return (
    <li style={{ borderBottom: isLast ? "none" : `1px solid ${C.hairline}` }}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-controls={panelId}
        className="relative w-full flex items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-white/[0.02] focus-visible:outline-none focus-visible:bg-white/[0.03]"
      >
        {/* Left vertical bar */}
        <span
          aria-hidden="true"
          className="absolute left-0 top-0 bottom-0 w-[2px] compose-bar"
          style={{
            background: barColor,
            opacity: isDone ? 0.7 : isWorking ? 0.85 : 0.4,
            animation:
              agent.status === "working"
                ? "compose-bar-breath 1.6s ease-in-out infinite"
                : agent.status === "retrying"
                ? "compose-bar-flicker 1.1s linear infinite"
                : undefined,
          }}
        />
        {/* Slugs */}
        <span className="flex-1 min-w-0 text-[13.5px] font-medium tracking-[-0.015em] truncate">
          {agent.slugs.map((slug, i) => (
            <span key={slug}>
              <span
                className="transition-colors duration-500"
                style={{ color: existingSlugs.has(slug) ? C.fgStrong : C.fgMuted }}
              >
                {slug}
              </span>
              {i < agent.slugs.length - 1 && <span style={{ color: C.fgMuted }}>, </span>}
            </span>
          ))}
        </span>
        {/* Retry info inline */}
        {agent.status === "retrying" && (
          <span
            className="text-[11px] tabular-nums"
            style={{
              color: C.retry,
              fontFamily: "var(--font-geist-mono, ui-monospace), monospace",
            }}
          >
            retry {agent.retryAttempt}
          </span>
        )}
        {/* Elapsed time */}
        <time
          className="text-[12px] tabular-nums flex-none"
          style={{
            color: isDone ? C.fgTime : C.fgTime,
            fontFamily: isDone
              ? "'Instrument Serif', Cambria, Georgia, serif"
              : "var(--font-geist-mono, ui-monospace), monospace",
            fontSize: isDone ? "13px" : "12px",
          }}
        >
          {timeDisplay}
        </time>
        {/* Chevron */}
        <ChevronDown
          className="h-3.5 w-3.5 flex-none transition-transform duration-200"
          style={{ color: C.chevron, transform: expanded ? "rotate(180deg)" : "rotate(0deg)" }}
        />
      </button>

      {/* Latest activity — hint while collapsed */}
      {!expanded && latestActivity && (
        <div className="px-4 pb-2 -mt-1 pl-6">
          <span
            className="text-[11.5px] tracking-[-0.005em]"
            style={{ color: C.fgActivity }}
          >
            <span style={{ color: C.fgActivityDim, marginRight: "6px" }}>╰</span>
            {latestActivity.label}
            {latestActivity.status === "active" ? "…" : ""}
          </span>
        </div>
      )}

      {/* Expanded detail */}
      <div
        id={panelId}
        hidden={!expanded}
        className="px-5 pb-5"
        style={{ background: expanded ? "oklch(1 0 0 / 1.5%)" : undefined }}
      >
        {expanded && (
          <>
            {/* Instruction (quoted) */}
            <div className="mt-3 mb-5">
              <div
                className="text-[10px] font-medium uppercase mb-2"
                style={{ color: C.smallLabel, letterSpacing: "0.14em" }}
              >
                Instruction
              </div>
              <div
                className="relative py-3 pl-6 pr-4 rounded-lg"
                style={{ background: C.instructionBg }}
              >
                <span
                  aria-hidden="true"
                  className="absolute top-1 left-2 leading-none"
                  style={{
                    color: C.fgMuted,
                    fontFamily: "'Instrument Serif', Cambria, Georgia, serif",
                    fontSize: "22px",
                  }}
                >
                  &ldquo;
                </span>
                <div
                  className="text-[12.5px] whitespace-pre-wrap"
                  style={{ color: C.fgLabel, lineHeight: 1.7 }}
                >
                  {agent.instruction || <span style={{ color: C.fgMuted }}>(no instruction)</span>}
                </div>
              </div>
            </div>

            {/* Activity log */}
            <div>
              <div
                className="text-[10px] font-medium uppercase mb-2"
                style={{ color: C.smallLabel, letterSpacing: "0.14em" }}
              >
                Activity
              </div>
              {agent.activity.length === 0 ? (
                <div className="text-[12px]" style={{ color: C.fgActivityDim }}>
                  No activity yet.
                </div>
              ) : (
                <ol className="relative pl-3" style={{ borderLeft: `1px solid ${C.hairlineStrong}` }}>
                  {agent.activity.map((a) => (
                    <li key={a.toolUseId} className="py-1.5 pl-2 relative">
                      <span
                        aria-hidden="true"
                        className="absolute -left-[5px] top-[11px] w-[9px] h-[1px]"
                        style={{ background: C.hairlineStrong }}
                      />
                      <span
                        className="text-[12px]"
                        style={{
                          color:
                            a.status === "error"
                              ? C.error
                              : a.status === "active"
                              ? C.fgActivity
                              : C.fgActivityDim,
                        }}
                      >
                        {a.label}
                        {a.status === "active" ? "…" : ""}
                        {a.status === "error" ? "  ✗" : ""}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </div>

            {/* Error detail */}
            {agent.status === "error" && agent.errorMsg && (
              <div
                className="mt-4 text-[11.5px] p-3 rounded-lg"
                style={{ background: "oklch(0.70 0.15 25 / 8%)", color: C.error }}
              >
                {agent.errorMsg}
              </div>
            )}
          </>
        )}
      </div>
    </li>
  )
}
