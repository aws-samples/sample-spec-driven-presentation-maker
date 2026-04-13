// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AnimatedSlidePreview — Builds SVG from compose JSON and animates
 * changed components with agent cursors, wireframes, and typewriter.
 *
 * Diff-based: only changed/new components animate; unchanged show instantly.
 * Key: class+bbox for stable identity across insertions/deletions.
 */

"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import DOMPurify from "dompurify"

// --- Constants ---
const COMPOSE_VERSION = 1
const STAGGER_MS = 420
const WIREFRAME_LEAD_MS = 280
const TYPE_DURATION_MS = 800
const MIN_CHAR_MS = 15
const MAX_CHAR_MS = 50

const AGENTS = [
  { name: "Layout", color: "rgba(100,150,255,0.55)", glow: "rgba(100,150,255,0.1)", bg: "#3b6cf0" },
  { name: "Content", color: "rgba(80,210,180,0.55)", glow: "rgba(80,210,180,0.1)", bg: "#2ba882" },
  { name: "Visual", color: "rgba(170,120,255,0.55)", glow: "rgba(170,120,255,0.1)", bg: "#8b5cf6" },
  { name: "Data", color: "rgba(245,180,70,0.55)", glow: "rgba(245,180,70,0.1)", bg: "#d97706" },
  { name: "Decorator", color: "rgba(240,100,130,0.55)", glow: "rgba(240,100,130,0.1)", bg: "#e04070" },
] as const

interface ComposeComponent {
  class: string
  bbox: { x: number; y: number; w: number; h: number } | null
  text: string
  svg: string
}

interface ComposeData {
  version: number
  viewBox: string
  bgFill: string
  bgSvg: string | null
  components: ComposeComponent[]
}

interface DefsData {
  version: number
  defs: string
}

interface AnimatedSlidePreviewProps {
  defsUrl: string
  composeUrl: string
  onComplete?: () => void
  /** Fallback to render when compose version mismatches or fetch fails. */
  fallback?: React.ReactNode
}

// --- Helpers ---

function makeKey(c: ComposeComponent): string {
  return c.bbox
    ? `${c.class}|${c.bbox.x},${c.bbox.y},${c.bbox.w},${c.bbox.h}`
    : `${c.class}|none`
}

function assignAgent(comp: ComposeComponent) {
  const cls = comp.class || ""
  if (cls === "TitleText" || cls === "SubtitleText") return AGENTS[0]
  if (comp.text.length > 20) return AGENTS[1]
  if (cls === "Graphic" || cls.includes("image")) return AGENTS[2]
  if (cls.includes("ConnectorShape") || cls.includes("line")) return AGENTS[3]
  return AGENTS[4] // Decorator — deterministic, no random
}

function sanitizeSvg(raw: string): string {
  return DOMPurify.sanitize(raw, {
    USE_PROFILES: { svg: true, svgFilters: true },
    ADD_TAGS: ["use", "clipPath", "mask", "filter", "feGaussianBlur", "feOffset",
      "feMerge", "feMergeNode", "feFlood", "feComposite", "feBlend",
      "font", "font-face", "glyph", "missing-glyph"],
    ADD_ATTR: ["xlink:href", "clip-path", "mask", "filter", "textLength",
      "lengthAdjust", "class", "viewBox", "preserveAspectRatio"],
  })
}

// --- Component ---

