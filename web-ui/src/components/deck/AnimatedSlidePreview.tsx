// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AnimatedSlidePreview — Builds SVG from compose JSON and animates
 * changed components with agent cursors, wireframes, and typewriter.
 *
 * Backend provides `changed: boolean` per component — no frontend diff needed.
 * First render = instant (page load). Subsequent composeUrl changes = animate changed.
 */

"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { acquire, registerTypewriter } from "./animationScheduler"
import { useSlideVisibility } from "./useSlideVisibility"
import { markUnsettled, settle, type MaterializeItem } from "./materialize"

// --- Constants ---
const COMPOSE_VERSION = 1
const STAGGER_MS = 260
const WIREFRAME_LEAD_MS = 400
const TYPE_DURATION_MS = 800
const MIN_CHAR_MS = 15
const MAX_CHAR_MS = 50

/**
 * Agent identities share five CSS tokens defined in globals.css.
 * color/glow/bg are derived from the same --agent-* variable for each persona.
 * At runtime, getComputedStyle reads the resolved token value (theme-aware).
 */
const AGENTS = [
  { name: "Layout", token: "--agent-layout" },
  { name: "Content", token: "--agent-content" },
  { name: "Visual", token: "--agent-visual" },
  { name: "Data", token: "--agent-data" },
  { name: "Decorator", token: "--agent-decorator" },
] as const

type ResolvedAgent = { name: string; color: string; glow: string; bg: string }

/** Resolve CSS variable tokens into usable color strings (theme-aware). */
function resolveAgents(): ResolvedAgent[] {
  const root = typeof document !== "undefined" ? document.documentElement : null
  return AGENTS.map((a) => {
    const raw = root ? getComputedStyle(root).getPropertyValue(a.token).trim() : ""
    // Fallback: use oklch representation directly if computation available, else neutral gray
    const base = raw || "oklch(0.6 0 0)"
    return {
      name: a.name,
      color: `color-mix(in oklch, ${base} 55%, transparent)`,
      glow: `color-mix(in oklch, ${base} 10%, transparent)`,
      bg: base,
    }
  })
}

interface ComposeComponent {
  class: string
  bbox: { x: number; y: number; w: number; h: number } | null
  text: string
  svg: string
  changed: boolean
}

interface ComposeRegion {
  name: string
  x: number
  y: number
  w: number
  h: number
}

interface ComposeData {
  version: number
  viewBox: string
  bgFill: string
  bgSvg: string | null
  components: ComposeComponent[]
  regions?: ComposeRegion[]
}

interface DefsData {
  version: number
  defs: string
}

interface AnimatedSlidePreviewProps {
  defsUrl: string
  composeUrl: string
  slug?: string
  skipAnimation?: boolean
  knownUrl?: string | null
  onAnimate?: () => void
  onComplete?: () => void
  onAspectRatio?: (ratio: number) => void
  fallback?: React.ReactNode
  defsMounted?: boolean
}

function assignAgent(comp: ComposeComponent, agents: ResolvedAgent[]) {
  const cls = comp.class || ""
  if (cls === "TitleText" || cls === "SubtitleText") return agents[0]
  if (comp.text.length > 20) return agents[1]
  if (cls === "Graphic" || cls.includes("image")) return agents[2]
  if (cls.includes("ConnectorShape") || cls.includes("line")) return agents[3]
  return agents[4]
}

function regionKey(region: ComposeRegion) {
  return `${region.name}|${region.x},${region.y},${region.w},${region.h}`
}

/**
 * A component counts as body content when it carries text or an image (or is a
 * table / graphic object). Bare shapes and connectors are decoration — an
 * accent bar or card background must not mark a region as filled.
 */
function isContentComponent(comp: ComposeComponent) {
  if (comp.text) return true
  if (/<image[\s>]/i.test(comp.svg)) return true
  return /Table|Graphic|OLE2|Media/i.test(comp.class)
}

