// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { existsSync, readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import { isHeavy, settleTargets, splitTextLines, type MaterializeComponent } from "./materialize"

const SVG_NS = "http://www.w3.org/2000/svg"
const fixture14Path = "/tmp/sdpm-fixtures/14.json"
const fixture20Path = "/tmp/sdpm-fixtures/20.json"

interface FixtureComponent extends MaterializeComponent {
  svg: string
}

function group(svg: string) {
  const element = document.createElementNS(SVG_NS, "g")
  element.innerHTML = svg
  return element
}

function component(className: string): MaterializeComponent {
  return { class: className, bbox: { x: 0, y: 0, w: 100, h: 100 } }
}

describe("materialize targets", () => {
  it("selects text lines, CustomShape frame then lines, TableShape lines, and whole Graphics", () => {
    const text = group('<text><tspan class="TextPosition" x="1" y="2"><tspan>A</tspan></tspan><tspan class="TextPosition" x="1" y="4"><tspan>B</tspan></tspan></text>')
    expect(settleTargets(component("TitleText"), text).map((node) => node.tagName)).toEqual(["text", "text"])

    const shape = group('<path id="frame"/><text><tspan class="TextPosition" x="1" y="2"><tspan>A</tspan></tspan></text>')
    expect(settleTargets(component("com.sun.star.drawing.CustomShape"), shape).map((node) => node.tagName)).toEqual(["path", "text"])

    const table = group('<path/><text><tspan class="TextPosition" x="1" y="2"><tspan>A</tspan></tspan><tspan class="TextPosition" x="1" y="4"><tspan>B</tspan></tspan></text>')
    expect(settleTargets(component("com.sun.star.drawing.TableShape"), table).map((node) => node.tagName)).toEqual(["text", "text"])

    const graphic = group('<path/><path/>')
    expect(settleTargets(component("Graphic"), graphic)).toEqual([graphic])
  })
})

describe.runIf(existsSync(fixture14Path) && existsSync(fixture20Path))("materialize real compose fixtures", () => {
  it("splits fixture 14 into one text per TextPosition without changing rendered text", () => {
    const fixture = JSON.parse(readFileSync(fixture14Path, "utf8")) as { components: FixtureComponent[] }
    for (const fixtureComponent of fixture.components.filter((entry) => entry.svg.includes("TextPosition"))) {
      const element = group(fixtureComponent.svg)
      const beforeText = Array.from(element.querySelectorAll("text")).map((node) => node.textContent).join("")
      const positionCount = element.querySelectorAll("tspan.TextPosition").length
      const lines = splitTextLines(element)
      expect(lines).toHaveLength(positionCount)
      expect(element.querySelectorAll("text")).toHaveLength(positionCount)
      expect(lines.map((line) => line.textContent).join("")).toBe(beforeText)
    }
  })

  it("identifies fixture 20's chart Graphic as heavy but not its icon Graphic", () => {
    const fixture = JSON.parse(readFileSync(fixture20Path, "utf8")) as { components: FixtureComponent[] }
    const graphics = fixture.components
      .filter((entry) => entry.class === "Graphic")
      .map((entry) => group(entry.svg))
    const chart = graphics.find((entry) => entry.querySelectorAll("path").length > 200)
    const icon = graphics.find((entry) => entry.querySelectorAll("path").length > 0 && entry.querySelectorAll("path").length <= 200)
    expect(chart).toBeDefined()
    expect(icon).toBeDefined()
    expect(isHeavy(chart!)).toBe(true)
    expect(isHeavy(icon!)).toBe(false)
  })
})
