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
import { acquire } from "./animationScheduler"
import {
  startAgentAnimation,
  type AgentAnimationComponent as ComposeComponent,
  type AgentAnimationRegion as ComposeRegion,
  type AgentAnimationScene as Scene,
  type AgentAnimationSession,
} from "./agentAnimation"
import { useSlideVisibility } from "./useSlideVisibility"

// --- Constants ---
const COMPOSE_VERSION = 1
/**
 * Share of a slide that must be in view for a live update to animate.
 * Full-view slides are ~90% of the viewport tall, so 0.5 meant "half the
 * screen" before anything moved; 0.35 starts as the slide arrives.
 *
 * Updates that land on a slide below this ratio are drawn in their final
 * state immediately — no deferral and no replay when the slide comes into
 * view. The agent-drawing animation is for watching work happen live; a
 * reviewer scrolling through a finished deck should never wait for it.
 */
const ANIMATE_VISIBLE_RATIO = 0.35
const STAGGER_MS = 260
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

function isComposeData(value: unknown): value is ComposeData {
  if (!value || typeof value !== "object") return false
  const data = value as Partial<ComposeData>
  return typeof data.version === "number"
    && typeof data.viewBox === "string"
    && typeof data.bgFill === "string"
    && (data.bgSvg === null || typeof data.bgSvg === "string")
    && Array.isArray(data.components)
    && data.components.every((component) => Boolean(component)
      && typeof component.class === "string"
      && typeof component.text === "string"
      && typeof component.svg === "string"
      && typeof component.changed === "boolean")
}

function isDefsData(value: unknown): value is DefsData {
  if (!value || typeof value !== "object") return false
  const data = value as Partial<DefsData>
  return typeof data.version === "number" && typeof data.defs === "string"
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

function regionKey(region: ComposeRegion) {
  return `${region.name}|${region.x},${region.y},${region.w},${region.h}`
}

function hashIdentity(value: string) {
  let hash = 0x811c9dc5
  for (let index = 0; index < value.length; index++) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0).toString(36)
}