export function AnimatedSlidePreview({ defsUrl, composeUrl, onComplete, fallback }: AnimatedSlidePreviewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const prevCompRef = useRef<Map<string, string> | null>(null)
  const intervalsRef = useRef<number[]>([])
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([])
  const [error, setError] = useState(false)
  const reducedMotion = useRef(
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  )

  const cleanup = useCallback(() => {
    intervalsRef.current.forEach(clearInterval)
    intervalsRef.current = []
    timersRef.current.forEach(clearTimeout)
    timersRef.current = []
  }, [])

  useEffect(() => () => cleanup(), [cleanup])

  useEffect(() => {
    let cancelled = false

    async function run() {
      try {
        const [defsResp, compResp] = await Promise.all([fetch(defsUrl), fetch(composeUrl)])
        if (cancelled || !defsResp.ok || !compResp.ok) { setError(true); return }

        const defsData: DefsData = await defsResp.json()
        const data: ComposeData = await compResp.json()

        if (defsData.version !== COMPOSE_VERSION || data.version !== COMPOSE_VERSION) {
          setError(true); return
        }

        const container = containerRef.current
        if (!container || cancelled) return

        cleanup()

        // --- Diff detection ---
        const animTargets = new Set<number>()
        const prevMap = prevCompRef.current
        if (!prevMap) {
          data.components.forEach((_, i) => animTargets.add(i))
        } else {
          data.components.forEach((comp, i) => {
            const key = makeKey(comp)
            const prevSvg = prevMap.get(key)
            if (prevSvg === undefined || prevSvg !== comp.svg) {
              animTargets.add(i)
            }
          })
        }

        // Save for next diff
        const newMap = new Map<string, string>()
        data.components.forEach(c => newMap.set(makeKey(c), c.svg))
        prevCompRef.current = newMap

        // --- Build SVG ---
        const vb = data.viewBox.split(" ").map(Number)
        container.innerHTML = ""
        // Remove old overlays
        container.parentElement?.querySelectorAll(".asp-overlay").forEach(el => el.remove())

        const svgEl = document.createElementNS("http://www.w3.org/2000/svg", "svg")
        svgEl.setAttribute("viewBox", data.viewBox)
        svgEl.setAttribute("preserveAspectRatio", "xMidYMid")
        svgEl.style.width = "100%"
        svgEl.style.height = "100%"

        // Background
        if (data.bgSvg) {
          const g = document.createElementNS("http://www.w3.org/2000/svg", "g")
          g.innerHTML = sanitizeSvg(data.bgSvg)
          svgEl.appendChild(g)
        } else {
          const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect")
          rect.setAttribute("width", String(vb[2]))
          rect.setAttribute("height", String(vb[3]))
          rect.setAttribute("fill", data.bgFill || "#000")
          svgEl.appendChild(rect)
        }

        // Defs
        const defsG = document.createElementNS("http://www.w3.org/2000/svg", "g")
        defsG.innerHTML = sanitizeSvg(defsData.defs)
        while (defsG.firstChild) svgEl.appendChild(defsG.firstChild)

        // Components
        data.components.forEach((comp, i) => {
          const g = document.createElementNS("http://www.w3.org/2000/svg", "g")
          g.innerHTML = sanitizeSvg(comp.svg)
          g.dataset.index = String(i)
          if (!animTargets.has(i) || reducedMotion.current) {
            g.style.opacity = "1"
          } else {
            g.style.opacity = "0"
          }
          svgEl.appendChild(g)
        })

        container.appendChild(svgEl)

        // --- Reduced motion: done ---
        if (reducedMotion.current) {
          onComplete?.()
          return
        }

        // --- Animate changed components ---
        const overlayContainer = document.createElement("div")
        overlayContainer.className = "asp-overlay absolute inset-0 pointer-events-none"
        container.parentElement?.appendChild(overlayContainer)

        let staggerIdx = 0
        data.components.forEach((comp, i) => {
          if (!animTargets.has(i) || !comp.bbox) return
          const si = staggerIdx++
          const agent = assignAgent(comp)

          const pctL = (comp.bbox.x / vb[2]) * 100
          const pctT = (comp.bbox.y / vb[3]) * 100
          const pctW = (comp.bbox.w / vb[2]) * 100
          const pctH = (comp.bbox.h / vb[3]) * 100

          // Phase 1: cursor fly-in
          const t1 = setTimeout(() => {
            if (cancelled) return
            const cursor = document.createElement("div")
            cursor.className = "absolute transition-all duration-300"
            cursor.style.cssText = `left:${pctL}%;top:${Math.max(0, pctT - 5)}%;opacity:0;z-index:20;`
            cursor.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M5 3l14 8.5L12 14l-2.5 7L5 3z" fill="${agent.bg}" stroke="rgba(0,0,0,0.4)" stroke-width="1.5"/></svg><span style="position:absolute;left:12px;top:12px;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;white-space:nowrap;background:${agent.bg};color:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.3)">${agent.name}</span>`
            overlayContainer.appendChild(cursor)
            requestAnimationFrame(() => {
              cursor.style.opacity = "1"
              cursor.style.left = `${pctL}%`
              cursor.style.top = `${pctT}%`
            })

            // Phase 2: wireframe
            const t2 = setTimeout(() => {
              if (cancelled) return
              const wf = document.createElement("div")
              wf.className = "absolute"
              wf.style.cssText = `left:${pctL}%;top:${pctT}%;width:${pctW}%;height:${pctH}%;border:1px solid ${agent.color};border-radius:2px;box-shadow:inset 0 0 16px ${agent.glow};opacity:1;clip-path:inset(0 100% 100% 0);animation:asp-wf-drag 0.35s cubic-bezier(0.16,1,0.3,1) forwards;`
              overlayContainer.appendChild(wf)

              // Move cursor to bottom-right
              const endL = ((comp.bbox!.x + comp.bbox!.w) / vb[2]) * 100
              const endT = ((comp.bbox!.y + comp.bbox!.h) / vb[3]) * 100
              cursor.style.left = `${endL}%`
              cursor.style.top = `${endT}%`

              // Phase 3: materialize
              const t3 = setTimeout(() => {
                if (cancelled) return
                const g = svgEl.querySelector(`g[data-index="${i}"]`) as SVGGElement | null
                if (g) {
                  g.style.opacity = "1"
                  g.style.filter = "brightness(2) saturate(0.5)"
                  g.style.transition = "filter 0.5s cubic-bezier(0.16,1,0.3,1)"
                  requestAnimationFrame(() => { g.style.filter = "brightness(1) saturate(1)" })
                  typewrite(g)
                }
                // Fade out wireframe + cursor
                const t4 = setTimeout(() => {
                  wf.style.transition = "opacity 0.4s ease-out"
                  wf.style.opacity = "0"
                  cursor.style.transition = "opacity 0.4s ease-out"
                  cursor.style.opacity = "0"
                }, 500)
                timersRef.current.push(t4)
              }, WIREFRAME_LEAD_MS - 50)
              timersRef.current.push(t3)
            }, 250)
            timersRef.current.push(t2)
          }, si * STAGGER_MS)
          timersRef.current.push(t1)
        })

        // onComplete after all animations
        const totalTime = staggerIdx * STAGGER_MS + WIREFRAME_LEAD_MS + 1000
        const tDone = setTimeout(() => {
          if (!cancelled) {
            overlayContainer.remove()
            onComplete?.()
          }
        }, totalTime)
        timersRef.current.push(tDone)

      } catch {
        if (!cancelled) setError(true)
      }
    }

    run()
    return () => { cancelled = true }
  }, [defsUrl, composeUrl, cleanup, onComplete])

  if (error && fallback) return <>{fallback}</>

  return (
    <div className="aspect-[16/9] relative overflow-hidden rounded-lg bg-black">
      <div ref={containerRef} className="absolute inset-0" />
    </div>
  )
}

