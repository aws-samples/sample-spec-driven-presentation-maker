// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ComposeCard — Parallel composer agents as independent living cards.
 *
 * Design goals (evolved through iteration):
 *   - Quality comparable to main-stage waiting animations (意味のある動き)
 *   - Parallel agents visible as independent, asynchronously breathing entities
 *   - Instruction accessible via rich hover pop-out (no click)
 *   - Color semantics align with existing ToolCard CAT palette
 *
 * Information layers (independent axes):
 *   - Agent state  → left glyph color  (working=violet / retry=amber / error=red)
 *   - Slug status  → slug text color   (existing=violet accent / not yet=gray)
 *   - Activity     → activity text     (category color per tool)
 */

"use client"

import { useState, useMemo, useEffect, useRef } from "react"
import { parseComposeState, type AgentState, type ComposeState } from "./parseComposeState"
import { CAT } from "../toolPalette"

// --- Color tokens ---
const STATE = {
  working: CAT.produce.accent,   // violet — compose_slides is `produce` category
  done: CAT.produce.accent,
  retry: CAT.explore.accent,     // amber — "trying again"
  error: "oklch(0.65 0.2 25)",
}

const C = {
  fgStrong: "oklch(0.92 0.005 85)",
  fgMuted: "oklch(0.48 0 0)",
  fgInstruction: "oklch(0.72 0 0)",
  fgLabel: "oklch(0.82 0 0)",
  fgTime: "oklch(0.65 0 0)",
  fgActivity: "oklch(0.62 0 0)",
  fgActivityDim: "oklch(0.42 0 0)",
  smallLabel: "oklch(0.52 0 0)",
  existing: "oklch(0.82 0.10 300)", // violet-tinted — "written by compose"
  hairline: "oklch(1 0 0 / 5%)",
  hairlineStrong: "oklch(1 0 0 / 10%)",
  cardBg: "oklch(0.14 0.005 280 / 60%)",
  cardBgHover: "oklch(0.16 0.008 285 / 70%)",
  popBg: "oklch(0.14 0.008 290)",
}

/** Per-agent hue offset for subtle individuality (±10° around violet 300). */
function agentHue(groupIndex: number): number {
  // Deterministic offset: agent 1 → -12, agent 2 → -4, agent 3 → +4, agent 4 → +12, wrap
  const n = (groupIndex - 1) % 8
  const offsets = [-12, -4, 4, 12, -8, 8, -16, 16]
  return 300 + offsets[n]
}

function agentColor(groupIndex: number, status: AgentState["status"]): string {
  if (status === "retrying") return STATE.retry
  if (status === "error") return STATE.error
  const hue = agentHue(groupIndex)
  return `oklch(0.75 0.14 ${hue})`
}

