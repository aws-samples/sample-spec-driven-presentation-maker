// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Spec waiting animations — shown while the agent is drafting each spec file.
 *
 * BriefWaiting: page being written with colorful lines and glowing cursor.
 * OutlineWaiting: tree growing with trunk, branches, and colorful nodes.
 * ArtDirectionWaiting: orbiting color dots with glow trails and pointer interaction.
 */

"use client"

import { useCallback, useRef } from "react"

export const WAIT_COLORS = [
  { css: "var(--wait-teal)", raw: "oklch(0.75 0.14 185)" },
  { css: "var(--wait-amber)", raw: "oklch(0.82 0.16 75)" },
  { css: "var(--wait-magenta)", raw: "oklch(0.70 0.18 330)" },
  { css: "var(--wait-green)", raw: "oklch(0.78 0.15 145)" },
]

/** Brief: page being written with colorful lines and glowing cursor. */
export function BriefWaiting() {
  const lines = [
    { w: 85, color: 0 }, { w: 65, color: 1 }, { w: 90, color: 2 },
    { w: 50, color: 3 }, { w: 75, color: 0 }, { w: 60, color: 1 },
  ]
  return (
    <div className="brief-waiting flex flex-col items-center gap-6">
      <div
        className="w-64 rounded-2xl p-6 flex flex-col gap-2.5"
        style={{
          background: "oklch(0.13 0.005 260)",
          border: "1px solid oklch(1 0 0 / 6%)",
          boxShadow: "0 0 40px oklch(0.75 0.14 185 / 6%), 0 8px 32px oklch(0 0 0 / 40%)",
        }}
      >
        {lines.map((l, i) => (
          <div
            key={i}
            className="brief-line-el h-[5px] rounded-full"
            style={{
              width: `${l.w}%`,
              background: WAIT_COLORS[l.color].raw,
              opacity: 0.5,
              animation: `brief-line 3s ease-in-out ${i * 0.35}s infinite`,
            }}
          />
        ))}
        <div className="flex items-center mt-1">
          <div
            className="brief-cursor-glow w-[3px] h-5 rounded-full"
            style={{
              background: WAIT_COLORS[0].raw,
              boxShadow: `0 0 12px ${WAIT_COLORS[0].raw}`,
              animation: "brief-cursor 0.8s step-end infinite",
              transition: "box-shadow 0.3s ease",
            }}
          />
        </div>
      </div>
      <p className="text-sm text-foreground-muted">Drafting the brief…</p>
    </div>
  )
}

/** Outline: tree growing with trunk, branches, and colorful nodes. */
export function OutlineWaiting() {
  const nodes = [
    { level: 0, color: 0 }, { level: 1, color: 2 }, { level: 1, color: 3 },
    { level: 0, color: 1 }, { level: 1, color: 0 }, { level: 1, color: 2 },
    { level: 0, color: 3 },
  ]
  return (
    <div className="outline-waiting flex flex-col items-center gap-6">
      <div className="relative w-56" style={{ height: 220 }}>
        {/* Trunk line */}
        <div
          className="absolute left-[14px] top-0 w-[2px] rounded-full"
          style={{
            background: `linear-gradient(to bottom, ${WAIT_COLORS[0].raw}, ${WAIT_COLORS[1].raw})`,
            animation: "outline-trunk-grow 1.2s ease-out both",
            height: "100%",
          }}
        />
        {/* Nodes */}
        {nodes.map((n, i) => {
          const c = WAIT_COLORS[n.color]
          const y = i * 30
          const isParent = n.level === 0
          const size = isParent ? 12 : 9
          const left = isParent ? 9 : 28
          return (
            <div key={i} className="absolute flex items-center" style={{ top: y, left }}>
              {/* Branch line for children */}
              {!isParent && (
                <div
                  className="absolute h-[1.5px] rounded-full"
                  style={{
                    left: -14,
                    width: 16,
                    background: c.raw,
                    opacity: 0.4,
                    animation: `outline-wait-branch 0.4s ease-out ${0.8 + i * 0.15}s both`,
                  }}
                />
              )}
              {/* Node dot */}
              <div
                className="outline-wait-node-el rounded-full"
                style={{
                  width: size,
                  height: size,
                  background: c.raw,
                  "--node-color": c.raw,
                  animation: `outline-wait-node 0.5s cubic-bezier(0.22, 1, 0.36, 1) ${0.6 + i * 0.15}s both`,
                } as React.CSSProperties}
              />
              <div
                className="outline-wait-glow-el absolute rounded-full"
                style={{
                  width: size,
                  height: size,
                  "--node-color": c.raw,
                  animation: `outline-wait-glow 2.5s ease-in-out ${i * 0.3}s infinite`,
                } as React.CSSProperties}
              />
              {/* Label line */}
              <div
                className="ml-3 h-[4px] rounded-full"
                style={{
                  width: isParent ? 80 : 56,
                  background: c.raw,
                  opacity: 0.2,
                  animation: `brief-line 3.6s ease-in-out ${0.8 + i * 0.2}s infinite`,
                }}
              />
            </div>
          )
        })}
      </div>
      <p className="text-sm text-foreground-muted">Structuring the outline…</p>
    </div>
  )
}

/** Art Direction: orbiting color dots with glow trails and pointer interaction. */
export function ArtDirectionWaiting() {
  const containerRef = useRef<HTMLDivElement>(null)

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const el = containerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width - 0.5) * 12
    const y = ((e.clientY - rect.top) / rect.height - 0.5) * 12
    el.style.setProperty("--px", `${x}px`)
    el.style.setProperty("--py", `${y}px`)
  }, [])

  const handleMouseLeave = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    el.style.setProperty("--px", "0px")
    el.style.setProperty("--py", "0px")
  }, [])

  return (
    <div className="art-waiting flex flex-col items-center gap-6">
      <div
        ref={containerRef}
        className="relative w-24 h-24"
        style={{
          "--px": "0px",
          "--py": "0px",
          animation: "art-hue 8s linear infinite",
          transform: "translate(var(--px), var(--py))",
          transition: "transform 0.3s ease-out",
        } as React.CSSProperties}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {WAIT_COLORS.map((c, i) => (
          <div key={i} className="absolute inset-0 flex items-center justify-center" style={{
            animation: `art-orbit 3s ease-in-out ${i * 0.75}s infinite`,
          }}>
            <div className="art-dot w-4 h-4 rounded-full" style={{
              background: c.raw,
              boxShadow: `0 0 16px ${c.raw}, 0 0 32px ${c.raw}`,
              transition: "animation-duration 0.3s",
            }} />
          </div>
        ))}
        {/* Center pulse */}
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-3 h-3 rounded-full" style={{
            background: "oklch(1 0 0 / 25%)",
            boxShadow: `0 0 12px ${WAIT_COLORS[0].raw}`,
            animation: "art-center-pulse 2.5s ease-in-out infinite",
          }} />
        </div>
      </div>
      <p className="text-sm text-foreground-muted">Composing art direction…</p>
    </div>
  )
}
