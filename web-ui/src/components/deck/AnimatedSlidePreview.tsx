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
 * Share of a slide that must be in view before an unseen update replays.
 * Full-view slides are ~90% of the viewport tall, so 0.5 meant "half the
 * screen" before anything moved; 0.35 starts as the slide arrives.
 */
const REPLAY_VISIBLE_RATIO = 0.35
const STAGGER_MS = 260
/**
 * Catch-up replay: when a slide changed while off-screen and the user reaches
 * it within CATCHUP_MAX_AGE_MS, the agent-drawing animation replays for the
 * accumulated changes with a tighter stagger. The wireframe lead stays: without
 * it the frame, the element and the landing flash appear in the same frame and
 * the landing reads as a sudden flash. Older changes are simply shown.
 */
const CATCHUP_STAGGER_MS = 150
const CATCHUP_MAX_AGE_MS = 60_000
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
  /** Changed component keys that arrived while off-screen → arrival time (ms). */
  const pendingKeysRef = useRef(new Map<string, number>())
  /** Draws pending (arrived-while-away) changes on the built scene when the slide comes into view. */
  const replayPendingRef = useRef<() => void>(() => {})
  const sceneRef = useRef<{ url: string; scene: Scene } | null>(null)
  const pendingRef = useRef<{ url: string; apply: (animateNow: boolean) => void } | null>(null)
  const applyPendingRef = useRef<(animateNow: boolean) => void>(() => {})
  const visibilityWaitersRef = useRef(new Set<(visibility: "visible" | "hidden") => void>())
  const checkRef = useRef<() => void>(() => {})
  const visibleRef = useSlideVisibility(wrapperRef, REPLAY_VISIBLE_RATIO, (visibility) => {
    visibilityWaitersRef.current.forEach((resolve) => resolve(visibility))
    visibilityWaitersRef.current.clear()
    if (visibility === "visible") {
      if (pendingRef.current) applyPendingRef.current(true)
      else if (pendingKeysRef.current.size > 0) replayPendingRef.current()
    }
  })
  const nearRef = useSlideVisibility(wrapperRef, 0, (visibility) => {
    if (visibility === "visible" && pendingRef.current) {
      applyPendingRef.current(visibleRef.current === "visible")
    }
  }, "100% 0px")
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

  applyPendingRef.current = (animateNow) => {
    const pending = pendingRef.current
    if (!pending) return
    pendingRef.current = null
    if (pending.url !== composeUrlRef.current) {
      checkRef.current()
      return
    }
    pending.apply(animateNow)
  }

  useEffect(() => () => {
    pendingRef.current = null
    cleanup()
  }, [cleanup])

  const addPendingKeys = (keys: Iterable<string>) => {
    const now = performance.now()
    for (const key of keys) if (!pendingKeysRef.current.has(key)) pendingKeysRef.current.set(key, now)
  }
  const mergeSupersededHiddenChanges = (data: ComposeData) => {
    if (nearRef.current === "visible" || reducedMotion.current) return
    addPendingKeys(data.components.filter((c) => c.changed).map(composeComponentKey))
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
     * Run the agent-drawing animation on an already-built scene. Used by live
     * updates right after the build and by catch-up replays when a slide that
     * changed while away comes into view (no rebuild — the SVG is already there).
     */
    const animateScene = (
      scene: Scene,
      componentTargets: Set<string>,
      regionTargets: Set<number>,
      stagger: number,
    ) => {
      let session: AgentAnimationSession | null = null
      session = startAgentAnimation(scene, componentTargets, regionTargets, stagger, () => {
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

    /** Catch-up: the slide changed while away and is now in view — draw the pending changes on the existing scene. */
    const replayPending = async () => {
      const current = sceneRef.current
      if (!current || cancelled) return
      if (current.url !== composeUrlRef.current) { check(); return }
      if (animatingRef.current) return
      const { scene } = current
      const now = performance.now()
      const targets = new Set<string>()
      const showNow = (key: string) => {
        const g = scene.svgEl.querySelector(`g[data-component-key="${key}"]`) as SVGGElement | null
        if (g) { g.style.opacity = "1"; delete g.dataset.pending }
        const entry = scene.componentEntries.find((e) => e.key === key)
        if (entry) scene.markFilledRegions(entry.component)
      }
      for (const [key, arrivedAt] of pendingKeysRef.current) {
        if (now - arrivedAt > CATCHUP_MAX_AGE_MS || reducedMotion.current) showNow(key)
        else targets.add(key)
      }
      pendingKeysRef.current.clear()
      if (targets.size === 0) return
      animatingRef.current = true
      const release = await acquire(lifecycleController.signal)
      if (!release || cancelled) { release?.(); animatingRef.current = false; return }
      if (current !== sceneRef.current || current.url !== composeUrlRef.current) {
        release(); animatingRef.current = false; addPendingKeys(targets); check(); return
      }
      if (visibleRef.current !== "visible") {
        release(); animatingRef.current = false; addPendingKeys(targets); return
      }
      targets.forEach((key) => {
        const g = scene.svgEl.querySelector(`g[data-component-key="${key}"]`) as SVGGElement | null
        if (g) delete g.dataset.pending
      })
      releaseRef.current = release
      onAnimate?.()
      animateScene(scene, targets, new Set(), CATCHUP_STAGGER_MS)
    }
    replayPendingRef.current = () => { void replayPending() }

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
          if (superseded || requestedUrl !== composeUrlRef.current) {
            if (isComposeData(parsedData) && parsedData.version === COMPOSE_VERSION) {
              mergeSupersededHiddenChanges(parsedData)
            }
            return
          }
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

          const applyPayload = async (animateNow = visibleAtArrival === "visible") => {
            const container = containerRef.current
            if (!container || cancelled) {
              // Container not mounted — reset so a later prop change can retry
              lastComposeUrlRef.current = ""
              return
            }
            pendingRef.current = null

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
          const currentKeys = new Set(componentEntries.map((entry) => entry.key))
          const now = performance.now()
          for (const [key, arrivedAt] of pendingKeysRef.current) {
            // Gone from the payload, or too old to be worth replaying → just show it.
            if (!currentKeys.has(key) || now - arrivedAt > CATCHUP_MAX_AGE_MS) pendingKeysRef.current.delete(key)
          }
          const changedTargets = new Set<string>()
          if (!suppressThisUpdate) {
            componentEntries.forEach(({ component, key }) => {
              if (component.changed) changedTargets.add(key)
            })
          }
          if (reducedMotion.current) pendingKeysRef.current.clear()
          // Live update on a visible slide: animate this payload's changes plus any
          // changes that piled up while the slide was away. Arrival on a slide that
          // changed while away: replay those changes in catch-up form.
          const catchUp = animateNow && visibleAtArrival !== "visible"
          const animTargets = new Set<string>()
          if (animateNow && !reducedMotion.current) {
            if (visibleAtArrival === "visible") changedTargets.forEach((key) => animTargets.add(key))
            pendingKeysRef.current.forEach((_, key) => animTargets.add(key))
            pendingKeysRef.current.clear()
          } else if (!reducedMotion.current) {
            addPendingKeys(changedTargets)
          }
          const skipAgentAnimation = suppressThisUpdate || !animateNow
          const stagger = catchUp ? CATCHUP_STAGGER_MS : STAGGER_MS

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
          if (hasAnimationTargets && !reducedMotion.current) {
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
            // A queued slide may have become hidden while waiting for its slot.
            if (visibleRef.current !== "visible") {
              release()
              animatingRef.current = false
              // Defer what would have been drawn; it replays when the slide comes back.
              if (visibleRef.current === "hidden") addPendingKeys(animTargets)
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
            const hidden = !reducedMotion.current && (animTargets.has(key) || pendingKeysRef.current.has(key))
            g.style.opacity = hidden ? "0" : "1"
            if (pendingKeysRef.current.has(key)) g.dataset.pending = "1"
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
          componentEntries.forEach(({ component, key }) => {
            if (!animTargets.has(key)) markFilledRegions(component)
          })
          const scene: Scene = { container, svgEl, vb, regionScale, componentEntries, regionEntries, markFilledRegions, markFilledByAll }
          sceneRef.current = { url: requestedUrl, scene }

          if (reducedMotion.current || !hasAnimationTargets) {
            markFilledByAll()
            animatingRef.current = false
            onComplete?.()
            return
          }

          animateScene(scene, animTargets, regionAnimTargets, stagger)
          }

          const hasRenderedSvg = Boolean(containerRef.current?.querySelector("svg"))
          if (visibleAtArrival !== "visible" && nearRef.current !== "visible" && hasRenderedSvg && !reducedMotion.current) {
            mergeSupersededHiddenChanges(data)
            pendingRef.current = {
              url: requestedUrl,
              apply: (animateNow) => {
                void applyPayload(animateNow).catch(() => {
                  animatingRef.current = false
                  releaseRef.current?.()
                  releaseRef.current = null
                  markRetryableError(requestedUrl, false)
                })
              },
            }
            onComplete?.()
            return
          }

          await applyPayload()
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
  const propsTriggeredRef = useRef(false)
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
      pendingRef.current = null
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