/** Stable across payload reordering; SVG IDs are preferred when LibreOffice supplied one. */
function composeComponentKey(component: ComposeComponent) {
  const id = component.svg.match(/\bid\s*=\s*["']([^"']+)["']/)?.[1]
  if (id) return `id:${id}`
  const bbox = component.bbox
    ? `${component.bbox.x},${component.bbox.y},${component.bbox.w},${component.bbox.h}`
    : "none"
  return `hash:${hashIdentity(`${component.class}|${bbox}|${component.text}`)}`
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
  const sceneRef = useRef<{ url: string; scene: Scene } | null>(null)
  const visibilityWaitersRef = useRef(new Set<(visibility: "visible" | "hidden") => void>())
  const checkRef = useRef<() => void>(() => {})
  const visibleRef = useSlideVisibility(wrapperRef, ANIMATE_VISIBLE_RATIO, (visibility) => {
    visibilityWaitersRef.current.forEach((resolve) => resolve(visibility))
    visibilityWaitersRef.current.clear()
  })
  const animationSessionRef = useRef<AgentAnimationSession | null>(null)
  const releaseRef = useRef<(() => void) | null>(null)
  const lastComposeUrlRef = useRef("")
  const previousRegionsRef = useRef<ComposeRegion[]>([])
  const animatingRef = useRef(false)
  const [errorKind, setErrorKind] = useState<"retryable" | "permanent" | null>(null)
  const [showError, setShowError] = useState(false)
  const retryFailureRef = useRef<{ url: string; startedAt: number } | null>(null)
  const [aspectRatio, setAspectRatio] = useState("16/9")
  const reducedMotion = useRef(
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  )

  const cleanup = useCallback(() => {
    animationSessionRef.current?.cancel()
    animationSessionRef.current = null
    releaseRef.current?.()
    releaseRef.current = null
    const parent = containerRef.current?.parentElement
    parent?.querySelectorAll(".asp-overlay, .asp-region-overlay").forEach(el => el.remove())
  }, [])

  useEffect(() => () => cleanup(), [cleanup])

  // Track latest props in refs so check() always reads current values
  const composeUrlRef = useRef(composeUrl)
  const defsUrlRef = useRef(defsUrl)
  const skipRef = useRef(skipAnimation)
  const knownUrlRef = useRef(knownUrl?.split("?")[0] || null)
  const defsMountedRef = useRef(defsMounted)
  const propsTriggeredRef = useRef(false)
  composeUrlRef.current = composeUrl
  defsUrlRef.current = defsUrl
  skipRef.current = skipAnimation
  knownUrlRef.current = knownUrl?.split("?")[0] || null
  defsMountedRef.current = defsMounted

  useEffect(() => {
    let cancelled = false
    const lifecycleController = new AbortController()

    const waitForFirstVisibility = () => {
      if (visibleRef.current !== "unknown") return Promise.resolve(visibleRef.current)
      return new Promise<"visible" | "hidden">((resolve) => {
        visibilityWaitersRef.current.add(resolve)
      })
    }
    const markPermanentError = () => {
      if (cancelled) return
      setErrorKind("permanent")
      setShowError(true)
    }
    const markRetryableError = (requestedUrl: string, hideTransient404: boolean) => {
      if (cancelled || requestedUrl !== composeUrlRef.current) return
      lastComposeUrlRef.current = ""
      setErrorKind("retryable")
      if (!hideTransient404) {
        retryFailureRef.current = null
        setShowError(true)
        return
      }
      const now = Date.now()
      if (retryFailureRef.current?.url !== requestedUrl) {
        retryFailureRef.current = { url: requestedUrl, startedAt: now }
      }
      setShowError(now - retryFailureRef.current.startedAt >= 3000)
    }

    /**
     * Run the agent-drawing animation on an already-built scene, right after a
     * live update lands on a visible slide.
     */
    const animateScene = (
      scene: Scene,
      componentTargets: Set<string>,
      regionTargets: Set<number>,
    ) => {
      let session: AgentAnimationSession | null = null
      session = startAgentAnimation(scene, componentTargets, regionTargets, STAGGER_MS, () => {
        if (animationSessionRef.current !== session) return
        animationSessionRef.current = null
        animatingRef.current = false
        releaseRef.current?.()
        releaseRef.current = null
        onComplete?.()
        check()
      })
      animationSessionRef.current = session
    }

    function check() {
      const requestedUrl = composeUrlRef.current
      const compUrlBase = requestedUrl?.split("?")[0] || ""
      if (!requestedUrl || !compUrlBase) return
      if (requestedUrl === lastComposeUrlRef.current) return
      if (animatingRef.current) return  // defer until animation completes
      const suppressThisUpdate = skipRef.current || compUrlBase === knownUrlRef.current
      lastComposeUrlRef.current = requestedUrl

      ;(async () => {
        try {
          // Wait for fonts to load — webkit computes textLength against
          // the wrong metrics if fonts aren't ready, causing compressed text.
          if (typeof document !== "undefined" && document.fonts?.ready) {
            try { await document.fonts.ready } catch { /* ignore */ }
          }
          const [defsResp, compResp] = await Promise.all([
            defsMountedRef.current
              ? Promise.resolve(null)
              : fetch(defsUrlRef.current, { signal: lifecycleController.signal }),
            fetch(requestedUrl, { signal: lifecycleController.signal }),
          ])
          if (cancelled) return
          const superseded = requestedUrl !== composeUrlRef.current
          if (!compResp.ok) {
            if (!superseded) {
              const hasPreviousSvg = Boolean(containerRef.current?.querySelector("svg"))
              markRetryableError(requestedUrl, compResp.status === 404 && hasPreviousSvg)
            }
            return
          }
          let parsedData: unknown
          try {
            parsedData = await compResp.json()
          } catch {
            if (!superseded) markPermanentError()
            return
          }
          if (cancelled) return
          // Superseded by a newer composeUrl: the newer request renders its own
          // final state, so this response contributes nothing.
          if (superseded || requestedUrl !== composeUrlRef.current) return
          if (defsResp && !defsResp.ok) {
            markRetryableError(requestedUrl, false)
            return
          }

          let parsedDefs: unknown = null
          try {
            parsedDefs = defsResp ? await defsResp.json() : null
          } catch {
            markPermanentError()
            return
          }
          if (cancelled || requestedUrl !== composeUrlRef.current) return

          if (
            (parsedDefs !== null && (!isDefsData(parsedDefs) || parsedDefs.version !== COMPOSE_VERSION))
            || !isComposeData(parsedData)
            || parsedData.version !== COMPOSE_VERSION
          ) {
            markPermanentError()
            return
          }
          const defsData = parsedDefs
          const data = parsedData

          // Empty content is a permanent payload error; retry only after composeUrl changes.
          if (!data.bgSvg && data.components.length === 0) {
            markPermanentError()
            return
          }

          // Compose can resolve before IntersectionObserver's first callback. Do not
          // classify that initial unknown state as off-screen.
          const visibleAtArrival = await waitForFirstVisibility()
          if (cancelled || requestedUrl !== composeUrlRef.current) return

          const container = containerRef.current
          if (!container || cancelled) {
            // Container not mounted — reset so a later prop change can retry
            lastComposeUrlRef.current = ""
            return
          }

          cleanup()
          retryFailureRef.current = null
          setErrorKind(null)
          setShowError(false)
          // Immediately hide fallback (React re-render is async)
          const fb = container.parentElement?.querySelector("[data-fallback]") as HTMLElement | null
          if (fb) fb.style.display = "none"

          const componentEntries = data.components.map((component, index) => ({
            component,
            index,
            key: composeComponentKey(component),
          }))
          // Only a live update on a slide the user is looking at animates. An
          // update that lands off-screen is drawn in its final state right away,
          // so the slide is already settled when the user scrolls to it.
          const animateNow = visibleAtArrival === "visible"
          const skipAgentAnimation = suppressThisUpdate || !animateNow || reducedMotion.current
          const animTargets = new Set<string>()
          if (!skipAgentAnimation) {
            componentEntries.forEach(({ component, key }) => {
              if (component.changed) animTargets.add(key)
            })
          }

          const regions = data.regions ?? []
          const previousRegionKeys = new Set(previousRegionsRef.current.map(regionKey))
          const regionAnimTargets = new Set<number>()
          if (!skipAgentAnimation) {
            regions.forEach((region, i) => {
              if (!previousRegionKeys.has(regionKey(region))) regionAnimTargets.add(i)
            })
          }
          previousRegionsRef.current = regions.map(region => ({ ...region }))

          let hasAnimationTargets = animTargets.size > 0 || regionAnimTargets.size > 0
          if (hasAnimationTargets) {
            animatingRef.current = true
            const release = await acquire(lifecycleController.signal)
            if (!release || cancelled) {
              release?.()
              animatingRef.current = false
              return
            }
            if (requestedUrl !== composeUrlRef.current) {
              release()
              animatingRef.current = false
              check()
              return
            }
            // A queued slide may have become hidden while waiting for its slot:
            // drop the animation and draw the final state instead.
            if (visibleRef.current !== "visible") {
              release()
              animatingRef.current = false
              animTargets.clear()
              regionAnimTargets.clear()
              hasAnimationTargets = false
            } else {
              releaseRef.current = release
              onAnimate?.()
            }
          }

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
          componentEntries.forEach(({ component, index, key }) => {
            const g = document.createElementNS("http://www.w3.org/2000/svg", "g")
            g.innerHTML = component.svg
            g.dataset.index = String(index)
            g.dataset.componentKey = key
            g.style.opacity = animTargets.has(key) ? "0" : "1"
            svgEl.appendChild(g)
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

            if (!regionAnimTargets.has(i)) {
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
          componentEntries.forEach(({ component, key }) => {
            if (!animTargets.has(key)) markFilledRegions(component)
          })
          const scene: Scene = { container, svgEl, vb, regionScale, componentEntries, regionEntries, markFilledRegions, markFilledByAll }
          sceneRef.current = { url: requestedUrl, scene }

          if (!hasAnimationTargets) {
            markFilledByAll()
            animatingRef.current = false
            onComplete?.()
            return
          }

          animateScene(scene, animTargets, regionAnimTargets)
        } catch {
          animatingRef.current = false
          releaseRef.current?.()
          releaseRef.current = null
          markRetryableError(requestedUrl, false)
        }
      })()
    }

    checkRef.current = check
    return () => {
      cancelled = true
      lifecycleController.abort()
      // In-flight work for the current URL is discarded with the abort, so a
      // remount (React Strict Mode in dev, or a key change) must fetch again.
      lastComposeUrlRef.current = ""
      propsTriggeredRef.current = false
      visibilityWaitersRef.current.forEach((resolve) => resolve("hidden"))
      visibilityWaitersRef.current.clear()
      sceneRef.current = null
      cleanup()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  const previousComposePropRef = useRef(composeUrl)
  const previousDefsUrlPropRef = useRef(defsUrl)
  const previousDefsMountedPropRef = useRef(defsMounted)
  // React to a new payload or lost/changed defs. Loading → ready needs no rebuild:
  // the in-flight slide already fetched its own fallback defs.
  useEffect(() => {
    const firstTrigger = !propsTriggeredRef.current
    const composeChanged = previousComposePropRef.current !== composeUrl
    const defsUrlChanged = previousDefsUrlPropRef.current !== defsUrl
    const lostDeckDefs = previousDefsMountedPropRef.current === true && defsMounted !== true
    propsTriggeredRef.current = true
    previousComposePropRef.current = composeUrl
    previousDefsUrlPropRef.current = defsUrl
    previousDefsMountedPropRef.current = defsMounted
    if (!firstTrigger && !composeChanged && !defsUrlChanged && !lostDeckDefs) return
    if (composeChanged) {
      retryFailureRef.current = null
      setErrorKind(null)
      setShowError(false)
    } else if (errorKind === "permanent") {
      return
    }
    lastComposeUrlRef.current = ""
    checkRef.current?.()
  }, [composeUrl, defsMounted, defsUrl, errorKind])

  // Retry network/HTTP failures only. Schema/version/empty failures wait for a new URL.
  useEffect(() => {
    if (errorKind !== "retryable") return
    let retry = 0
    const scheduleRetry = () => {
      retry = window.setTimeout(() => {
        checkRef.current?.()
        scheduleRetry()
      }, 2000)
    }
    scheduleRetry()
    return () => window.clearTimeout(retry)
  }, [errorKind, composeUrl])

  return (
    <div ref={wrapperRef} data-slide-id={slug} className="slide-cv slide-shadow relative rounded-lg bg-black" style={{ aspectRatio }}>
      <div ref={containerRef} className="absolute inset-0 overflow-hidden rounded-lg" data-slide-id={slug} />
      {showError && fallback && <div data-fallback className="absolute inset-0 overflow-hidden rounded-lg">{fallback}</div>}
    </div>
  )
}
