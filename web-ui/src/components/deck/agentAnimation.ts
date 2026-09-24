// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { registerTypewriter } from "./animationScheduler"

const WIREFRAME_LEAD_MS = 400
const TYPE_DURATION_MS = 800
const MIN_CHAR_MS = 15
const MAX_CHAR_MS = 50

const AGENTS = [
  { name: "Layout", token: "--agent-layout" },
  { name: "Content", token: "--agent-content" },
  { name: "Visual", token: "--agent-visual" },
  { name: "Data", token: "--agent-data" },
  { name: "Decorator", token: "--agent-decorator" },
] as const

export interface AgentAnimationComponent {
  class: string
  bbox: { x: number; y: number; w: number; h: number } | null
  text: string
  svg: string
  changed: boolean
}

export interface AgentAnimationRegion {
  name: string
  x: number
  y: number
  w: number
  h: number
}

export interface AgentAnimationScene {
  container: HTMLDivElement
  svgEl: SVGSVGElement
  vb: number[]
  regionScale: number
  componentEntries: { component: AgentAnimationComponent; index: number; key: string }[]
  regionEntries: { g: SVGGElement; label: HTMLDivElement; region: AgentAnimationRegion }[]
  markFilledRegions: (component: AgentAnimationComponent) => void
  markFilledByAll: () => void
}

export interface AgentAnimationSession {
  cancel: () => void
}

type ResolvedAgent = { name: string; color: string; glow: string; bg: string }

function resolveAgents(): ResolvedAgent[] {
  const root = typeof document !== "undefined" ? document.documentElement : null
  return AGENTS.map((agent) => {
    const raw = root ? getComputedStyle(root).getPropertyValue(agent.token).trim() : ""
    const base = raw || "oklch(0.6 0 0)"
    return {
      name: agent.name,
      color: `color-mix(in oklch, ${base} 55%, transparent)`,
      glow: `color-mix(in oklch, ${base} 10%, transparent)`,
      bg: base,
    }
  })
}

function assignAgent(component: AgentAnimationComponent, agents: ResolvedAgent[]) {
  const cls = component.class || ""
  if (cls === "TitleText" || cls === "SubtitleText") return agents[0]
  if (component.text.length > 20) return agents[1]
  if (cls === "Graphic" || cls.includes("image")) return agents[2]
  if (cls.includes("ConnectorShape") || cls.includes("line")) return agents[3]
  return agents[4]
}

/**
 * Animate an already-built scene. The session owns every timer and typewriter
 * registration it creates; callers only coordinate visibility and scheduler slots.
 */
