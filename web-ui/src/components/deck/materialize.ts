// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const SVG_NS = "http://www.w3.org/2000/svg"
const DURATION_MS = 700
const COMPONENT_STAGGER_MS = 90
const LINE_STAGGER_MS = 55
const CHILD_STAGGER_MS = 45
const SPRING_K = 300
const SPRING_C = 20
const FRAME_COUNT = 40

export interface MaterializeComponent {
  class: string
  bbox: { x: number; y: number; w: number; h: number } | null
}

export interface MaterializeItem {
  component: MaterializeComponent
  element: SVGGElement
}

function copyAttributes(from: Element, to: Element) {
  for (const attribute of Array.from(from.attributes)) {
    to.setAttributeNS(attribute.namespaceURI, attribute.name, attribute.value)
  }
}

/** Split LibreOffice absolute TextPosition lines into sibling text elements. */
export function splitTextLines(group: SVGGElement): SVGTextElement[] {
  const existing = Array.from(group.querySelectorAll<SVGTextElement>("text[data-materialize-line]"))
  if (existing.length > 0) return existing

  const byParent = new Map<SVGTextElement, SVGTSpanElement[]>()
  group.querySelectorAll<SVGTSpanElement>("tspan.TextPosition").forEach((position) => {
    const parent = position.closest("text") as SVGTextElement | null
    if (!parent) return
    const positions = byParent.get(parent) ?? []
    positions.push(position)
    byParent.set(parent, positions)
  })

  const lines: SVGTextElement[] = []
  for (const [parent, positions] of byParent) {
    for (const position of positions) {
      const line = document.createElementNS(SVG_NS, "text")
      copyAttributes(parent, line)
      line.dataset.materializeLine = "true"
      line.appendChild(position.cloneNode(true))
      parent.parentNode?.insertBefore(line, parent)
      lines.push(line)
    }
    parent.remove()
  }
  return lines
}

export function isHeavy(group: SVGGElement) {
  return group.querySelectorAll("path").length > 200
}

/** Return authored-order animation targets for each LibreOffice component class. */
export function settleTargets(component: MaterializeComponent, group: SVGGElement): SVGElement[] {
  const className = component.class || ""
  if (/Graphic/i.test(className)) return [group]

  const lines = splitTextLines(group)
  if (/TableShape/i.test(className)) return lines.length > 0 ? lines : [group]
  if (/CustomShape/i.test(className)) {
    const frames = Array.from(group.querySelectorAll<SVGPathElement>("path"))
    return [...frames, ...lines].length > 0 ? [...frames, ...lines] : [group]
  }
  if (/Text/i.test(className) || lines.length > 0) return lines.length > 0 ? lines : [group]
  return [group]
}

function markTarget(target: SVGElement, noBlur: boolean) {
  target.classList.add("asp-materialize-target")
  target.style.opacity = "0.45"
  target.style.transform = "scale(0.96)"
  if (!noBlur) target.style.filter = "blur(8px) saturate(0.7) brightness(1.12)"
}

export function markUnsettled(group: SVGGElement, component: MaterializeComponent) {
  const noBlur = /Graphic/i.test(component.class) && isHeavy(group)
  settleTargets(component, group).forEach((target) => markTarget(target, noBlur))
  group.dataset.unsettled = "true"
}

function springAt(seconds: number) {
  const w0 = Math.sqrt(SPRING_K)
  const zeta = SPRING_C / (2 * w0)
  if (zeta < 1) {
    const wd = w0 * Math.sqrt(1 - zeta * zeta)
    return 1 - Math.exp(-zeta * w0 * seconds)
      * (Math.cos(wd * seconds) + (zeta * w0 / wd) * Math.sin(wd * seconds))
  }
  const r = -w0
  return 1 - (1 - r * seconds) * Math.exp(r * seconds)
}

function easeOutExpo(value: number) {
  return value >= 1 ? 1 : 1 - 2 ** (-10 * value)
}

function lerp(from: number, to: number, progress: number) {
  return from + (to - from) * progress
}

function frames(noBlur: boolean): Keyframe[] {
  const result: Keyframe[] = []
  for (let index = 0; index <= FRAME_COUNT; index++) {
    const position = index / FRAME_COUNT
    const spring = springAt(position * DURATION_MS / 1000)
    const focus = easeOutExpo(Math.min(1, position / 0.6))
    const frame: Keyframe = {
      offset: position,
      transform: `scale(${lerp(0.96, 1, spring).toFixed(4)})`,
      opacity: lerp(0.45, 1, focus).toFixed(3),
    }
    if (!noBlur) {
      frame.filter = `blur(${lerp(8, 0, focus).toFixed(2)}px) saturate(${lerp(0.7, 1, focus).toFixed(3)}) brightness(${lerp(1.12, 1, easeOutExpo(position)).toFixed(3)})`
    }
    result.push(frame)
  }
  return result
}

function clearTarget(target: SVGElement) {
  for (const property of ["opacity", "transform", "filter", "transform-box", "transform-origin"]) {
    target.style.removeProperty(property)
  }
  target.classList.remove("asp-materialize-target")
}

/** Settle accumulated off-screen changes in reading order. */
export function settle(
  slide: HTMLElement,
  sourceItems: MaterializeItem[],
  { reducedMotion = false }: { reducedMotion?: boolean } = {},
) {
  const items = [...sourceItems].sort((left, right) => {
    const a = left.component.bbox
    const b = right.component.bbox
    return ((a?.y ?? 0) - (b?.y ?? 0)) || ((a?.x ?? 0) - (b?.x ?? 0))
  })
  const animations: Animation[] = []
  let latestDelay = 0

  items.forEach((item, itemIndex) => {
    const noBlur = /Graphic/i.test(item.component.class) && isHeavy(item.element)
    const targets = settleTargets(item.component, item.element)
    let targetOffset = 0
    targets.forEach((target) => {
      const delay = itemIndex * COMPONENT_STAGGER_MS + targetOffset
      targetOffset += target.tagName.toLowerCase() === "text" ? LINE_STAGGER_MS : CHILD_STAGGER_MS
      latestDelay = Math.max(latestDelay, delay)
      if (reducedMotion || typeof target.animate !== "function") {
        clearTarget(target)
        return
      }
      const animation = target.animate(frames(noBlur), {
        delay,
        duration: DURATION_MS,
        easing: "linear",
        fill: "forwards",
      })
      animations.push(animation)
      animation.onfinish = () => {
        clearTarget(target)
        animation.cancel()
      }
    })
    delete item.element.dataset.unsettled
  })

  if (!reducedMotion && items.length > 0 && typeof slide.animate === "function") {
    const breath = slide.animate([
      { transform: "scale(0.992)", boxShadow: "0 12px 40px oklch(0 0 0 / 45%)" },
      { transform: "scale(1)", boxShadow: "0 22px 60px oklch(0 0 0 / 55%)", offset: 0.5 },
      { transform: "scale(1)", boxShadow: "0 12px 40px oklch(0 0 0 / 45%)" },
    ], {
      duration: DURATION_MS + latestDelay,
      easing: "cubic-bezier(0.22, 1, 0.36, 1)",
    })
    animations.push(breath)
  }

  return () => {
    animations.forEach((animation) => animation.cancel())
    items.forEach((item) => settleTargets(item.component, item.element).forEach(clearTarget))
  }
}
