// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, expect, it, vi } from "vitest"
import chartFixtureJson from "../../test/fixtures/compose/chart.json"
import tableFixtureJson from "../../test/fixtures/compose/table.json"
import textFixtureJson from "../../test/fixtures/compose/text.json"
import {
  isHeavy,
  markUnsettled,
  settle,
  settleTargets,
  splitTextLines,
  type MaterializeComponent,
} from "./materialize"

const SVG_NS = "http://www.w3.org/2000/svg"

interface FixtureComponent extends MaterializeComponent {
  svg: string
}

interface ComposeFixture {
  components: FixtureComponent[]
}

const textFixture = textFixtureJson as ComposeFixture
const tableFixture = tableFixtureJson as ComposeFixture
const chartFixture = chartFixtureJson as ComposeFixture

function group(svg: string) {
  const element = document.createElementNS(SVG_NS, "g")
  element.innerHTML = svg
  return element
}

function component(className: string): MaterializeComponent {
  return { class: className, bbox: { x: 0, y: 0, w: 100, h: 100 } }
}

function fakeAnimation(): Animation {
  return { cancel: vi.fn(), onfinish: null } as unknown as Animation
}

describe("materialize targets", () => {
  it("selects text lines, CustomShape frame then lines, TableShape lines, and whole Graphics", () => {
    const text = group('<text><tspan class="TextPosition" x="1" y="2"><tspan>A</tspan></tspan><tspan class="TextPosition" x="1" y="4"><tspan>B</tspan></tspan></text>')
    expect(settleTargets(component("TitleText"), text).map((node) => node.tagName)).toEqual(["text", "text"])

    const shape = group('<path id="frame"/><text><tspan class="TextPosition" x="1" y="2"><tspan>A</tspan></tspan></text>')
    expect(settleTargets(component("com.sun.star.drawing.CustomShape"), shape).map((node) => node.tagName)).toEqual(["path", "text"])

    const table = group('<path/><text><tspan class="TextPosition" x="1" y="2"><tspan>A</tspan></tspan><tspan class="TextPosition" x="1" y="4"><tspan>B</tspan></tspan></text>')
    expect(settleTargets(component("com.sun.star.drawing.TableShape"), table).map((node) => node.tagName)).toEqual(["text", "text"])

    const graphic = group("<path/><path/>")
    expect(settleTargets(component("Graphic"), graphic)).toEqual([graphic])
  })
})

describe("materialize real compose fixtures", () => {
  it("splits the text fixture into one text per TextPosition without changing rendered text", () => {
    for (const fixtureComponent of textFixture.components.filter((entry) => entry.svg.includes("TextPosition"))) {
      const element = group(fixtureComponent.svg)
      const beforeText = Array.from(element.querySelectorAll("text")).map((node) => node.textContent).join("")
      const positionCount = element.querySelectorAll("tspan.TextPosition").length
      const lines = splitTextLines(element)
      expect(lines).toHaveLength(positionCount)
      expect(element.querySelectorAll("text")).toHaveLength(positionCount)
      expect(lines.map((line) => line.textContent).join("")).toBe(beforeText)
    }
  })

  it("settles the table fixture per text line", () => {
    const fixtureComponent = tableFixture.components[0]
    const element = group(fixtureComponent.svg)
    const targets = settleTargets(fixtureComponent, element)
    expect(targets.length).toBeGreaterThan(1)
    expect(targets.every((target) => target.tagName.toLowerCase() === "text")).toBe(true)
  })

  it("identifies the trimmed 250-path chart as heavy", () => {
    const element = group(chartFixture.components[0].svg)
    expect(element.querySelectorAll("path")).toHaveLength(250)
    expect(isHeavy(element)).toBe(true)
  })

  it("uses only opacity and transform styles/keyframes for a heavy Graphic", () => {
    const fixtureComponent = chartFixture.components[0]
    const element = group(fixtureComponent.svg)
    const keyframes: Keyframe[][] = []
    element.animate = vi.fn((frames) => {
      keyframes.push(Array.from(frames as Iterable<Keyframe>))
      return fakeAnimation()
    })
    const slide = document.createElement("div")
    const slideAnimations: { frames: Keyframe[]; options?: number | KeyframeAnimationOptions }[] = []
    slide.animate = vi.fn((frames, options) => {
      slideAnimations.push({ frames: Array.from(frames as Iterable<Keyframe>), options })
      return fakeAnimation()
    })

    markUnsettled(element, fixtureComponent)
    expect(element.style.filter).toBe("")
    const cancel = settle(slide, [{ component: fixtureComponent, element }])

    expect(keyframes).toHaveLength(1)
    expect(keyframes[0].every((frame) => !("filter" in frame))).toBe(true)
    expect(slideAnimations).toHaveLength(2)
    expect(slideAnimations.flatMap((entry) => entry.frames).every((frame) => !("boxShadow" in frame))).toBe(true)
    expect(slide.querySelector(".asp-breath-shadow")).toBeTruthy()
    expect(slideAnimations[1].frames).toEqual([
      { opacity: 0 },
      { opacity: 1, offset: 0.5 },
      { opacity: 0 },
    ])
    cancel()
    expect(slide.querySelector(".asp-breath-shadow")).toBeNull()
  })
})
