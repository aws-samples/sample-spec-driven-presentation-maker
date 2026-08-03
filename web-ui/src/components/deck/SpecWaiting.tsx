// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Spec waiting animations — shown while the agent is drafting each spec file.
 *
 * BriefWaiting: page being written with colorful lines and glowing cursor.
 * OutlineWaiting: tree growing with trunk, branches, and colorful nodes.
 * ArtDirectionWaiting: orbiting color dots with glow trails and pointer interaction.
 *
 * Colors use the five agent identity tokens (--agent-layout through --agent-decorator).
 * All animations respect prefers-reduced-motion.
 */

"use client"

import { useCallback, useRef } from "react"
import { useTranslations } from "next-intl"

/**
 * The five agent identity colors used for waiting animations.
 * Uses CSS custom properties for theme-awareness.
 */
export const AGENT_WAIT_COLORS = [
  { css: "var(--agent-layout)" },
  { css: "var(--agent-content)" },
  { css: "var(--agent-visual)" },
  { css: "var(--agent-data)" },
  { css: "var(--agent-decorator)" },
]

/** Brief: page being written with colorful lines and glowing cursor. */
export function BriefWaiting() {
  const t = useTranslations("specWaiting")
  const lines = [
    { w: 85, color: 0 }, { w: 65, color: 1 }, { w: 90, color: 2 },
    { w: 50, color: 3 }, { w: 75, color: 4 }, { w: 60, color: 0 },
  ]
  return (
    <div className="brief-waiting flex flex-col items-center gap-6">
      <div
        className="w-64 rounded-2xl p-6 flex flex-col gap-2.5"
        style={{
          background: "var(--background-raised)",
          border: "1px solid var(--border)",
          boxShadow: "var(--shadow-card)",
        }}
      >
        {lines.map((l, i) => (
          <div
            key={i}
            className="brief-line-el h-[5px] rounded-full"
            style={{
              width: `${l.w}%`,
              background: AGENT_WAIT_COLORS[l.color].css,
              opacity: 0.5,
              animation: `brief-line 3s ease-in-out ${i * 0.35}s infinite`,
            }}
          />
        ))}
        <div className="flex items-center mt-1">
          <div
            className="brief-cursor-glow w-[3px] h-5 rounded-full"
            style={{
              background: AGENT_WAIT_COLORS[0].css,
              boxShadow: `0 0 12px ${AGENT_WAIT_COLORS[0].css}`,
              animation: "brief-cursor 0.8s step-end infinite",
              transition: "box-shadow 0.3s ease",
            }}
          />
        </div>
      </div>
      <p className="text-sm text-foreground-muted">{t("draftingBrief")}</p>
    </div>
  )
}

/** Outline: tree growing with trunk, branches, and colorful nodes. */
export function OutlineWaiting() {
  const t = useTranslations("specWaiting")
  const nodes = [
    { level: 0, color: 0 }, { level: 1, color: 2 }, { level: 1, color: 3 },
    { level: 0, color: 1 }, { level: 1, color: 4 }, { level: 1, color: 2 },
    { level: 0, color: 3 },
  ]
  return (
    <div className="outline-waiting flex flex-col items-center gap-6">
      <div className="relative w-56" style={{ height: 220 }}>
        {/* Trunk line */}
        <div
          className="absolute left-[14px] top-0 w-[2px] rounded-full"
          style={{
            background: `linear-gradient(to bottom, ${AGENT_WAIT_COLORS[0].css}, ${AGENT_WAIT_COLORS[1].css})`,
            animation: "outline-trunk-grow 1.2s ease-out both",
            height: "100%",
          }}
        />
        {/* Nodes */}
        {nodes.map((n, i) => {
          const c = AGENT_WAIT_COLORS[n.color]
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
                    background: c.css,
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
                  background: c.css,
                  "--node-color": c.css,
                  animation: `outline-wait-node 0.5s cubic-bezier(0.22, 1, 0.36, 1) ${0.6 + i * 0.15}s both`,
                } as React.CSSProperties}
              />
              <div
                className="outline-wait-glow-el absolute rounded-full"
                style={{
                  width: size,
                  height: size,
                  "--node-color": c.css,
                  animation: `outline-wait-glow 2.5s ease-in-out ${i * 0.3}s infinite`,
                } as React.CSSProperties}
              />
              {/* Label line */}
              <div
                className="ml-3 h-[4px] rounded-full"
                style={{
                  width: isParent ? 80 : 56,
                  background: c.css,
                  opacity: 0.2,
                  animation: `brief-line 3.6s ease-in-out ${0.8 + i * 0.2}s infinite`,
                }}
              />
            </div>
          )
        })}
      </div>
      <p className="text-sm text-foreground-muted">{t("structuringOutline")}</p>
    </div>
  )
}

/** Art Direction: orbiting color dots with glow trails and pointer interaction. */
export function ArtDirectionWaiting() {
  const t = useTranslations("specWaiting")
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
        {AGENT_WAIT_COLORS.map((c, i) => (
          <div key={i} className="absolute inset-0 flex items-center justify-center" style={{
            animation: `art-orbit 3s ease-in-out ${i * 0.6}s infinite`,
          }}>
            <div className="art-dot w-4 h-4 rounded-full" style={{
              background: c.css,
              boxShadow: `0 0 16px ${c.css}, 0 0 32px ${c.css}`,
              transition: "animation-duration 0.3s",
            }} />
          </div>
        ))}
        {/* Center pulse */}
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-3 h-3 rounded-full" style={{
            background: "oklch(1 0 0 / 25%)",
            boxShadow: `0 0 12px ${AGENT_WAIT_COLORS[0].css}`,
            animation: "art-center-pulse 2.5s ease-in-out infinite",
          }} />
        </div>
      </div>
      <p className="text-sm text-foreground-muted">{t("composingArtDirection")}</p>
    </div>
  )
}