/**
 * A component fills a region when it sits mostly inside it (>= 50% of its own
 * area) or covers most of it (>= 50% of the region's area). Any-overlap was
 * too eager: LibreOffice bounding boxes include text-frame padding, so a title
 * frame or a bar touching the region's edge used to hide it.
 */
function fillsRegion(
  bbox: ComposeComponent["bbox"],
  region: ComposeRegion,
  scale: number,
) {
  if (!bbox || bbox.w <= 0 || bbox.h <= 0) return false
  const rx = region.x * scale, ry = region.y * scale
  const rw = region.w * scale, rh = region.h * scale
  if (rw <= 0 || rh <= 0) return false
  const ix = Math.max(0, Math.min(bbox.x + bbox.w, rx + rw) - Math.max(bbox.x, rx))
  const iy = Math.max(0, Math.min(bbox.y + bbox.h, ry + rh) - Math.max(bbox.y, ry))
  const inter = ix * iy
  if (inter <= 0) return false
  return inter >= 0.5 * bbox.w * bbox.h || inter >= 0.5 * rw * rh
}

export function AnimatedSlidePreview({ defsUrl, composeUrl, slug, skipAnimation, knownUrl, onAnimate, onComplete, onAspectRatio, fallback, defsMounted }: AnimatedSlidePreviewProps) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const unsettledRef = useRef(new Set<number>())
  const latestComponentsRef = useRef<ComposeComponent[]>([])
  const hasBeenOffscreenRef = useRef(false)
  const settlePendingRef = useRef<() => void>(() => {})
  const visibleRef = useSlideVisibility(wrapperRef, 0.5, (visible) => {
    if (!visible) {
      hasBeenOffscreenRef.current = true
    } else if (hasBeenOffscreenRef.current) {
      settlePendingRef.current()
    }
  })
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([])
  const typewriterCancelsRef = useRef<(() => void)[]>([])
  const releaseRef = useRef<(() => void) | null>(null)
  const materializeCancelRef = useRef<(() => void) | null>(null)
  const lastComposeUrlRef = useRef("")
  const previousRegionsRef = useRef<ComposeRegion[]>([])
  const animatingRef = useRef(false)
  const [error, setError] = useState(false)
  const [retryTick, setRetryTick] = useState(0)
  const [aspectRatio, setAspectRatio] = useState("16/9")
  const reducedMotion = useRef(
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  )

  const cleanup = useCallback(() => {
    timersRef.current.forEach(clearTimeout)
    timersRef.current = []
    typewriterCancelsRef.current.forEach(cancel => cancel())
    typewriterCancelsRef.current = []
    releaseRef.current?.()
    releaseRef.current = null
    materializeCancelRef.current?.()
    materializeCancelRef.current = null
    const parent = containerRef.current?.parentElement
    parent?.querySelectorAll(".asp-overlay, .asp-region-overlay").forEach(el => el.remove())
  }, [])

  useEffect(() => () => cleanup(), [cleanup])

  settlePendingRef.current = () => {
    const container = containerRef.current
    const slide = wrapperRef.current
    if (!container || !slide || unsettledRef.current.size === 0) return
    const items: MaterializeItem[] = []
    for (const index of unsettledRef.current) {
      const element = container.querySelector<SVGGElement>(`g[data-index="${index}"]`)
      const component = latestComponentsRef.current[index]
      if (element && component) items.push({ component, element })
    }
    unsettledRef.current.clear()
    materializeCancelRef.current?.()
    materializeCancelRef.current = settle(slide, items, { reducedMotion: reducedMotion.current })
  }

  // Track latest props in refs so check() always reads current values
  const composeUrlRef = useRef(composeUrl)
  const defsUrlRef = useRef(defsUrl)
  const skipRef = useRef(skipAnimation)
  const knownUrlRef = useRef(knownUrl?.split("?")[0] || null)
  const defsMountedRef = useRef(defsMounted)
  composeUrlRef.current = composeUrl
  defsUrlRef.current = defsUrl
  skipRef.current = skipAnimation
  knownUrlRef.current = knownUrl?.split("?")[0] || null
  defsMountedRef.current = defsMounted

  // Expose check() via ref so the composeUrl-change effect can trigger it
  const checkRef = useRef<() => void>(() => {})

  useEffect(() => {
    let cancelled = false

    function check() {
      const compUrlBase = composeUrlRef.current?.split("?")[0] || ""
      if (!compUrlBase) return
      if (compUrlBase === lastComposeUrlRef.current) return
      if (animatingRef.current) return  // defer until animation completes
      const suppressThisUpdate = skipRef.current || compUrlBase === knownUrlRef.current
      lastComposeUrlRef.current = compUrlBase

      ;(async () => {
        try {
          // Wait for fonts to load — webkit computes textLength against
          // the wrong metrics if fonts aren't ready, causing compressed text.
          if (typeof document !== "undefined" && document.fonts?.ready) {
            try { await document.fonts.ready } catch { /* ignore */ }
          }
          const [defsResp, compResp] = await Promise.all([
            defsMountedRef.current ? Promise.resolve(null) : fetch(defsUrlRef.current),
            fetch(composeUrlRef.current),
          ])
          if (cancelled || !compResp.ok || (defsResp && !defsResp.ok)) {
            lastComposeUrlRef.current = ""
            setError(true); return
          }

          const defsData: DefsData | null = defsResp ? await defsResp.json() : null
          const data: ComposeData = await compResp.json()

          if ((defsData && defsData.version !== COMPOSE_VERSION) || data.version !== COMPOSE_VERSION) {
            setError(true); return
          }

          // Empty content = nothing to render → treat as failure (fallback to PNG)
          if (!data.bgSvg && data.components.length === 0) {
            lastComposeUrlRef.current = ""
            setError(true); return
          }

          const container = containerRef.current
          if (!container || cancelled) {
            // Container not mounted — reset so a later prop change can retry
            lastComposeUrlRef.current = ""
            return
          }

          cleanup()
          setError(false)
          // Immediately hide fallback (React re-render is async)
          const fb = container.parentElement?.querySelector("[data-fallback]") as HTMLElement | null
          if (fb) fb.style.display = "none"

          const visibleAtArrival = visibleRef.current
          const skipAgentAnimation = suppressThisUpdate || !visibleAtArrival
          const changedTargets = new Set<number>()
          if (!suppressThisUpdate) {
            data.components.forEach((comp, i) => {
              if (comp.changed) changedTargets.add(i)
            })
          }
          const animTargets = visibleAtArrival ? changedTargets : new Set<number>()
          if (!visibleAtArrival && !reducedMotion.current) {
            changedTargets.forEach((index) => unsettledRef.current.add(index))
          } else if (reducedMotion.current) {
            unsettledRef.current.clear()
          }
          latestComponentsRef.current = data.components

          const regions = data.regions ?? []
          const previousRegionKeys = new Set(previousRegionsRef.current.map(regionKey))
          const regionAnimTargets = new Set<number>()
          if (!skipAgentAnimation) {
            regions.forEach((region, i) => {
              if (!previousRegionKeys.has(regionKey(region))) regionAnimTargets.add(i)
            })
          }
          previousRegionsRef.current = regions.map(region => ({ ...region }))

          const hasAnimationTargets = animTargets.size > 0 || regionAnimTargets.size > 0
          const shouldAnimate = hasAnimationTargets && !reducedMotion.current
          if (shouldAnimate) {
            animatingRef.current = true
            const release = await acquire(slug || compUrlBase)
            if (cancelled) {
              release()
              animatingRef.current = false
              return
            }
            releaseRef.current = release
            onAnimate?.()
          }

          // Resolve agent tokens once per animation cycle (theme-aware)
          const resolvedAgents = resolveAgents()

          // --- Build SVG ---
          const vb = data.viewBox.split(" ").map(Number)
          if (vb[2] > 0 && vb[3] > 0) {
            setAspectRatio(`${vb[2]}/${vb[3]}`)
            onAspectRatio?.(vb[2] / vb[3])
          }
          const regionScale = vb[2] / 1920
          container.innerHTML = ""

          const svgEl = document.createElementNS("http://www.w3.org/2000/svg", "svg")
          svgEl.setAttribute("viewBox", data.viewBox)
          svgEl.setAttribute("preserveAspectRatio", "xMidYMid")
          svgEl.style.width = "100%"
          svgEl.style.height = "100%"

          // Background
          if (data.bgSvg) {
            const g = document.createElementNS("http://www.w3.org/2000/svg", "g")
            g.innerHTML = data.bgSvg
            svgEl.appendChild(g)
          } else {
            const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect")
            rect.setAttribute("width", String(vb[2]))
            rect.setAttribute("height", String(vb[3]))
            rect.setAttribute("fill", data.bgFill || "#000")
            svgEl.appendChild(rect)
          }

          // Defs are normally hoisted once by SlideCarousel. Keep the old path
          // for standalone consumers that do not mount DeckDefs.
          if (defsData) {
            const defsG = document.createElementNS("http://www.w3.org/2000/svg", "g")
            defsG.innerHTML = defsData.defs
            while (defsG.firstChild) svgEl.appendChild(defsG.firstChild)
          }

          // Components
          data.components.forEach((comp, i) => {
            const g = document.createElementNS("http://www.w3.org/2000/svg", "g")
            g.innerHTML = comp.svg
            g.dataset.index = String(i)
            g.style.opacity = (animTargets.has(i) && !reducedMotion.current) ? "0" : "1"
            svgEl.appendChild(g)
            if (unsettledRef.current.has(i) && !reducedMotion.current) markUnsettled(g, comp)
          })

          // Layout regions sit above slide components; labels stay HTML-sized.
          const regionOverlay = document.createElement("div")
          regionOverlay.className = "asp-region-overlay absolute inset-0 pointer-events-none"
          const regionEntries = regions.map((region, i) => {
            const g = document.createElementNS("http://www.w3.org/2000/svg", "g")
            g.setAttribute("class", "asp-region")
            g.dataset.regionName = region.name

            const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect")
            rect.setAttribute("class", "asp-region-rect")
            rect.setAttribute("x", String(region.x * regionScale))
            rect.setAttribute("y", String(region.y * regionScale))
            rect.setAttribute("width", String(region.w * regionScale))
            rect.setAttribute("height", String(region.h * regionScale))
            rect.setAttribute("rx", String(6 * regionScale))
            rect.setAttribute("vector-effect", "non-scaling-stroke")
            g.appendChild(rect)
            svgEl.appendChild(g)

            const label = document.createElement("div")
            label.className = "asp-region-label"
            label.dataset.regionName = region.name
            label.textContent = region.name
            label.style.left = `${(region.x * regionScale / vb[2]) * 100}%`
            label.style.top = `${(region.y * regionScale / vb[3]) * 100}%`
            // Clamp to the region so long names never spill into neighbours; skip the
            // label entirely when the region is too small to hold one line.
            label.style.maxWidth = `calc(${(region.w * regionScale / vb[2]) * 100}% - 12px)`
            if (region.w < 120 || region.h < 40) label.classList.add("asp-region-label-hidden")
            regionOverlay.appendChild(label)

            if (!regionAnimTargets.has(i) || reducedMotion.current) {
              g.classList.add("asp-region-on", "asp-region-drawn")
              label.classList.add("asp-region-on")
            }
            return { g, label, region }
          })

          container.appendChild(svgEl)
          if (regions.length > 0) container.parentElement?.appendChild(regionOverlay)

          const markFilledRegions = (comp: ComposeComponent) => {
            if (!isContentComponent(comp)) return
            regionEntries.forEach(({ g, label, region }) => {
              if (fillsRegion(comp.bbox, region, regionScale)) {
                g.classList.add("asp-region-filled")
                label.classList.add("asp-region-filled")
              }
            })
          }
          // Fill state derives from the whole component set: content that was
          // already there (unchanged) fills its region right away; changed
          // components fill theirs as they land below, and a final pass at the
          // end catches anything the timing missed.
          const markFilledByAll = () => data.components.forEach(markFilledRegions)
          data.components.forEach((comp, i) => {
            if (!animTargets.has(i)) markFilledRegions(comp)
          })

          if (reducedMotion.current || !hasAnimationTargets) {
            markFilledByAll()
            animatingRef.current = false
            onComplete?.()
            return
          }

          // --- Animate new regions, then changed components ---
          const overlayContainer = document.createElement("div")
          overlayContainer.className = "asp-overlay absolute inset-0 pointer-events-none"
          container.parentElement?.appendChild(overlayContainer)

          const createCursor = (agent: ResolvedAgent, left: number, top: number) => {
            const cursor = document.createElement("div")
            cursor.className = "absolute transition-all duration-300"
            cursor.style.cssText = `left:${left}%;top:${top}%;opacity:0;z-index:20;`
            cursor.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M5 3l14 8.5L12 14l-2.5 7L5 3z" fill="${agent.bg}" stroke="color-mix(in oklch, var(--background) 60%, transparent)" stroke-width="1.5"/></svg><span style="position:absolute;left:12px;top:12px;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600;white-space:nowrap;background:${agent.bg};color:var(--background);box-shadow:var(--shadow-card)">${agent.name}</span>`
            overlayContainer.appendChild(cursor)
            requestAnimationFrame(() => { cursor.style.opacity = "1" })
            return cursor
          }

          let regionStaggerIdx = 0
          regionEntries.forEach(({ g, label, region }, i) => {
            if (!regionAnimTargets.has(i)) return
            const si = regionStaggerIdx++
            const pctL = (region.x * regionScale / vb[2]) * 100
            const pctT = (region.y * regionScale / vb[3]) * 100
            const endL = ((region.x + region.w) * regionScale / vb[2]) * 100
            const endT = ((region.y + region.h) * regionScale / vb[3]) * 100
            const t1 = setTimeout(() => {
              if (cancelled) return
              const cursor = createCursor(resolvedAgents[0], pctL, pctT)
              const t2 = setTimeout(() => {
                if (cancelled) return
                g.classList.add("asp-region-on", "asp-region-drawn")
                label.classList.add("asp-region-on")
                cursor.style.left = `${endL}%`
                cursor.style.top = `${endT}%`
                const t3 = setTimeout(() => {
                  cursor.style.transition = "opacity 0.4s ease-out"
                  cursor.style.opacity = "0"
                }, 500)
                timersRef.current.push(t3)
              }, 250)
              timersRef.current.push(t2)
            }, si * STAGGER_MS)
            timersRef.current.push(t1)
          })

          const regionPhaseMs = regionStaggerIdx > 0
            ? regionStaggerIdx * STAGGER_MS + WIREFRAME_LEAD_MS
            : 0
          let componentStaggerIdx = 0
          data.components.forEach((comp, i) => {
            if (!animTargets.has(i) || !comp.bbox) return
            const si = componentStaggerIdx++
            const agent = assignAgent(comp, resolvedAgents)

            const pctL = (comp.bbox.x / vb[2]) * 100
            const pctT = (comp.bbox.y / vb[3]) * 100
            const pctW = (comp.bbox.w / vb[2]) * 100
            const pctH = (comp.bbox.h / vb[3]) * 100

            const t1 = setTimeout(() => {
              if (cancelled) return
              const cursor = createCursor(agent, pctL, Math.max(0, pctT - 5))
              requestAnimationFrame(() => {
                cursor.style.left = `${pctL}%`
                cursor.style.top = `${pctT}%`
              })

              const t2 = setTimeout(() => {
                if (cancelled) return
                const wf = document.createElement("div")
                wf.className = "absolute"
                wf.style.cssText = `left:${pctL}%;top:${pctT}%;width:${pctW}%;height:${pctH}%;border:1px solid ${agent.color};border-radius:2px;box-shadow:inset 0 0 16px ${agent.glow};opacity:1;clip-path:inset(0 100% 100% 0);animation:asp-wf-drag 0.35s cubic-bezier(0.16,1,0.3,1) forwards;`
                overlayContainer.appendChild(wf)

                const endL = ((comp.bbox!.x + comp.bbox!.w) / vb[2]) * 100
                const endT = ((comp.bbox!.y + comp.bbox!.h) / vb[3]) * 100
                cursor.style.left = `${endL}%`
                cursor.style.top = `${endT}%`

                const t3 = setTimeout(() => {
                  if (cancelled) return
                  const g = svgEl.querySelector(`g[data-index="${i}"]`) as SVGGElement | null
                  if (g) {
                    g.style.opacity = "1"
                    const flash = document.createElement("div")
                    flash.className = "asp-land absolute"
                    flash.style.cssText = `left:${pctL}%;top:${pctT}%;width:${pctW}%;height:${pctH}%;background:${agent.glow};`
                    overlayContainer.appendChild(flash)
                    flash.addEventListener("animationend", () => flash.remove(), { once: true })
                    typewriterCancelsRef.current.push(typewrite(g))
                  }
                  markFilledRegions(comp)
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
            }, regionPhaseMs + si * STAGGER_MS)
            timersRef.current.push(t1)
          })

          const totalTime = regionPhaseMs + componentStaggerIdx * STAGGER_MS + WIREFRAME_LEAD_MS + 1000
          const tDone = setTimeout(() => {
            markFilledByAll()
            animatingRef.current = false
            releaseRef.current?.()
            releaseRef.current = null
            overlayContainer.remove()
            onComplete?.()
            // Check if a new composeUrl arrived during animation
            check()
          }, totalTime)
          timersRef.current.push(tDone)
        } catch {
          animatingRef.current = false
          releaseRef.current?.()
          releaseRef.current = null
          lastComposeUrlRef.current = ""
          setError(true)
        }
      })()
    }

    check()
    checkRef.current = check
    return () => { cancelled = true; cleanup() }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  // React immediately to composeUrl prop changes.
  useEffect(() => {
    checkRef.current?.()
  }, [composeUrl])

  // Retry only while the current compose payload is in an error state.
  useEffect(() => {
    if (!error) return
    const retry = window.setTimeout(() => {
      checkRef.current?.()
      setRetryTick((tick) => tick + 1)
    }, 2000)
    return () => clearTimeout(retry)
  }, [error, composeUrl, retryTick])

  return (
    <div ref={wrapperRef} data-slide-id={slug} className="slide-cv slide-shadow relative overflow-hidden rounded-lg bg-black" style={{ aspectRatio }}>
      <div ref={containerRef} className="absolute inset-0" data-slide-id={slug} />
      {error && fallback && <div data-fallback className="absolute inset-0">{fallback}</div>}
    </div>
  )
}

function typewrite(compEl: SVGGElement) {
  const tspans = compEl.querySelectorAll("tspan")
  const leafSpans: { el: Element; fullText: string }[] = []
  let totalChars = 0
  tspans.forEach(ts => {
    if (ts.querySelectorAll("tspan").length === 0 && ts.textContent) {
      // Strip textLength / lengthAdjust permanently — restoring them after typewriter
      // completes causes webkit to horizontally compress glyphs.
      for (const attr of ["textLength", "lengthAdjust"]) ts.removeAttribute(attr)
      totalChars += ts.textContent.length
      leafSpans.push({ el: ts, fullText: ts.textContent })
      ts.textContent = ""
    }
  })
  if (!leafSpans.length) return () => {}
  const charMs = Math.max(MIN_CHAR_MS, Math.min(MAX_CHAR_MS, Math.floor(TYPE_DURATION_MS / totalChars)))
  return registerTypewriter(leafSpans, charMs)
}