function formatElapsed(ms: number): string {
  if (ms < 0) ms = 0
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, "0")}`
}

interface Timing { start: number; end: number | null }

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
  deckSlideIds?: string[]
}

export function ComposeCard({ input, status, isActive, streamMessages = [], deckSlideIds = [] }: ComposeCardProps) {
  const state: ComposeState = useMemo(
    () => parseComposeState(streamMessages, input),
    [streamMessages, input],
  )

  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!isActive) return
    const id = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(id)
  }, [isActive])

  const [startTime] = useState(() => Date.now())
  const timings = useAgentTimings(streamMessages, state.totalGroups, now)

  const isDone = !isActive && (status === "success" || state.phase === "done")
  const overallElapsed = isDone
    ? Math.max(...timings.map((t) => t.end || 0), now) - startTime
    : now - startTime

  const existingSlugs = new Set(deckSlideIds)

  const totalSlides = state.agents.reduce((sum, a) => sum + a.slugs.length, 0)

  return (
    <section
      aria-label="Composing slides"
      className="tool-card-enter relative"
    >
      <Header
        state={state}
        elapsed={overallElapsed}
        isDone={isDone}
        totalSlides={totalSlides}
      />
      <div className="relative mt-3 flex flex-col gap-2">
        {state.agents.map((agent, i) => (
          <AgentCard
            key={agent.groupIndex}
            agent={agent}
            existingSlugs={existingSlugs}
            timing={timings[i]}
            now={now}
            indexDelay={i}
          />
        ))}
      </div>
      <span className="sr-only" aria-live="polite">
        {state.doneGroupCount} of {state.totalGroups} agents completed
      </span>
    </section>
  )
}

// --- Header -----------------------------------------------------------------

function Header({
  state,
  elapsed,
  isDone,
  totalSlides,
}: {
  state: ComposeState
  elapsed: number
  isDone: boolean
  totalSlides: number
}) {
  const hasAgents = state.totalGroups > 0
  const label = isDone
    ? `Composed ${totalSlides || state.totalGroups} slides in ${formatElapsed(elapsed)}`
    : hasAgents
    ? `Composing ${totalSlides} slides · ${state.totalGroups} agents in parallel`
    : state.statusMessage || "Preparing…"

  return (
    <header className="flex items-baseline justify-between gap-3 px-1">
      <span
        className="text-[12.5px] tracking-[-0.01em] transition-colors duration-500 truncate"
        style={{ color: C.fgLabel }}
      >
        {label}
      </span>
      <span
        className="text-[11.5px] tabular-nums flex-none"
        style={{ color: C.fgTime, fontFamily: "var(--font-geist-mono, ui-monospace), monospace" }}
      >
        {formatElapsed(elapsed)}
      </span>
    </header>
  )
}

// --- Agent Card -------------------------------------------------------------

interface AgentCardProps {
  agent: AgentState
  existingSlugs: Set<string>
  timing: Timing
  now: number
  indexDelay: number
}

function AgentCard({ agent, existingSlugs, timing, now, indexDelay }: AgentCardProps) {
  const cardRef = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState(false)
  const [tilt, setTilt] = useState({ x: 0, y: 0 })
  const popTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const color = agentColor(agent.groupIndex, agent.status)
  const isWorking = agent.status === "working" || agent.status === "retrying"
  const isDone = agent.status === "done"
  const isError = agent.status === "error"

  const elapsedMs =
    timing.end !== null
      ? timing.end - timing.start
      : timing.start
      ? now - timing.start
      : 0

  const latestActivity = agent.activity.length
    ? agent.activity[agent.activity.length - 1]
    : null

  // Asynchronous breathing — phase offset per agent (independence).
  const breathDelay = `${(agent.groupIndex * 0.37) % 1.8}s`

  // --- Hover pop-out state ---
  function handleEnter() {
    if (popTimer.current) clearTimeout(popTimer.current)
    setHover(true)
  }
  function handleLeave() {
    if (popTimer.current) clearTimeout(popTimer.current)
    popTimer.current = setTimeout(() => setHover(false), 120)
    setTilt({ x: 0, y: 0 })
  }
  function handleMouseMove(e: React.MouseEvent) {
    const el = cardRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const px = (e.clientX - rect.left) / rect.width - 0.5
    const py = (e.clientY - rect.top) / rect.height - 0.5
    // Max 2deg tilt
    setTilt({ x: -py * 2, y: px * 2 })
  }

  const instructionPreview = agent.instruction
    ? agent.instruction.replace(/\s+/g, " ").trim()
    : ""

  return (
    <div
      ref={cardRef}
      className="agent-card relative rounded-xl overflow-visible"
      style={{
        background: hover ? C.cardBgHover : C.cardBg,
        boxShadow: `
          0 1px 0 oklch(1 0 0 / 4%) inset,
          0 2px 8px oklch(0 0 0 / 25%),
          0 0 0 1px oklch(1 0 0 / 5%)
        `,
        transform: `perspective(800px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
        transition: "background 160ms ease, transform 220ms ease",
        animation: `compose-card-enter 500ms cubic-bezier(0.22, 1, 0.36, 1) ${indexDelay * 80}ms both`,
      }}
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      onMouseMove={handleMouseMove}
    >
      <div className="relative px-3.5 py-3">
        {/* Agent state glyph */}
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className="relative flex-none w-2 h-2 rounded-full"
            style={{
              background: color,
              boxShadow: `0 0 0 0 ${color}`,
              animation: isWorking
                ? `compose-breath 1.8s ease-in-out ${breathDelay} infinite`
                : agent.status === "retrying"
                ? `compose-flicker 1.1s linear ${breathDelay} infinite`
                : isDone
                ? undefined
                : undefined,
              opacity: isError ? 0.8 : 1,
            }}
          />
          {/* Slugs */}
          <span className="flex-1 min-w-0 text-[13px] font-medium tracking-[-0.015em] truncate">
            {agent.slugs.map((slug, i) => (
              <span key={slug}>
                <span
                  className="transition-colors duration-500"
                  style={{ color: existingSlugs.has(slug) ? C.existing : C.fgMuted }}
                >
                  {slug}
                </span>
                {i < agent.slugs.length - 1 && <span style={{ color: C.fgMuted }}>, </span>}
              </span>
            ))}
          </span>
          {agent.status === "retrying" && (
            <span
              className="text-[10.5px] tabular-nums flex-none px-1.5 py-0.5 rounded"
              style={{
                color: STATE.retry,
                background: `${STATE.retry}14`,
                fontFamily: "var(--font-geist-mono, ui-monospace), monospace",
              }}
            >
              retry {agent.retryAttempt}
            </span>
          )}
          <time
            className="text-[10.5px] tabular-nums flex-none"
            style={{
              color: C.fgTime,
              fontFamily: "var(--font-geist-mono, ui-monospace), monospace",
            }}
          >
            {formatElapsed(elapsedMs)}
          </time>
        </div>

        {/* Instruction preview (inline truncate, 1 line) */}
        {instructionPreview && (
          <div
            className="mt-1.5 text-[11.5px] leading-snug truncate pl-[18px]"
            style={{ color: C.fgInstruction, fontStyle: "italic" }}
            title=""
          >
            {instructionPreview}
          </div>
        )}

        {/* Current activity */}
        {latestActivity && (
          <div className="mt-1.5 pl-[18px] flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="text-[10px]"
              style={{ color: C.fgActivityDim }}
            >
              ↳
            </span>
            <span
              className="text-[11px] truncate tracking-[-0.005em]"
              style={{ color: CAT[latestActivity.category].accent }}
            >
              {latestActivity.label}
              {latestActivity.status === "active" ? "…" : ""}
              {latestActivity.status === "error" ? "  ✗" : ""}
            </span>
          </div>
        )}
      </div>

      {/* Hover pop-out */}
      {hover && (
        <PopOut
          agent={agent}
          color={color}
        />
      )}
    </div>
  )
}