// --- Typewriter ---

function typewrite(compEl: SVGGElement) {
  const textEls = compEl.querySelectorAll(".SVGTextShape")
  textEls.forEach(textEl => {
    const tspans = textEl.querySelectorAll("tspan")
    const leafSpans: { el: Element; fullText: string; saved: Record<string, string> }[] = []
    let totalChars = 0
    tspans.forEach(ts => {
      if (ts.querySelectorAll("tspan").length === 0 && ts.textContent) {
        const saved: Record<string, string> = {}
        for (const attr of ["textLength", "lengthAdjust"]) {
          if (ts.hasAttribute(attr)) {
            saved[attr] = ts.getAttribute(attr)!
            ts.removeAttribute(attr)
          }
        }
        totalChars += ts.textContent.length
        leafSpans.push({ el: ts, fullText: ts.textContent, saved })
        ts.textContent = ""
      }
    })
    if (!leafSpans.length) return
    const charMs = Math.max(MIN_CHAR_MS, Math.min(MAX_CHAR_MS, Math.floor(TYPE_DURATION_MS / totalChars)))
    let spanIdx = 0, charIdx = 0
    const iv = window.setInterval(() => {
      if (spanIdx >= leafSpans.length) { clearInterval(iv); return }
      const span = leafSpans[spanIdx]
      charIdx++
      span.el.textContent = span.fullText.slice(0, charIdx)
      if (charIdx >= span.fullText.length) {
        for (const [a, v] of Object.entries(span.saved)) span.el.setAttribute(a, v)
        spanIdx++
        charIdx = 0
      }
    }, charMs)
  })
}