export function startAgentAnimation(
  scene: AgentAnimationScene,
  componentTargets: Set<string>,
  regionTargets: Set<number>,
  stagger: number,
  onComplete: () => void,
): AgentAnimationSession {
  const { container, svgEl, vb, regionScale, componentEntries, regionEntries, markFilledRegions, markFilledByAll } = scene
  const resolvedAgents = resolveAgents()
  const timers = new Set<ReturnType<typeof setTimeout>>()
  const typewriterCancels = new Set<() => void>()
  const overlayContainer = document.createElement("div")
  let cancelled = false

  overlayContainer.className = "asp-overlay absolute inset-0 pointer-events-none"
  container.parentElement?.appendChild(overlayContainer)

  const schedule = (callback: () => void, delay: number) => {
    const timer = setTimeout(() => {
      timers.delete(timer)
      if (!cancelled) callback()
    }, delay)
    timers.add(timer)
  }

  // Cursors move via transform (compositor thread), not left/top (layout).
  // A typewriter write relayouts the SVG every few frames; a left/top
  // transition would stutter with it, a transform transition does not.
  // Percent → px once per animation; the slide box does not change mid-run.
  const box = container.getBoundingClientRect()
  const moveCursor = (cursor: HTMLDivElement, leftPct: number, topPct: number) => {
    cursor.style.transform = `translate3d(${(leftPct / 100) * box.width}px, ${(topPct / 100) * box.height}px, 0)`
  }
  const createCursor = (agent: ResolvedAgent, left: number, top: number) => {
    const cursor = document.createElement("div")
    cursor.className = "absolute"
    cursor.style.cssText = "left:0;top:0;opacity:0;z-index:20;will-change:transform,opacity;transition:transform 0.3s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.3s ease-out;"
    moveCursor(cursor, left, top)
    cursor.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M5 3l14 8.5L12 14l-2.5 7L5 3z" fill="${agent.bg}" stroke="color-mix(in oklch, var(--background) 60%, transparent)" stroke-width="1.5"/></svg><span style="position:absolute;left:12px;top:12px;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600;white-space:nowrap;background:${agent.bg};color:var(--background);box-shadow:var(--shadow-card)">${agent.name}</span>`
    overlayContainer.appendChild(cursor)
    requestAnimationFrame(() => {
      if (!cancelled) cursor.style.opacity = "1"
    })
    return cursor
  }

  let regionStaggerIndex = 0
  regionEntries.forEach(({ g, label, region }, index) => {
    if (!regionTargets.has(index)) return
    const staggerIndex = regionStaggerIndex++
    const startLeft = (region.x * regionScale / vb[2]) * 100
    const startTop = (region.y * regionScale / vb[3]) * 100
    const endLeft = ((region.x + region.w) * regionScale / vb[2]) * 100
    const endTop = ((region.y + region.h) * regionScale / vb[3]) * 100
    schedule(() => {
      const cursor = createCursor(resolvedAgents[0], startLeft, startTop)
      schedule(() => {
        g.classList.add("asp-region-on", "asp-region-drawn")
        label.classList.add("asp-region-on")
        moveCursor(cursor, endLeft, endTop)
        schedule(() => {
          cursor.style.transition = "opacity 0.4s ease-out"
          cursor.style.opacity = "0"
        }, 500)
      }, 250)
    }, staggerIndex * stagger)
  })

  const regionPhaseMs = regionStaggerIndex > 0
    ? regionStaggerIndex * stagger + WIREFRAME_LEAD_MS
    : 0
  let componentStaggerIndex = 0
  componentEntries.forEach(({ component, index, key }) => {
    if (!componentTargets.has(key) || !component.bbox) return
    const staggerIndex = componentStaggerIndex++
    const agent = assignAgent(component, resolvedAgents)
    const { bbox } = component
    const left = (bbox.x / vb[2]) * 100
    const top = (bbox.y / vb[3]) * 100
    const width = (bbox.w / vb[2]) * 100
    const height = (bbox.h / vb[3]) * 100

    schedule(() => {
      const cursor = createCursor(agent, left, Math.max(0, top - 5))
      requestAnimationFrame(() => {
        if (!cancelled) moveCursor(cursor, left, top)
      })

      schedule(() => {
        const wireframe = document.createElement("div")
        wireframe.className = "absolute"
        wireframe.style.cssText = `left:${left}%;top:${top}%;width:${width}%;height:${height}%;border:1px solid ${agent.color};border-radius:2px;box-shadow:inset 0 0 16px ${agent.glow};opacity:1;clip-path:inset(0 100% 100% 0);animation:asp-wf-drag 0.35s cubic-bezier(0.16,1,0.3,1) forwards;`
        overlayContainer.appendChild(wireframe)

        const endLeft = ((bbox.x + bbox.w) / vb[2]) * 100
        const endTop = ((bbox.y + bbox.h) / vb[3]) * 100
        moveCursor(cursor, endLeft, endTop)

        schedule(() => {
          const group = svgEl.querySelector(`g[data-index="${index}"]`) as SVGGElement | null
          if (group) {
            group.style.opacity = "1"
            // Landing: the component lights up, then returns to normal brightness.
            // One component at a time on a visible slide keeps SVG filter cost bounded.
            group.style.filter = "brightness(2) saturate(0.5)"
            group.style.transition = "filter 0.5s cubic-bezier(0.16,1,0.3,1)"
            requestAnimationFrame(() => {
              if (!cancelled) group.style.filter = "brightness(1) saturate(1)"
            })
            typewriterCancels.add(typewrite(group))
          }
          markFilledRegions(component)
          schedule(() => {
            wireframe.style.transition = "opacity 0.4s ease-out"
            wireframe.style.opacity = "0"
            cursor.style.transition = "opacity 0.4s ease-out"
            cursor.style.opacity = "0"
          }, 500)
        }, WIREFRAME_LEAD_MS - 50)
      }, 250)
    }, regionPhaseMs + staggerIndex * stagger)
  })

  const totalTime = regionPhaseMs + componentStaggerIndex * stagger + WIREFRAME_LEAD_MS + 1000
  schedule(() => {
    markFilledByAll()
    overlayContainer.remove()
    onComplete()
  }, totalTime)

  return {
    cancel: () => {
      if (cancelled) return
      cancelled = true
      timers.forEach(clearTimeout)
      timers.clear()
      typewriterCancels.forEach((cancel) => cancel())
      typewriterCancels.clear()
      overlayContainer.remove()
    },
  }
}

function typewrite(component: SVGGElement) {
  const leafSpans: { el: Element; fullText: string }[] = []
  let totalChars = 0
  component.querySelectorAll("tspan").forEach((span) => {
    if (span.querySelectorAll("tspan").length === 0 && span.textContent) {
      // Strip textLength / lengthAdjust permanently — restoring them after typewriter
      // completes causes webkit to horizontally compress glyphs.
      for (const attribute of ["textLength", "lengthAdjust"]) span.removeAttribute(attribute)
      totalChars += span.textContent.length
      leafSpans.push({ el: span, fullText: span.textContent })
      span.textContent = ""
    }
  })
  if (!leafSpans.length) return () => {}
  const charMs = Math.max(MIN_CHAR_MS, Math.min(MAX_CHAR_MS, Math.floor(TYPE_DURATION_MS / totalChars)))
  return registerTypewriter(leafSpans, charMs)
}