// --- Pop-out ----------------------------------------------------------------

function PopOut({ agent, color }: { agent: AgentState; color: string }) {
  return (
    <div
      role="tooltip"
      className="absolute left-0 right-0 top-full mt-2 z-20 rounded-xl overflow-hidden"
      style={{
        background: C.popBg,
        boxShadow: `
          0 1px 0 oklch(1 0 0 / 6%) inset,
          0 12px 40px oklch(0 0 0 / 50%),
          0 4px 12px oklch(0 0 0 / 35%),
          0 0 0 1px oklch(1 0 0 / 6%)
        `,
        animation: "compose-popout-enter 220ms cubic-bezier(0.22, 1, 0.36, 1) both",
      }}
    >
      {/* Top accent line — agent's color */}
      <div
        aria-hidden="true"
        className="h-[1px] w-full"
        style={{ background: `linear-gradient(90deg, transparent, ${color} 40%, ${color} 60%, transparent)` }}
      />
      <div className="p-5">
        {/* Instruction */}
        <div>
          <div
            className="text-[9.5px] font-medium uppercase mb-2"
            style={{ color: C.smallLabel, letterSpacing: "0.14em" }}
          >
            Instruction
          </div>
          <div
            className="text-[13px] whitespace-pre-wrap"
            style={{
              color: C.fgLabel,
              fontFamily: "'Instrument Serif', Cambria, Georgia, serif",
              fontSize: "14.5px",
              lineHeight: 1.65,
            }}
          >
            {agent.instruction || <span style={{ color: C.fgMuted }}>(no instruction)</span>}
          </div>
        </div>

        {/* Activity timeline */}
        <div className="mt-4">
          <div className="flex items-center justify-between mb-2">
            <div
              className="text-[9.5px] font-medium uppercase"
              style={{ color: C.smallLabel, letterSpacing: "0.14em" }}
            >
              Activity
            </div>
            <div className="text-[10px] tabular-nums" style={{ color: C.fgActivityDim }}>
              {agent.activity.length} step{agent.activity.length === 1 ? "" : "s"}
            </div>
          </div>
          {agent.activity.length === 0 ? (
            <div className="text-[11.5px]" style={{ color: C.fgActivityDim }}>
              No activity yet.
            </div>
          ) : (
            <ol className="flex flex-col gap-1">
              {agent.activity.map((a, i) => {
                const catColor = CAT[a.category].accent
                const textColor =
                  a.status === "error"
                    ? STATE.error
                    : a.status === "active"
                    ? catColor
                    : `color-mix(in oklch, ${catColor} 55%, transparent)`
                return (
                  <li
                    key={a.toolUseId}
                    className="flex items-center gap-2"
                    style={{
                      animation: `compose-popout-row-enter 240ms cubic-bezier(0.22, 1, 0.36, 1) ${i * 40}ms both`,
                    }}
                  >
                    <span
                      aria-hidden="true"
                      className="flex-none w-1.5 h-1.5 rounded-full"
                      style={{
                        background: catColor,
                        opacity: a.status === "active" ? 1 : 0.4,
                        boxShadow: a.status === "active" ? `0 0 8px ${catColor}` : undefined,
                        animation: a.status === "active"
                          ? "compose-breath 1.4s ease-in-out infinite"
                          : undefined,
                      }}
                    />
                    <span className="text-[11.5px] tracking-[-0.005em] truncate" style={{ color: textColor }}>
                      {a.label}
                      {a.status === "active" ? "…" : ""}
                      {a.status === "error" ? "  ✗" : ""}
                    </span>
                  </li>
                )
              })}
            </ol>
          )}
        </div>

        {/* Error detail */}
        {agent.status === "error" && agent.errorMsg && (
          <div
            className="mt-3 text-[11px] p-2.5 rounded-lg"
            style={{ background: `${STATE.error}12`, color: STATE.error }}
          >
            {agent.errorMsg}
          </div>
        )}
      </div>
    </div>
  )
}
